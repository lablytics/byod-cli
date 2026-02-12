"""Job listing and detail endpoints."""

import asyncio
import io
import json
import logging
import mimetypes
import tarfile
import tempfile
from pathlib import Path
from typing import Optional

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse, StreamingResponse

logger = logging.getLogger(__name__)

router = APIRouter(tags=["jobs"])

RESULTS_BASE = Path(tempfile.gettempdir()) / "byod-results"

NONCE_SIZE = 12


def _get_api_client(request: Request):
    from byod_cli.api_client import APIClient

    config = request.app.state.config
    api_key = config.get_api_key()
    if not api_key:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return APIClient(api_url=config.get_api_url(), api_key=api_key)


@router.get("/jobs")
async def list_jobs(
    request: Request,
    limit: int = Query(50, ge=1, le=200),
    status: Optional[str] = Query(None),
    plugin: Optional[str] = Query(None),
):
    """List jobs with optional filters."""
    client = _get_api_client(request)
    try:
        jobs = await asyncio.to_thread(client.list_jobs, limit=limit, status=status, plugin=plugin)
        return jobs
    except Exception as e:
        logger.exception("Failed to list jobs")
        raise HTTPException(status_code=502, detail="Failed to fetch jobs. Check your API key and network.") from e


@router.get("/jobs/{job_id}")
async def get_job(request: Request, job_id: str):
    """Get a single job's status and details."""
    client = _get_api_client(request)
    try:
        job = await asyncio.to_thread(client.get_job_status, job_id)
        return job
    except Exception as e:
        logger.exception("Failed to get job %s", job_id)
        raise HTTPException(status_code=502, detail="Failed to fetch job details. Check your API key and network.") from e


@router.post("/jobs/{job_id}/get")
async def get_results(request: Request, job_id: str):
    """Download and decrypt results for a completed job.

    Mirrors the CLI `byod get` command:
    1. Download output.enc + output_key.bin via presigned URLs
    2. Unwrap the data key via boto3 KMS decrypt
    3. AES-256-GCM decrypt the results
    4. Extract tar.gz archive to output directory
    """
    client = _get_api_client(request)

    async def _stream():
        try:
            yield _sse("progress", {"stage": "checking", "percent": 5, "message": "Checking job status..."})

            job = await asyncio.to_thread(client.get_job_status, job_id)
            job_status = job.get("status", "")
            if job_status != "completed":
                yield _sse("error", {"message": f"Job is not completed (status: {job_status})"})
                return

            output_dir = RESULTS_BASE / job_id
            output_dir.mkdir(parents=True, exist_ok=True)

            # Step 1: Download encrypted results
            yield _sse("progress", {"stage": "downloading", "percent": 15, "message": "Downloading encrypted results..."})

            try:
                output_presigned = await asyncio.to_thread(client.get_download_url, job_id, "output.enc")
                await asyncio.to_thread(client.download_file, output_presigned, output_dir / "output.enc")
            except Exception:
                logger.exception("Failed to download results for job %s", job_id)
                yield _sse("error", {"message": "Failed to download results. Check the CLI logs for details."})
                return

            # Step 2: Download wrapped key
            yield _sse("progress", {"stage": "downloading", "percent": 35, "message": "Downloading wrapped key..."})

            try:
                key_presigned = await asyncio.to_thread(client.get_download_url, job_id, "output_key.bin")
                await asyncio.to_thread(client.download_file, key_presigned, output_dir / "output_key.bin")
            except Exception:
                logger.exception("Failed to download wrapped key for job %s", job_id)
                yield _sse("error", {"message": "Failed to download wrapped key. Check the CLI logs for details."})
                return

            # Step 3: Get tenant config for KMS region
            yield _sse("progress", {"stage": "unwrapping", "percent": 50, "message": "Getting tenant configuration..."})

            try:
                tenant_config = await asyncio.to_thread(client.get_tenant_config)
                kms_key_id = tenant_config.customer_kms_key_arn or tenant_config.kms_key_arn
                kms_region = tenant_config.region
            except Exception:
                logger.exception("Failed to get tenant config for job %s", job_id)
                yield _sse("error", {"message": "Failed to get tenant configuration. Check your API key and network."})
                return

            # Step 4: Unwrap key via KMS
            yield _sse("progress", {"stage": "unwrapping", "percent": 60, "message": "Unwrapping key via KMS..."})

            try:
                import boto3

                with open(output_dir / "output_key.bin", "rb") as f:
                    wrapped_key = f.read()

                kms = boto3.client("kms", region_name=kms_region)
                decrypt_response = await asyncio.to_thread(
                    kms.decrypt,
                    CiphertextBlob=wrapped_key,
                    KeyId=kms_key_id,
                )
                result_key = decrypt_response["Plaintext"]
            except Exception:
                logger.exception("KMS key unwrap failed for job %s", job_id)
                yield _sse("error", {"message": "KMS key unwrap failed. Check your AWS credentials and KMS key permissions."})
                return

            # Step 5: AES-256-GCM decrypt
            yield _sse("progress", {"stage": "decrypting", "percent": 75, "message": "Decrypting results..."})

            try:
                with open(output_dir / "output.enc", "rb") as f:
                    encrypted_data = f.read()

                nonce = encrypted_data[:NONCE_SIZE]
                ciphertext = encrypted_data[NONCE_SIZE:]
                aesgcm = AESGCM(result_key)
                plaintext = aesgcm.decrypt(nonce, ciphertext, None)
            except Exception:
                logger.exception("Decryption failed for job %s", job_id)
                yield _sse("error", {"message": "Decryption failed. The data may be corrupted or the key may not match."})
                return

            # Step 6: Extract results
            yield _sse("progress", {"stage": "extracting", "percent": 88, "message": "Extracting results..."})

            decrypted_dir = output_dir / "decrypted"
            decrypted_dir.mkdir(parents=True, exist_ok=True)
            extracted_files = []

            try:
                # Check if it's a tar.gz archive (gzip magic bytes: 1f 8b)
                if len(plaintext) > 2 and plaintext[0:2] == b'\x1f\x8b':
                    with tarfile.open(fileobj=io.BytesIO(plaintext), mode='r:gz') as tar:
                        for member in tar.getmembers():
                            if member.name == "__manifest__.json":
                                continue
                            tar.extract(member, path=decrypted_dir)
                            extracted_files.append(member.name)
                else:
                    # Not a tar.gz — write as raw file
                    raw_output = decrypted_dir / "output.bin"
                    with open(raw_output, "wb") as f:
                        f.write(plaintext)
                    extracted_files.append("output.bin")
            except tarfile.TarError:
                raw_output = decrypted_dir / "output.bin"
                with open(raw_output, "wb") as f:
                    f.write(plaintext)
                extracted_files.append("output.bin")

            # Clean up encrypted files
            (output_dir / "output.enc").unlink(missing_ok=True)
            (output_dir / "output_key.bin").unlink(missing_ok=True)

            yield _sse("progress", {"stage": "complete", "percent": 100, "message": "Results decrypted"})
            yield _sse("complete", {
                "output_dir": str(decrypted_dir),
                "files": extracted_files,
            })
        except Exception:
            logger.exception("Unexpected error retrieving results for job %s", job_id)
            yield _sse("error", {"message": "An unexpected error occurred. Check the CLI logs for details."})

    return StreamingResponse(_stream(), media_type="text/event-stream")


