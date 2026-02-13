"""
API Client Module for BYOD CLI

Handles authentication and communication with the Lablytics BYOD platform.
The platform manages all infrastructure (buckets, KMS keys) and provides
presigned URLs for secure data upload/download.

Security Model:
--------------
- Customer authenticates with API key (obtained from dashboard)
- Platform returns presigned URLs for S3 operations
- Customer never needs direct S3/KMS credentials
- All bucket policies are controlled by Lablytics
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import requests

logger = logging.getLogger(__name__)

DEFAULT_API_URL = "https://byod.cultivatedcode.co/"
DEFAULT_TIMEOUT = 30


@dataclass
class TenantConfig:
    """Configuration returned from the platform for a tenant."""

    tenant_id: str
    organization_name: str
    region: str
    data_bucket: str
    results_bucket: str
    kms_key_arn: str | None  # None if using customer-owned KMS
    customer_kms_key_arn: str | None  # Set if customer brought their own KMS
    tenant_prefix: str  # e.g., "tenant-abc123" - path prefix in buckets


@dataclass
class PresignedUpload:
    """Presigned URL and fields for S3 upload."""

    url: str
    fields: dict[str, str]
    s3_key: str
    expires_at: datetime


@dataclass
class PresignedDownload:
    """Presigned URL for S3 download."""

    url: str
    s3_key: str
    expires_at: datetime


@dataclass
class JobSubmission:
    """Response from job submission."""

    job_id: str
    status: str
    created_at: datetime
    input_s3_key: str
    wrapped_key_s3_key: str


class APIError(Exception):
    """API request failed."""

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class AuthenticationError(APIError):
    """Authentication failed."""

    pass


class APIClient:
    """
    Client for the Lablytics BYOD Platform API.

    Handles:
    - Authentication with API keys
    - Fetching tenant configuration (buckets, KMS keys)
    - Getting presigned URLs for upload/download
    - Job submission and status checking
    """

    def __init__(
        self,
        api_url: str = DEFAULT_API_URL,
        api_key: str | None = None,
        timeout: int = DEFAULT_TIMEOUT,
    ) -> None:
        # Enforce HTTPS to prevent credentials being sent in plaintext.
        # Allow HTTP only for localhost (local UI server) and explicit test URLs.
        if not api_url.startswith("https://"):
            from urllib.parse import urlparse

            host = urlparse(api_url).hostname or ""
            if host not in ("localhost", "127.0.0.1", "0.0.0.0"):
                logger.warning(
                    "API URL uses HTTP instead of HTTPS — credentials may be sent in plaintext. "
                    "Set BYOD_API_URL to an https:// URL for production use."
                )

        self.api_url = api_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout
        self.session = requests.Session()

        if api_key:
            self.session.headers.update({"Authorization": f"Bearer {api_key}"})

        self.session.headers.update(
            {
                "Content-Type": "application/json",
                "User-Agent": "byod-cli/1.0.0",
            }
        )

    def _request(
        self,
        method: str,
        endpoint: str,
        data: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Make an authenticated API request."""
        url = urljoin(self.api_url + "/", endpoint.lstrip("/"))

        try:
            response = self.session.request(
                method=method,
                url=url,
                json=data,
                params=params,
                timeout=self.timeout,
            )

            if response.status_code == 401:
                raise AuthenticationError(
                    "Invalid or expired API key. Run 'byod auth login' to authenticate.",
                    status_code=401,
                )

            if response.status_code == 403:
                raise AuthenticationError(
                    "Access denied. Check your API key permissions.",
                    status_code=403,
                )

            if not response.ok:
                error_msg = response.text
                try:
                    error_data = response.json()
                    error_msg = error_data.get("detail", error_data.get("message", error_msg))
                except json.JSONDecodeError:
                    pass
                raise APIError(f"API error: {error_msg}", status_code=response.status_code)

            return response.json()

        except requests.exceptions.ConnectionError:
            raise APIError(f"Failed to connect to {self.api_url}. Check your network connection.") from None
        except requests.exceptions.Timeout:
            raise APIError(f"Request timed out after {self.timeout}s") from None

    def verify_auth(self) -> dict[str, Any]:
        """Verify authentication and get current user info."""
        return self._request("GET", "/api/v1/auth/me")

    def get_tenant_config(self) -> TenantConfig:
        """Get the tenant's platform configuration."""
        data = self._request("GET", "/api/v1/tenant/config")

        return TenantConfig(
            tenant_id=data["tenant_id"],
            organization_name=data["organization_name"],
            region=data["region"],
            data_bucket=data["data_bucket"],
            results_bucket=data["results_bucket"],
            kms_key_arn=data.get("kms_key_arn"),
            customer_kms_key_arn=data.get("customer_kms_key_arn"),
            tenant_prefix=data["tenant_prefix"],
        )

    def get_upload_url(
        self,
        filename: str,
        content_type: str = "application/octet-stream",
        file_size: int | None = None,
    ) -> PresignedUpload:
        """Get a presigned URL for uploading encrypted data."""
        data = self._request(
            "POST",
            "/api/v1/upload/presign",
            data={
                "filename": filename,
                "content_type": content_type,
                "file_size": file_size,
            },
        )

        return PresignedUpload(
            url=data["url"],
            fields=data["fields"],
            s3_key=data["s3_key"],
            expires_at=datetime.fromisoformat(data["expires_at"].replace("Z", "+00:00")),
        )

    def get_download_url(self, job_id: str, filename: str = "output.enc") -> PresignedDownload:
        """Get a presigned URL for downloading encrypted results."""
        data = self._request(
            "POST",
            f"/api/v1/jobs/{job_id}/download",
            data={"filename": filename},
        )

        return PresignedDownload(
            url=data["url"],
            s3_key=data["s3_key"],
            expires_at=datetime.fromisoformat(data["expires_at"].replace("Z", "+00:00")),
        )

    def submit_job(
        self,
        plugin_name: str,
        input_s3_key: str,
        wrapped_key_s3_key: str,
        description: str | None = None,
        config: dict[str, Any] | None = None,
        tags: dict[str, str] | None = None,
    ) -> JobSubmission:
        """Submit a job for processing."""
        data = self._request(
            "POST",
            "/api/v1/jobs",
            data={
                "plugin_name": plugin_name,
                "input_s3_key": input_s3_key,
                "wrapped_key_s3_key": wrapped_key_s3_key,
                "description": description,
                "config": config or {},
                "tags": tags or {},
            },
        )

        return JobSubmission(
            job_id=data["job_id"],
            status=data["status"],
            created_at=datetime.fromisoformat(data["created_at"].replace("Z", "+00:00")),
            input_s3_key=data["input_s3_key"],
            wrapped_key_s3_key=data["wrapped_key_s3_key"],
        )

    def get_job_status(self, job_id: str) -> dict[str, Any]:
        """Get job status."""
        return self._request("GET", f"/api/v1/jobs/{job_id}")

    def list_jobs(
        self,
        limit: int = 20,
        status: str | None = None,
        plugin: str | None = None,
    ) -> list[dict[str, Any]]:
        """List jobs for the current tenant."""
        params: dict[str, Any] = {"limit": limit}
        if status:
            params["status"] = status
        if plugin:
            params["plugin"] = plugin

        data = self._request("GET", "/api/v1/jobs", params=params)
        return data.get("jobs", [])

    def list_plugins(self) -> list[dict[str, Any]]:
        """List available pipeline plugins."""
        data = self._request("GET", "/api/v1/plugins")
        return data.get("plugins", [])

    def get_job_logs(
        self,
        job_id: str,
        limit: int = 1000,
        level: str | None = None,
        source: str | None = None,
        since: str | None = None,
    ) -> dict[str, Any]:
        """Get logs for a specific job."""
        params: dict[str, Any] = {"limit": limit}
        if level:
            params["level"] = level
        if source:
            params["source"] = source
        if since:
            params["since"] = since
        return self._request("GET", f"/api/v1/jobs/{job_id}/logs", params=params)

    def upload_file(self, presigned: PresignedUpload, file_path: Path) -> None:
        """Upload a file using a presigned POST URL."""
        with open(file_path, "rb") as f:
            files = {"file": (file_path.name, f)}
            response = requests.post(
                presigned.url,
                data=presigned.fields,
                files=files,
                timeout=300,
            )

            if not response.ok:
                raise APIError(
                    f"Upload failed: {response.status_code} {response.text}",
                    status_code=response.status_code,
                )

    def download_file(self, presigned: PresignedDownload, output_path: Path) -> None:
        """Download a file using a presigned GET URL."""
        response = requests.get(presigned.url, stream=True, timeout=300)

        if not response.ok:
            raise APIError(
                f"Download failed: {response.status_code}",
                status_code=response.status_code,
            )

        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "wb") as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)

    def get_enclave_info(self) -> dict[str, Any]:
        """
        Get enclave info needed for CLI setup.

        Returns:
            dict with:
            - pcr0: Nitro Enclave PCR0 attestation value
            - account_id: Lablytics AWS account ID
            - tenant_id: Current tenant's ID
        """
        return self._request("GET", "/api/tenants/enclave/info")

    def register_kms_setup(
        self,
        kms_key_arn: str,
        role_arn: str,
        aws_account_id: str,
        region: str,
    ) -> dict[str, Any]:
        """
        Register customer's KMS key and role after CLI setup.

        Called after `byod setup` creates:
        1. KMS key with attestation policy
        2. Cross-account IAM role

        Args:
            kms_key_arn: ARN of the KMS key created in customer's account
            role_arn: ARN of the cross-account IAM role
            aws_account_id: Customer's AWS account ID (12 digits)
            region: AWS region where resources were created

        Returns:
            dict with registration confirmation
        """
        return self._request(
            "POST",
            "/api/tenants/tenant/kms/register",
            data={
                "kms_key_arn": kms_key_arn,
                "role_arn": role_arn,
                "aws_account_id": aws_account_id,
                "region": region,
            },
        )
