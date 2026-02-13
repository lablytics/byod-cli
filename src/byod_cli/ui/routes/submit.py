"""Job submission endpoint with SSE progress."""

import asyncio
import io
import json
import logging
import os
import tarfile

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import StreamingResponse

logger = logging.getLogger(__name__)

router = APIRouter(tags=["submit"])

# Maximum total upload size (500 MB). Protects against memory exhaustion
# since uploaded files are buffered in memory for encryption.
MAX_UPLOAD_BYTES = 500 * 1024 * 1024


@router.post("/submit")
async def submit_job(
    request: Request,
    files: list[UploadFile] = File(...),
    plugin: str = Form(...),
    description: str = Form(""),
    config: str = Form("{}"),
):
    """Submit a job: receive files, encrypt locally, upload, and create job.

    Mirrors the CLI's submit command:
    - Single file: encrypt as-is
    - Multiple files: tar.gz together first (like CLI does with directories)

    Returns an SSE stream with progress updates.
    """
    from byod_cli.api_client import APIClient

    app_config = request.app.state.config
    api_key = app_config.get_api_key()
    if not api_key:
        raise HTTPException(status_code=401, detail="Not authenticated")

    if not files:
        raise HTTPException(status_code=400, detail="No files provided")

    client = APIClient(api_url=app_config.get_api_url(), api_key=api_key)

    # Parse pipeline config
    try:
        plugin_config = json.loads(config) if config and config != "{}" else None
    except json.JSONDecodeError:
        plugin_config = None

    # Read all uploaded file contents upfront (before streaming response)
    file_contents: list[tuple[str, bytes]] = []
    total_size = 0
    for f in files:
        content = await f.read()
        total_size += len(content)
        if total_size > MAX_UPLOAD_BYTES:
            raise HTTPException(
                status_code=413,
                detail=f"Total upload size exceeds {MAX_UPLOAD_BYTES // (1024 * 1024)} MB limit",
            )
        file_contents.append((f.filename or "upload", content))

    # Validate file types against plugin input spec
    from byod_cli.validation import validate_files_for_plugin

    try:
        available_plugins = await asyncio.to_thread(client.list_plugins)
    except Exception:
        available_plugins = []

    if available_plugins:
        plugin_meta = next((p for p in available_plugins if p["name"] == plugin), None)
        if plugin_meta is None:
            plugin_names = ", ".join(p["name"] for p in available_plugins)
            raise HTTPException(
                status_code=400,
                detail=f"Unknown plugin '{plugin}'. Available: {plugin_names}",
            )

        filenames = [name for name, _ in file_contents]
        validation_errors = validate_files_for_plugin(filenames, plugin_meta.get("inputs", []))
        if validation_errors:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid file types: {'; '.join(validation_errors)}",
            )

    async def _stream():
        tmp_dir = None
        try:
            yield _sse("progress", {"stage": "receiving", "percent": 5, "message": f"Received {len(file_contents)} file(s)..."})

            # Build the plaintext payload — tar.gz if multiple files, raw if single
            if len(file_contents) == 1:
                filename, plaintext = file_contents[0]
                upload_filename = f"{filename}.enc"
            else:
                yield _sse("progress", {"stage": "packaging", "percent": 10, "message": f"Packaging {len(file_contents)} files..."})
                buf = io.BytesIO()
                with tarfile.open(fileobj=buf, mode="w:gz") as tar:
                    for fname, content in file_contents:
                        info = tarfile.TarInfo(name=fname)
                        info.size = len(content)
                        tar.addfile(info, io.BytesIO(content))
                plaintext = buf.getvalue()
                upload_filename = "input.tar.gz.enc"

            file_size = len(plaintext)
            yield _sse("progress", {"stage": "encrypting", "percent": 15, "message": f"Encrypting ({_format_bytes(file_size)})..."})

            # Get KMS key from profile config
            profile = app_config.get_active_profile_config() if app_config.get_active_profile_name() else {}
            settings = profile.get("settings", {}) if profile else {}
            kms_key_arn = settings.get("kms_key_arn")

            if not kms_key_arn:
                yield _sse("error", {"message": "No KMS key configured. Run 'byod setup' first."})
                return

            import boto3

            kms_client = boto3.client("kms", region_name=settings.get("region", "us-east-1"))

            # Generate data encryption key
            dek_response = await asyncio.to_thread(
                kms_client.generate_data_key,
                KeyId=kms_key_arn,
                KeySpec="AES_256",
            )
            plaintext_dek = dek_response["Plaintext"]
            wrapped_dek = dek_response["CiphertextBlob"]

            yield _sse("progress", {"stage": "encrypting", "percent": 30, "message": "Encrypting data with AES-256-GCM..."})

            # Encrypt with AES-256-GCM
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM

            nonce = os.urandom(12)
            aesgcm = AESGCM(plaintext_dek)
            ciphertext = await asyncio.to_thread(aesgcm.encrypt, nonce, plaintext, None)
            encrypted_data = nonce + ciphertext

            yield _sse("progress", {"stage": "uploading_data", "percent": 45, "message": "Uploading encrypted data..."})

            # Get presigned URL and upload encrypted data
            presigned = await asyncio.to_thread(
                client.get_upload_url,
                filename=upload_filename,
                content_type="application/octet-stream",
                file_size=len(encrypted_data),
            )

            # Upload via presigned POST
            import requests as http_requests

            upload_resp = await asyncio.to_thread(
                http_requests.post,
                presigned.url,
                data=presigned.fields,
                files={"file": ("encrypted", encrypted_data)},
            )
            if upload_resp.status_code not in (200, 201, 204):
                yield _sse("error", {"message": f"Upload failed: HTTP {upload_resp.status_code}"})
                return

            yield _sse("progress", {"stage": "uploading_key", "percent": 65, "message": "Uploading wrapped key..."})

            # Upload wrapped DEK
            key_presigned = await asyncio.to_thread(
                client.get_upload_url,
                filename="wrapped_key.bin",
                content_type="application/octet-stream",
                file_size=len(wrapped_dek),
            )
            key_resp = await asyncio.to_thread(
                http_requests.post,
                key_presigned.url,
                data=key_presigned.fields,
                files={"file": ("wrapped_key", wrapped_dek)},
            )
            if key_resp.status_code not in (200, 201, 204):
                yield _sse("error", {"message": f"Key upload failed: HTTP {key_resp.status_code}"})
                return

            yield _sse("progress", {"stage": "submitting", "percent": 85, "message": "Creating job..."})

            # Submit the job
            submission = await asyncio.to_thread(
                client.submit_job,
                plugin_name=plugin,
                input_s3_key=presigned.s3_key,
                wrapped_key_s3_key=key_presigned.s3_key,
                description=description,
                config=plugin_config,
            )

            yield _sse("progress", {"stage": "done", "percent": 100, "message": "Job submitted!"})
            yield _sse("complete", {
                "job_id": submission.job_id,
                "status": submission.status,
            })
        except Exception as e:
            logger.exception("Job submission failed")
            yield _sse("error", {"message": _sanitize_error(e)})
        finally:
            # Clean up temp files
            if tmp_dir:
                import shutil

                shutil.rmtree(tmp_dir, ignore_errors=True)

    return StreamingResponse(_stream(), media_type="text/event-stream")


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


def _format_bytes(size: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024:
            return f"{size:.1f} {unit}" if unit != "B" else f"{size} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


def _sanitize_error(exc: Exception) -> str:
    """Return a safe error message — no AWS ARNs, key IDs, or account details."""
    from byod_cli.api_client import APIError, AuthenticationError

    if isinstance(exc, AuthenticationError):
        return "Authentication failed. Check your API key."
    if isinstance(exc, APIError):
        return f"API error: {exc}"

    msg = str(exc).lower()
    if "kms" in msg or "decrypt" in msg or "encrypt" in msg:
        return "Encryption operation failed. Check your KMS key configuration."
    if "connect" in msg or "timeout" in msg:
        return "Connection failed. Check your network and API URL."
    if "credential" in msg or "access denied" in msg or "not authorized" in msg:
        return "AWS access denied. Check your credentials and permissions."
    return "An unexpected error occurred. Check the CLI logs for details."