def _get_decrypted_dir(job_id: str) -> Path:
    """Get the decrypted results directory for a job, with path-traversal protection."""
    # Sanitize job_id to prevent path traversal
    safe_id = Path(job_id).name
    decrypted_dir = RESULTS_BASE / safe_id / "decrypted"
    # Verify it resolves under RESULTS_BASE
    if not decrypted_dir.resolve().is_relative_to(RESULTS_BASE.resolve()):
        raise HTTPException(status_code=400, detail="Invalid job ID")
    return decrypted_dir


@router.get("/jobs/{job_id}/results")
async def list_results(request: Request, job_id: str):
    """List decrypted result files for a job."""
    decrypted_dir = _get_decrypted_dir(job_id)

    if not decrypted_dir.exists():
        raise HTTPException(status_code=404, detail="Results not found. Run 'Get Results' first.")

    files = []
    for item in sorted(decrypted_dir.rglob("*")):
        if not item.is_file():
            continue
        rel = item.relative_to(decrypted_dir)
        mime, _ = mimetypes.guess_type(str(item))
        files.append({
            "path": str(rel).replace("\\", "/"),
            "name": item.name,
            "size": item.stat().st_size,
            "mime": mime or "application/octet-stream",
        })

    return {"files": files, "output_dir": str(decrypted_dir)}


@router.get("/jobs/{job_id}/results/file")
async def get_result_file(
    request: Request,
    job_id: str,
    path: str = Query(...),
    download: bool = Query(False),
):
    """Serve a single result file."""
    decrypted_dir = _get_decrypted_dir(job_id)
    file_path = decrypted_dir / path

    # Path-traversal protection
    if not file_path.resolve().is_relative_to(decrypted_dir.resolve()):
        raise HTTPException(status_code=400, detail="Invalid file path")

    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail="File not found")

    mime, _ = mimetypes.guess_type(str(file_path))
    # Only set filename (which triggers Content-Disposition: attachment) when
    # explicitly downloading. Otherwise serve inline so iframes/img tags work.
    return FileResponse(
        path=str(file_path),
        media_type=mime or "application/octet-stream",
        filename=file_path.name if download else None,
    )


def _sse(event: str, data: dict) -> str:
    """Format a Server-Sent Event."""
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"
