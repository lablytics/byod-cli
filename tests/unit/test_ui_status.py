"""Tests for UI status routes."""

from unittest.mock import MagicMock, patch


class TestGetStatus:
    """Tests for GET /api/status."""

    def test_status_unauthenticated(self, ui_client):
        resp = ui_client.get("/api/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["authenticated"] is False
        assert data["tenant_valid"] is False
        assert data["api_reachable"] is False

    @patch("boto3.client")
    @patch("byod_cli.api_client.APIClient")
    def test_status_authenticated_tenant_valid(self, MockAPIClient, mock_boto3, ui_client_authed):
        mock_client = MagicMock()
        mock_client.verify_auth.return_value = {"tenant_id": "tenant-abc"}
        MockAPIClient.return_value = mock_client

        mock_iam = MagicMock()
        mock_iam.get_role.return_value = {"Role": {}}
        mock_kms = MagicMock()
        mock_kms.describe_key.return_value = {"KeyMetadata": {"KeyState": "Enabled"}}

        def client_factory(service, **kwargs):
            if service == "iam":
                return mock_iam
            if service == "kms":
                return mock_kms
            return MagicMock()

        mock_boto3.side_effect = client_factory

        resp = ui_client_authed.get("/api/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["authenticated"] is True
        assert data["api_reachable"] is True
        assert data["tenant_valid"] is True
        assert data["tenant_id"] == "tenant-abc"
        assert data["kms_key_configured"] is True
        assert data["role_configured"] is True

    @patch("boto3.client")
    @patch("byod_cli.api_client.APIClient")
    def test_status_authenticated_no_tenant(self, MockAPIClient, mock_boto3, ui_client_authed):
        mock_client = MagicMock()
        mock_client.verify_auth.return_value = {}
        MockAPIClient.return_value = mock_client
        mock_boto3.return_value = MagicMock()

        resp = ui_client_authed.get("/api/status")
        data = resp.json()
        assert data["api_reachable"] is True
        assert data["tenant_valid"] is False
        assert data["tenant_error"] is not None
        assert "not associated" in data["tenant_error"]

    @patch("boto3.client")
    @patch("byod_cli.api_client.APIClient")
    def test_status_auth_error(self, MockAPIClient, mock_boto3, ui_client_authed):
        from byod_cli.api_client import AuthenticationError

        mock_client = MagicMock()
        mock_client.verify_auth.side_effect = AuthenticationError("Invalid key")
        MockAPIClient.return_value = mock_client
        mock_boto3.return_value = MagicMock()

        resp = ui_client_authed.get("/api/status")
        data = resp.json()
        assert data["tenant_error"] is not None

    @patch("boto3.client")
    @patch("byod_cli.api_client.APIClient")
    def test_status_connection_error(self, MockAPIClient, mock_boto3, ui_client_authed):
        mock_client = MagicMock()
        mock_client.verify_auth.side_effect = ConnectionError("Connection refused")
        MockAPIClient.return_value = mock_client
        mock_boto3.return_value = MagicMock()

        resp = ui_client_authed.get("/api/status")
        data = resp.json()
        assert data["api_reachable"] is False
        assert data["tenant_error"] is not None

    @patch("boto3.client")
    @patch("byod_cli.api_client.APIClient")
    def test_status_kms_key_disabled(self, MockAPIClient, mock_boto3, ui_client_authed):
        mock_client = MagicMock()
        mock_client.verify_auth.return_value = {"tenant_id": "tenant-abc"}
        MockAPIClient.return_value = mock_client

        mock_iam = MagicMock()
        mock_iam.get_role.return_value = {"Role": {}}
        mock_kms = MagicMock()
        mock_kms.describe_key.return_value = {"KeyMetadata": {"KeyState": "Disabled"}}

        def client_factory(service, **kwargs):
            if service == "iam":
                return mock_iam
            if service == "kms":
                return mock_kms
            return MagicMock()

        mock_boto3.side_effect = client_factory

        resp = ui_client_authed.get("/api/status")
        data = resp.json()
        assert data["kms_key_configured"] is False
        assert data["kms_key_error"] is not None
        assert "disabled" in data["kms_key_error"].lower()

    @patch("boto3.client")
    @patch("byod_cli.api_client.APIClient")
    def test_status_kms_key_pending_deletion(self, MockAPIClient, mock_boto3, ui_client_authed):
        mock_client = MagicMock()
        mock_client.verify_auth.return_value = {"tenant_id": "tenant-abc"}
        MockAPIClient.return_value = mock_client

        mock_iam = MagicMock()
        mock_iam.get_role.return_value = {"Role": {}}
        mock_kms = MagicMock()
        mock_kms.describe_key.return_value = {"KeyMetadata": {"KeyState": "PendingDeletion"}}

        def client_factory(service, **kwargs):
            if service == "iam":
                return mock_iam
            if service == "kms":
                return mock_kms
            return MagicMock()

        mock_boto3.side_effect = client_factory

        resp = ui_client_authed.get("/api/status")
        data = resp.json()
        assert data["kms_key_configured"] is False
        assert "deletion" in data["kms_key_error"].lower()

    @patch("boto3.client")
    @patch("byod_cli.api_client.APIClient")
    def test_status_role_not_found(self, MockAPIClient, mock_boto3, ui_client_authed):
        from botocore.exceptions import ClientError

        mock_client = MagicMock()
        mock_client.verify_auth.return_value = {"tenant_id": "tenant-abc"}
        MockAPIClient.return_value = mock_client

        mock_iam = MagicMock()
        mock_iam.get_role.side_effect = ClientError(
            {"Error": {"Code": "NoSuchEntity", "Message": "Role not found"}},
            "GetRole",
        )
        mock_kms = MagicMock()
        mock_kms.describe_key.return_value = {"KeyMetadata": {"KeyState": "Enabled"}}

        def client_factory(service, **kwargs):
            if service == "iam":
                return mock_iam
            if service == "kms":
                return mock_kms
            return MagicMock()

        mock_boto3.side_effect = client_factory

        resp = ui_client_authed.get("/api/status")
        data = resp.json()
        assert data["role_configured"] is False
        assert data["role_error"] is not None
        assert "no longer exists" in data["role_error"].lower()


class TestGetAWSStatus:
    """Tests for GET /api/status/aws."""

    @patch("boto3.client")
    def test_aws_configured(self, mock_boto3, ui_client):
        mock_sts = MagicMock()
        mock_sts.get_caller_identity.return_value = {
            "Account": "123456789012",
            "Arn": "arn:aws:iam::123456789012:user/test",
        }
        mock_boto3.return_value = mock_sts

        resp = ui_client.get("/api/status/aws")
        assert resp.status_code == 200
        data = resp.json()
        assert data["configured"] is True
        assert data["account"] == "123456789012"

    @patch("boto3.client")
    def test_aws_not_configured(self, mock_boto3, ui_client):
        mock_boto3.side_effect = Exception("Unable to locate credentials")

        resp = ui_client.get("/api/status/aws")
        assert resp.status_code == 200
        data = resp.json()
        assert data["configured"] is False
        assert "error" in data
