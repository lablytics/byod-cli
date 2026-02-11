"""Tests for APIClient (byod_cli/api_client.py) with mocked HTTP."""

import pytest
import responses

from byod_cli.api_client import APIClient, APIError, AuthenticationError

BASE_URL = "https://byod.test.local"


@pytest.fixture
def api_client():
    return APIClient(api_url=BASE_URL, api_key="sk_live_test1234")


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------

class TestVerifyAuth:
    @responses.activate
    def test_success(self, api_client):
        responses.add(
            responses.GET,
            f"{BASE_URL}/api/v1/auth/me",
            json={"user_id": "u123", "email": "user@example.com"},
            status=200,
        )
        result = api_client.verify_auth()
        assert result["user_id"] == "u123"

    @responses.activate
    def test_unauthorized(self, api_client):
        responses.add(
            responses.GET,
            f"{BASE_URL}/api/v1/auth/me",
            json={"detail": "Invalid API key"},
            status=401,
        )
        with pytest.raises(AuthenticationError):
            api_client.verify_auth()


# ---------------------------------------------------------------------------
# Tenant config
# ---------------------------------------------------------------------------

class TestGetTenantConfig:
    @responses.activate
    def test_success(self, api_client):
        responses.add(
            responses.GET,
            f"{BASE_URL}/api/v1/tenant/config",
            json={
                "tenant_id": "t-001",
                "organization_name": "Test Lab",
                "region": "us-east-1",
                "data_bucket": "byod-data",
                "results_bucket": "byod-results",
                "kms_key_arn": None,
                "customer_kms_key_arn": "arn:aws:kms:us-east-1:111:key/abc",
                "tenant_prefix": "tenant-t001",
            },
            status=200,
        )
        config = api_client.get_tenant_config()
        assert config.tenant_id == "t-001"
        assert config.data_bucket == "byod-data"
        assert config.customer_kms_key_arn == "arn:aws:kms:us-east-1:111:key/abc"


# ---------------------------------------------------------------------------
# Upload URL
# ---------------------------------------------------------------------------

class TestGetUploadUrl:
    @responses.activate
    def test_success(self, api_client):
        responses.add(
            responses.POST,
            f"{BASE_URL}/api/v1/upload/presign",
            json={
                "url": "https://s3.amazonaws.com/bucket",
                "fields": {"key": "uploads/file.enc"},
                "s3_key": "uploads/file.enc",
                "expires_at": "2026-12-31T23:59:59Z",
            },
            status=200,
        )
        presigned = api_client.get_upload_url("file.enc")
        assert presigned.s3_key == "uploads/file.enc"


# ---------------------------------------------------------------------------
# Submit job
# ---------------------------------------------------------------------------

class TestSubmitJob:
    @responses.activate
    def test_success(self, api_client):
        responses.add(
            responses.POST,
            f"{BASE_URL}/api/v1/jobs",
            json={
                "job_id": "job-42",
                "status": "pending",
                "created_at": "2026-01-15T10:00:00Z",
                "input_s3_key": "uploads/input.tar.gz.enc",
                "wrapped_key_s3_key": "uploads/wrapped_dek.bin",
            },
            status=200,
        )
        job = api_client.submit_job(
            plugin_name="demo-count",
            input_s3_key="uploads/input.tar.gz.enc",
            wrapped_key_s3_key="uploads/wrapped_dek.bin",
        )
        assert job.job_id == "job-42"
        assert job.status == "pending"


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------

class TestErrorHandling:
    @responses.activate
    def test_server_error(self, api_client):
        responses.add(
            responses.GET,
            f"{BASE_URL}/api/v1/jobs",
            json={"detail": "Internal Server Error"},
            status=500,
        )
        with pytest.raises(APIError) as exc_info:
            api_client.list_jobs()
        assert exc_info.value.status_code == 500

    @responses.activate
    def test_forbidden(self, api_client):
        responses.add(
            responses.GET,
            f"{BASE_URL}/api/v1/tenant/config",
            json={"detail": "Forbidden"},
            status=403,
        )
        with pytest.raises(AuthenticationError):
            api_client.get_tenant_config()


# ---------------------------------------------------------------------------
# Headers
# ---------------------------------------------------------------------------

class TestHeaders:
    @responses.activate
    def test_authorization_header_sent(self, api_client):
        responses.add(
            responses.GET,
            f"{BASE_URL}/api/v1/auth/me",
            json={"user_id": "u1"},
            status=200,
        )
        api_client.verify_auth()
        assert responses.calls[0].request.headers["Authorization"] == "Bearer sk_live_test1234"

    @responses.activate
    def test_user_agent_header(self, api_client):
        responses.add(
            responses.GET,
            f"{BASE_URL}/api/v1/auth/me",
            json={"user_id": "u1"},
            status=200,
        )
        api_client.verify_auth()
        assert "byod-cli" in responses.calls[0].request.headers["User-Agent"]
