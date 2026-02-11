"""
S3 Client Module for BYOD CLI

Handles all S3 and KMS operations for the BYOD platform:
- Encrypting data with KMS-wrapped keys and uploading to S3
- Checking job status via S3 object presence
- Downloading encrypted results from S3
- Decrypting results using KMS key unwrapping

This module handles direct S3 communication. The enclave expects KMS-wrapped
keys (not locally-wrapped), so all key operations go through KMS.
"""

from __future__ import annotations

import io
import json
import logging
import os
import tarfile
from datetime import datetime
from pathlib import Path
from typing import Any

import boto3
from botocore.exceptions import ClientError
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

logger = logging.getLogger(__name__)

NONCE_SIZE = 12


class S3Client:
    """
    Client for BYOD platform S3 and KMS operations.

    Handles the full job lifecycle:
    - submit: encrypt data with KMS-generated DEK, upload to S3
    - status: check for job manifest and results in S3
    - retrieve: download encrypted results from S3
    - decrypt: unwrap result key via KMS and decrypt output
    """

    def __init__(
        self,
        region: str,
        data_bucket: str,
        results_bucket: str,
        kms_key_id: str,
    ) -> None:
        self.region = region
        self.data_bucket = data_bucket
        self.results_bucket = results_bucket
        self.kms_key_id = kms_key_id
        self.s3 = boto3.client("s3", region_name=region)
        self.kms = boto3.client("kms", region_name=region)

    def submit_job(
        self,
        input_path: Path,
        plugin_name: str,
        description: str | None = None,
        plugin_config: dict[str, Any] | None = None,
        tags: dict[str, str] | None = None,
    ) -> str:
        """
        Encrypt input data and submit as a job to S3.

        Steps:
        1. Generate a data encryption key (DEK) via KMS
        2. Encrypt input data with AES-256-GCM
        3. Upload encrypted data + KMS-wrapped key to S3
        4. Create and upload job manifest

        Args:
            input_path: Path to input file or directory
            plugin_name: Name of the pipeline plugin to run
            description: Human-readable job description
            plugin_config: Optional plugin configuration dict
            tags: Optional metadata tags

        Returns:
            Job ID string
        """
        job_id = f"{plugin_name}-{datetime.now().strftime('%Y%m%d%H%M%S')}-{os.urandom(4).hex()}"

        # Generate DEK via KMS
        logger.info("Generating data encryption key via KMS...")
        key_response = self.kms.generate_data_key(KeyId=self.kms_key_id, KeySpec="AES_256")
        plaintext_key = key_response["Plaintext"]
        wrapped_key = key_response["CiphertextBlob"]

        # Read and encrypt input data
        logger.info(f"Encrypting input data from {input_path}...")
        if input_path.is_dir():
            plaintext = self._read_directory(input_path)
        else:
            with open(input_path, "rb") as f:
                plaintext = f.read()

        encrypted_data = self._encrypt(plaintext, plaintext_key)
        logger.info(f"Encrypted {len(plaintext)} bytes -> {len(encrypted_data)} bytes")

        # Upload paths
        input_key = f"data/{job_id}/input.enc"
        wrapped_key_key = f"data/{job_id}/wrapped_key.bin"
        manifest_key = f"jobs/{job_id}.json"

        # Upload encrypted data
        logger.info(f"Uploading encrypted data to s3://{self.data_bucket}/{input_key}")
        self.s3.put_object(
            Bucket=self.data_bucket,
            Key=input_key,
            Body=encrypted_data,
            ServerSideEncryption="aws:kms",
            SSEKMSKeyId=self.kms_key_id,
        )

        # Upload wrapped key
        logger.info(f"Uploading wrapped key to s3://{self.data_bucket}/{wrapped_key_key}")
        self.s3.put_object(
            Bucket=self.data_bucket,
            Key=wrapped_key_key,
            Body=wrapped_key,
            ServerSideEncryption="aws:kms",
            SSEKMSKeyId=self.kms_key_id,
        )

        # Create and upload job manifest
        output_key = f"results/{job_id}/output.enc"
        job_manifest: dict[str, Any] = {
            "job_id": job_id,
            "user_id": os.environ.get("USER", "cli-user"),
            "plugin_name": plugin_name,
            "input_s3_key": input_key,
            "output_s3_key": output_key,
            "wrapped_key_s3_key": wrapped_key_key,
            "created_at": datetime.utcnow().isoformat() + "Z",
            "config": {
                "description": description or f"{plugin_name} job",
                **(plugin_config or {}),
            },
            "tags": tags or {},
        }

        logger.info(f"Uploading job manifest to s3://{self.data_bucket}/{manifest_key}")
        self.s3.put_object(
            Bucket=self.data_bucket,
            Key=manifest_key,
            Body=json.dumps(job_manifest, indent=2),
            ServerSideEncryption="aws:kms",
            SSEKMSKeyId=self.kms_key_id,
        )

        # Best effort to clear plaintext key from memory
        if isinstance(plaintext_key, bytearray):
            for i in range(len(plaintext_key)):
                plaintext_key[i] = 0

        return job_id

    def get_job_status(self, job_id: str) -> dict[str, Any]:
        """
        Check job status by examining S3 objects.

        Status is determined by:
        - Job manifest exists in data bucket -> submitted
        - Results exist in results bucket -> completed
        - Neither -> unknown
        """
        status_info: dict[str, Any] = {
            "job_id": job_id,
            "status": "unknown",
        }

        # Check for job manifest
        manifest_key = f"jobs/{job_id}.json"
        try:
            response = self.s3.get_object(Bucket=self.data_bucket, Key=manifest_key)
            manifest = json.loads(response["Body"].read().decode("utf-8"))
            status_info["plugin"] = manifest.get("plugin_name", "unknown")
            status_info["submitted_at"] = manifest.get("created_at", "unknown")
            status_info["description"] = manifest.get("config", {}).get("description", "")
            status_info["tags"] = manifest.get("tags", {})
            status_info["status"] = "submitted"
        except ClientError as e:
            if e.response["Error"]["Code"] == "NoSuchKey":
                status_info["status"] = "not_found"
                return status_info
            raise

        # Check for results
        try:
            result_objects = self.s3.list_objects_v2(
                Bucket=self.results_bucket,
                Prefix=f"results/{job_id}/",
            )
            if "Contents" in result_objects and len(result_objects["Contents"]) > 0:
                status_info["status"] = "completed"
                status_info["result_files"] = [
                    {"key": obj["Key"], "size": obj["Size"]}
                    for obj in result_objects["Contents"]
                ]
                latest = max(obj["LastModified"] for obj in result_objects["Contents"])
                status_info["completed_at"] = latest.isoformat()
            else:
                status_info["status"] = "processing"
        except ClientError:
            status_info["status"] = "processing"

        return status_info

    def download_results(self, job_id: str, output_dir: Path) -> Path:
        """
        Download encrypted results and wrapped key from S3.

        Creates a results manifest in the output directory for use by
        the decrypt command.
        """
        output_dir.mkdir(parents=True, exist_ok=True)

        output_key = f"results/{job_id}/output.enc"
        result_key_key = f"results/{job_id}/output_key.bin"

        # Download encrypted results
        logger.info(f"Downloading s3://{self.results_bucket}/{output_key}")
        try:
            response = self.s3.get_object(Bucket=self.results_bucket, Key=output_key)
            encrypted_data = response["Body"].read()
        except ClientError as e:
            if e.response["Error"]["Code"] == "NoSuchKey":
                raise FileNotFoundError(
                    f"No results found for job {job_id}. The job may still be processing."
                ) from e
            raise

        enc_path = output_dir / "output.enc"
        with open(enc_path, "wb") as f:
            f.write(encrypted_data)
        logger.info(f"Saved encrypted results: {enc_path} ({len(encrypted_data)} bytes)")

        # Download wrapped result key
        logger.info(f"Downloading s3://{self.results_bucket}/{result_key_key}")
        try:
            response = self.s3.get_object(Bucket=self.results_bucket, Key=result_key_key)
            wrapped_key = response["Body"].read()
        except ClientError as e:
            if e.response["Error"]["Code"] == "NoSuchKey":
                raise FileNotFoundError(
                    f"No result key found for job {job_id}. Results may be incomplete."
                ) from e
            raise

        key_path = output_dir / "output_key.bin"
        with open(key_path, "wb") as f:
            f.write(wrapped_key)
        logger.info(f"Saved wrapped key: {key_path} ({len(wrapped_key)} bytes)")

        # Create results manifest
        manifest: dict[str, Any] = {
            "job_id": job_id,
            "encrypted_file": "output.enc",
            "wrapped_key_file": "output_key.bin",
            "kms_key_id": self.kms_key_id,
            "region": self.region,
            "downloaded_at": datetime.now().isoformat(),
            "encrypted_size": len(encrypted_data),
            "wrapped_key_size": len(wrapped_key),
        }

        manifest_path = output_dir / "results-manifest.json"
        with open(manifest_path, "w") as f:
            json.dump(manifest, f, indent=2)
        logger.info(f"Created results manifest: {manifest_path}")

        return output_dir

    def decrypt_results(self, results_dir: Path, output_path: Path) -> dict[str, Any]:
        """
        Decrypt downloaded results using KMS to unwrap the key.

        Steps:
        1. Load results manifest
        2. Unwrap the result key via KMS
        3. Decrypt the encrypted output with AES-256-GCM
        """
        manifest_path = results_dir / "results-manifest.json"
        if not manifest_path.exists():
            raise FileNotFoundError(
                f"Results manifest not found at {manifest_path}. "
                "Run 'byod retrieve' first to download results."
            )

        with open(manifest_path) as f:
            manifest = json.load(f)

        # Read wrapped key
        key_path = results_dir / manifest["wrapped_key_file"]
        with open(key_path, "rb") as f:
            wrapped_key = f.read()

        # Unwrap key via KMS
        kms_key_id = manifest.get("kms_key_id", self.kms_key_id)
        logger.info("Unwrapping result key via KMS...")
        try:
            decrypt_response = self.kms.decrypt(CiphertextBlob=wrapped_key, KeyId=kms_key_id)
            result_key = decrypt_response["Plaintext"]
            logger.info(f"Key unwrapped successfully ({len(result_key)} bytes)")
        except ClientError as e:
            raise RuntimeError(
                f"Failed to unwrap result key via KMS: {e}. "
                "Ensure your AWS credentials have KMS Decrypt permission "
                "for the key used by the enclave."
            ) from e

        # Read encrypted results
        enc_path = results_dir / manifest["encrypted_file"]
        with open(enc_path, "rb") as f:
            encrypted_data = f.read()

        # Decrypt: format is [nonce (12 bytes)][ciphertext + tag]
        plaintext = self._decrypt(encrypted_data, result_key)

        # Write decrypted output
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "wb") as f:
            f.write(plaintext)

        logger.info(f"Decrypted results written to {output_path}")

        # Best effort key wipe
        if isinstance(result_key, bytearray):
            for i in range(len(result_key)):
                result_key[i] = 0

        return {
            "decrypted_size": len(plaintext),
            "output_path": str(output_path),
            "job_id": manifest["job_id"],
        }

    def list_jobs(self, limit: int = 50) -> list[dict[str, Any]]:
        """List recent jobs by scanning job manifests in S3."""
        jobs: list[dict[str, Any]] = []

        try:
            paginator = self.s3.get_paginator("list_objects_v2")
            pages = paginator.paginate(Bucket=self.data_bucket, Prefix="jobs/")

            manifest_keys: list[str] = []
            for page in pages:
                for obj in page.get("Contents", []):
                    if obj["Key"].endswith(".json"):
                        manifest_keys.append(obj["Key"])

            # Sort by key name (contains timestamp) descending
            manifest_keys.sort(reverse=True)
            manifest_keys = manifest_keys[:limit]

            for key in manifest_keys:
                try:
                    response = self.s3.get_object(Bucket=self.data_bucket, Key=key)
                    manifest = json.loads(response["Body"].read().decode("utf-8"))
                    job_id = manifest.get("job_id", key.split("/")[-1].replace(".json", ""))
                    has_results = self._results_exist(job_id)

                    jobs.append(
                        {
                            "job_id": job_id,
                            "plugin": manifest.get("plugin_name", "unknown"),
                            "status": "completed" if has_results else "processing",
                            "submitted_at": manifest.get("created_at", "unknown"),
                            "description": manifest.get("config", {}).get("description", ""),
                        }
                    )
                except Exception as e:
                    logger.warning(f"Failed to read manifest {key}: {e}")

        except ClientError as e:
            logger.error(f"Failed to list jobs: {e}")

        return jobs

    def _results_exist(self, job_id: str) -> bool:
        """Check if results exist for a job."""
        try:
            response = self.s3.list_objects_v2(
                Bucket=self.results_bucket,
                Prefix=f"results/{job_id}/",
                MaxKeys=1,
            )
            return "Contents" in response and len(response["Contents"]) > 0
        except ClientError:
            return False

    def _read_directory(self, dir_path: Path) -> bytes:
        """Read all files in a directory into a tar.gz archive."""
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz") as tar:
            tar.add(str(dir_path), arcname=dir_path.name)
        return buf.getvalue()

    @staticmethod
    def _encrypt(plaintext: bytes, key: bytes) -> bytes:
        """
        Encrypt data with AES-256-GCM.

        Format: [nonce (12 bytes)][ciphertext + tag]
        No associated data (matches enclave expectations).
        """
        nonce = os.urandom(NONCE_SIZE)
        aesgcm = AESGCM(key)
        ciphertext = aesgcm.encrypt(nonce, plaintext, None)
        return nonce + ciphertext

    @staticmethod
    def _decrypt(encrypted: bytes, key: bytes) -> bytes:
        """
        Decrypt data with AES-256-GCM.

        Format: [nonce (12 bytes)][ciphertext + tag]
        """
        nonce = encrypted[:NONCE_SIZE]
        ciphertext = encrypted[NONCE_SIZE:]
        aesgcm = AESGCM(key)
        return aesgcm.decrypt(nonce, ciphertext, None)
