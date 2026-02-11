"""Extended tests for APIClient (byod_cli/api_client.py).

Covers methods not tested in Phase 1: get_job_status, list_jobs,
list_plugins, upload_file, download_file, get_download_url,
get_enclave_info, register_kms_setup, connection/timeout errors.
"""

from unittest.mock import MagicMock, patch

import pytest
import responses

from byod_cli.api_client import APIClient, APIError, AuthenticationError

API_URL = "https://api.lablytics.test"
API_KEY = "sk_live_test_key_123"


@pytest.fixture
def client():
    return APIClient(api_url=API_URL, api_key=API_KEY)


# ---------------------------------------------------------------------------
# get_job_status
# ---------------------------------------------------------------------------

class TestGetJobStatus:
    @responses.activate
    def test_success(self, client):
        responses.add(
            responses.GET,
            f"{API_URL}/api/v1/jobs/job-123",
            json={"job_id": "job-123", "status": "completed"},
        )
        result = client.get_job_status("job-123")
        assert result["status"] == "completed"

    @responses.activate
    def test_not_found(self, client):
        responses.add(
            responses.GET,
            f"{API_URL}/api/v1/jobs/nonexistent",
            json={"detail": "Job not found"},
            status=404,
        )
        with pytest.raises(APIError):
            client.get_job_status("nonexistent")


# ---------------------------------------------------------------------------
# list_jobs
# ---------------------------------------------------------------------------

class TestListJobs:
    @responses.activate
    def test_returns_jobs(self, client):
        responses.add(
            responses.GET,
            f"{API_URL}/api/v1/jobs",
            json={"jobs": [{"job_id": "j1"}, {"job_id": "j2"}]},
        )
        result = client.list_jobs()
        assert len(result) == 2

    @responses.activate
    def test_with_filters(self, client):
        responses.add(
            responses.GET,
            f"{API_URL}/api/v1/jobs",
            json={"jobs": [{"job_id": "j1", "status": "completed"}]},
        )
        result = client.list_jobs(limit=5, status="completed", plugin="demo")
        assert len(result) == 1
        # Verify query params were sent
        assert "limit=5" in responses.calls[0].request.url
        assert "status=completed" in responses.calls[0].request.url
        assert "plugin=demo" in responses.calls[0].request.url

    @responses.activate
    def test_empty_list(self, client):
        responses.add(
            responses.GET,
            f"{API_URL}/api/v1/jobs",
            json={"jobs": []},
        )
        result = client.list_jobs()
        assert result == []


# ---------------------------------------------------------------------------
# list_plugins
# ---------------------------------------------------------------------------

class TestListPlugins:
    @responses.activate
    def test_returns_plugins(self, client):
        responses.add(
            responses.GET,
            f"{API_URL}/api/v1/plugins",
            json={"plugins": [{"name": "demo-count"}, {"name": "genomic-qc"}]},
        )
        result = client.list_plugins()
        assert len(result) == 2
        assert result[0]["name"] == "demo-count"


# ---------------------------------------------------------------------------
# get_download_url
# ---------------------------------------------------------------------------

class TestGetDownloadUrl:
    @responses.activate
    def test_success(self, client):
        responses.add(
            responses.POST,
            f"{API_URL}/api/v1/jobs/job-123/download",
            json={
                "url": "https://s3.example.com/presigned",
                "s3_key": "results/job-123/output.enc",
                "expires_at": "2026-02-15T00:00:00Z",
            },
        )
        result = client.get_download_url("job-123", "output.enc")
        assert result.url == "https://s3.example.com/presigned"
        assert result.s3_key == "results/job-123/output.enc"


# ---------------------------------------------------------------------------
# upload_file / download_file
# ---------------------------------------------------------------------------

class TestUploadFile:
    @responses.activate
    def test_success(self, client, tmp_path):
        responses.add(responses.POST, "https://s3.example.com/upload", status=204)

        test_file = tmp_path / "data.enc"
        test_file.write_bytes(b"encrypted data")

        presigned = MagicMock()
        presigned.url = "https://s3.example.com/upload"
        presigned.fields = {"key": "uploads/data.enc"}

        client.upload_file(presigned, test_file)
        assert len(responses.calls) == 1

    @responses.activate
    def test_failure_raises(self, client, tmp_path):
        responses.add(responses.POST, "https://s3.example.com/upload", status=500)

        test_file = tmp_path / "data.enc"
        test_file.write_bytes(b"data")

        presigned = MagicMock()
        presigned.url = "https://s3.example.com/upload"
        presigned.fields = {}

        with pytest.raises(APIError, match="Upload failed"):
            client.upload_file(presigned, test_file)


class TestDownloadFile:
    @responses.activate
    def test_success(self, client, tmp_path):
        responses.add(
            responses.GET,
            "https://s3.example.com/download",
            body=b"file contents",
            status=200,
        )

        presigned = MagicMock()
        presigned.url = "https://s3.example.com/download"

        output_path = tmp_path / "output" / "data.bin"
        client.download_file(presigned, output_path)
        assert output_path.read_bytes() == b"file contents"

    @responses.activate
    def test_failure_raises(self, client, tmp_path):
        responses.add(
            responses.GET, "https://s3.example.com/download", status=403
        )

        presigned = MagicMock()
        presigned.url = "https://s3.example.com/download"

        with pytest.raises(APIError, match="Download failed"):
            client.download_file(presigned, tmp_path / "out.bin")


# ---------------------------------------------------------------------------
# get_enclave_info / register_kms_setup
# ---------------------------------------------------------------------------

class TestEnclaveInfo:
    @responses.activate
    def test_success(self, client):
        responses.add(
            responses.GET,
            f"{API_URL}/api/tenants/enclave/info",
            json={
                "pcr0": "abc123",
                "account_id": "506587498939",
                "tenant_id": "tenant-001",
            },
        )
        result = client.get_enclave_info()
        assert result["pcr0"] == "abc123"


class TestRegisterKmsSetup:
    @responses.activate
    def test_success(self, client):
        responses.add(
            responses.POST,
            f"{API_URL}/api/tenants/tenant/kms/register",
            json={"status": "registered"},
        )
        result = client.register_kms_setup(
            kms_key_arn="arn:aws:kms:us-east-1:111122223333:key/abc",
            role_arn="arn:aws:iam::111122223333:role/BYODRole",
            aws_account_id="111122223333",
            region="us-east-1",
        )
        assert result["status"] == "registered"


# ---------------------------------------------------------------------------
# Error handling edge cases
# ---------------------------------------------------------------------------

class TestErrorEdgeCases:
    def test_connection_error(self, client):
        import requests as req_lib
        with patch.object(req_lib.Session, "request", side_effect=req_lib.exceptions.ConnectionError("Connection refused")):
            with pytest.raises(APIError, match="connect"):
                client.verify_auth()

    @responses.activate
    def test_json_decode_error_in_error_response(self, client):
        """Non-JSON error body should still raise APIError with status text."""
        responses.add(
            responses.GET,
            f"{API_URL}/api/v1/auth/me",
            body="Internal Server Error",
            status=500,
        )
        with pytest.raises(APIError, match="Internal Server Error"):
            client.verify_auth()

    @responses.activate
    def test_403_raises_authentication_error(self, client):
        responses.add(
            responses.GET,
            f"{API_URL}/api/v1/auth/me",
            status=403,
        )
        with pytest.raises(AuthenticationError, match="Access denied"):
            client.verify_auth()
