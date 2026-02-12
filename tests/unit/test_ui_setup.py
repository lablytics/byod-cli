"""Tests for UI setup wizard routes."""

import json
from unittest.mock import MagicMock, patch


def _parse_sse(text: str) -> list:
    """Parse SSE text into a list of {event, data} dicts."""
    events = []
    current_event = None
    current_data = None

    for line in text.split("\n"):
        if line.startswith("event: "):
            current_event = line[7:]
        elif line.startswith("data: "):
            current_data = line[6:]
        elif line == "" and current_event and current_data:
            try:
                events.append({"event": current_event, "data": json.loads(current_data)})
            except json.JSONDecodeError:
                events.append({"event": current_event, "data": current_data})
            current_event = None
            current_data = None

    return events


class TestSetupStatus:
    """Tests for GET /api/setup/status."""

    @patch("boto3.client")
    def test_setup_status_unconfigured(self, mock_boto3, ui_client):
        mock_boto3.side_effect = Exception("No credentials")

        resp = ui_client.get("/api/setup/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["authenticated"] is False
        assert data["aws_configured"] is False
        assert data["kms_key_configured"] is False
        assert data["role_configured"] is False
        assert data["registered"] is False

    @patch("boto3.client")
    @patch("byod_cli.api_client.APIClient")
    def test_setup_status_fully_configured(self, MockAPIClient, mock_boto3, ui_client_authed):
        mock_client = MagicMock()
        mock_client.verify_auth.return_value = {"tenant_id": "tenant-abc"}
        MockAPIClient.return_value = mock_client

        mock_sts = MagicMock()
        mock_sts.get_caller_identity.return_value = {"Account": "123456789"}
        mock_iam = MagicMock()
        mock_iam.get_role.return_value = {"Role": {}}
        mock_kms = MagicMock()
        mock_kms.describe_key.return_value = {"KeyMetadata": {"KeyState": "Enabled"}}

        def client_factory(service, **kwargs):
            if service == "sts":
                return mock_sts
            if service == "iam":
                return mock_iam
            if service == "kms":
                return mock_kms
            return MagicMock()

        mock_boto3.side_effect = client_factory

        resp = ui_client_authed.get("/api/setup/status")
        data = resp.json()
        assert data["authenticated"] is True
        assert data["aws_configured"] is True
        assert data["aws_account_id"] == "123456789"
        assert data["tenant_valid"] is True
        assert data["kms_key_configured"] is True
        assert data["role_configured"] is True
        assert data["registered"] is True

    @patch("boto3.client")
    @patch("byod_cli.api_client.APIClient")
    def test_setup_status_role_deleted(self, MockAPIClient, mock_boto3, ui_client_authed):
        from botocore.exceptions import ClientError

        mock_client = MagicMock()
        mock_client.verify_auth.return_value = {"tenant_id": "tenant-abc"}
        MockAPIClient.return_value = mock_client

        mock_sts = MagicMock()
        mock_sts.get_caller_identity.return_value = {"Account": "123456789"}
        mock_iam = MagicMock()
        mock_iam.get_role.side_effect = ClientError(
            {"Error": {"Code": "NoSuchEntity", "Message": "not found"}},
            "GetRole",
        )
        mock_kms = MagicMock()
        mock_kms.describe_key.return_value = {"KeyMetadata": {"KeyState": "Enabled"}}

        def client_factory(service, **kwargs):
            if service == "sts":
                return mock_sts
            if service == "iam":
                return mock_iam
            if service == "kms":
                return mock_kms
            return MagicMock()

        mock_boto3.side_effect = client_factory

        resp = ui_client_authed.get("/api/setup/status")
        data = resp.json()
        assert data["role_configured"] is False
        assert "no longer exists" in data["role_error"].lower()
        assert data["registered"] is False  # both must be configured


class TestRunSetup:
    """Tests for POST /api/setup/run."""

    def test_run_setup_unauthenticated(self, ui_client):
        resp = ui_client.post("/api/setup/run", json={"region": "us-east-1"})
        assert resp.status_code == 401

    @patch("boto3.client")
    @patch("byod_cli.api_client.APIClient")
    def test_run_setup_no_tenant(self, MockAPIClient, mock_boto3, ui_client_authed):
        mock_client = MagicMock()
        mock_client.verify_auth.return_value = {}  # No tenant_id
        MockAPIClient.return_value = mock_client

        resp = ui_client_authed.post("/api/setup/run", json={"region": "us-east-1"})
        events = _parse_sse(resp.text)
        error_events = [e for e in events if e["event"] == "error"]
        assert len(error_events) > 0
        assert "not associated" in error_events[0]["data"]["message"].lower()

    @patch("asyncio.sleep", return_value=None)
    @patch("boto3.client")
    @patch("byod_cli.api_client.APIClient")
    def test_run_setup_happy_path(self, MockAPIClient, mock_boto3, mock_sleep, ui_client_authed):
        mock_client = MagicMock()
        mock_client.verify_auth.return_value = {"tenant_id": "tenant-abc123"}
        mock_client.get_enclave_info.return_value = {
            "pcr0": "abc123",
            "pcr0_values": ["abc123", "def456"],
            "account_id": "506587498939",
        }
        mock_client.register_kms_setup.return_value = None
        MockAPIClient.return_value = mock_client

        mock_sts = MagicMock()
        mock_sts.get_caller_identity.return_value = {"Account": "123456789012"}
        mock_iam = MagicMock()
        mock_iam.create_role.return_value = {
            "Role": {"Arn": "arn:aws:iam::123456789012:role/BYODEnclaveRole-tenant-abc123xx"},
        }
        mock_kms = MagicMock()
        mock_kms.create_key.return_value = {
            "KeyMetadata": {
                "Arn": "arn:aws:kms:us-east-1:123456789012:key/new-key-id",
                "KeyId": "new-key-id",
            },
        }

        def client_factory(service, **kwargs):
            if service == "sts":
                return mock_sts
            if service == "iam":
                return mock_iam
            if service == "kms":
                return mock_kms
            return MagicMock()

        mock_boto3.side_effect = client_factory

        resp = ui_client_authed.post("/api/setup/run", json={"region": "us-east-1"})
        events = _parse_sse(resp.text)

        event_types = [e["event"] for e in events]
        assert "progress" in event_types
        assert "complete" in event_types
        assert "error" not in event_types

        complete_event = next(e for e in events if e["event"] == "complete")
        assert "kms_key_arn" in complete_event["data"]
        assert "role_arn" in complete_event["data"]

    @patch("asyncio.sleep", return_value=None)
    @patch("boto3.client")
    @patch("byod_cli.api_client.APIClient")
    def test_run_setup_role_already_exists(self, MockAPIClient, mock_boto3, mock_sleep, ui_client_authed):
        from botocore.exceptions import ClientError

        mock_client = MagicMock()
        mock_client.verify_auth.return_value = {"tenant_id": "tenant-abc123"}
        mock_client.get_enclave_info.return_value = {
            "pcr0": "abc123",
            "account_id": "506587498939",
        }
        mock_client.register_kms_setup.return_value = None
        MockAPIClient.return_value = mock_client

        mock_sts = MagicMock()
        mock_sts.get_caller_identity.return_value = {"Account": "123456789012"}
        mock_iam = MagicMock()
        mock_iam.create_role.side_effect = ClientError(
            {"Error": {"Code": "EntityAlreadyExists", "Message": "Role exists"}},
            "CreateRole",
        )
        mock_kms = MagicMock()
        mock_kms.create_key.return_value = {
            "KeyMetadata": {
                "Arn": "arn:aws:kms:us-east-1:123456789012:key/new-key-id",
                "KeyId": "new-key-id",
            },
        }

        def client_factory(service, **kwargs):
            if service == "sts":
                return mock_sts
            if service == "iam":
                return mock_iam
            if service == "kms":
                return mock_kms
            return MagicMock()

        mock_boto3.side_effect = client_factory

        resp = ui_client_authed.post("/api/setup/run", json={"region": "us-east-1"})
        events = _parse_sse(resp.text)

        # Should still succeed — role reuse path
        event_types = [e["event"] for e in events]
        assert "complete" in event_types
        assert "error" not in event_types
        # Should have updated the trust policy
        mock_iam.update_assume_role_policy.assert_called_once()

    @patch("asyncio.sleep", return_value=None)
    @patch("boto3.client")
    @patch("byod_cli.api_client.APIClient")
    def test_run_setup_kms_failure(self, MockAPIClient, mock_boto3, mock_sleep, ui_client_authed):
        from botocore.exceptions import ClientError

        mock_client = MagicMock()
        mock_client.verify_auth.return_value = {"tenant_id": "tenant-abc123"}
        mock_client.get_enclave_info.return_value = {
            "pcr0": "abc123",
            "account_id": "506587498939",
        }
        MockAPIClient.return_value = mock_client

        mock_sts = MagicMock()
        mock_sts.get_caller_identity.return_value = {"Account": "123456789012"}
        mock_iam = MagicMock()
        mock_iam.create_role.return_value = {
            "Role": {"Arn": "arn:aws:iam::123456789012:role/BYODEnclaveRole-test"},
        }
        mock_kms = MagicMock()
        mock_kms.create_key.side_effect = ClientError(
            {"Error": {"Code": "LimitExceededException", "Message": "Too many keys"}},
            "CreateKey",
        )

        def client_factory(service, **kwargs):
            if service == "sts":
                return mock_sts
            if service == "iam":
                return mock_iam
            if service == "kms":
                return mock_kms
            return MagicMock()

        mock_boto3.side_effect = client_factory

        resp = ui_client_authed.post("/api/setup/run", json={"region": "us-east-1"})
        events = _parse_sse(resp.text)
        error_events = [e for e in events if e["event"] == "error"]
        assert len(error_events) > 0
        assert "KMS" in error_events[0]["data"]["message"]
