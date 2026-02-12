"""Tests for setup and update-policy commands (byod_cli/cli.py).

Tests AWS resource creation (IAM roles, KMS keys) and policy updates.
"""

import json
from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import ClientError
from click.testing import CliRunner

from byod_cli.api_client import APIError
from byod_cli.cli import cli


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def enclave_info():
    return {
        "pcr0_values": ["abc123def456" * 4],
        "pcr0": "abc123def456" * 4,
        "account_id": "506587498939",
        "tenant_id": "t-001",
    }


def _make_boto3_side_effect(sts_mock, iam_mock, kms_mock):
    """Create a side_effect function for boto3.client returning per-service mocks."""
    def side_effect(service, **kwargs):
        return {"sts": sts_mock, "iam": iam_mock, "kms": kms_mock}[service]
    return side_effect


# ---------------------------------------------------------------------------
# Setup command
# ---------------------------------------------------------------------------


class TestSetupCommand:
    def _make_aws_mocks(self):
        """Create default STS, IAM, and KMS mocks for setup success path."""
        sts_mock = MagicMock()
        sts_mock.get_caller_identity.return_value = {"Account": "123456789012"}

        iam_mock = MagicMock()
        iam_mock.create_role.return_value = {
            "Role": {"Arn": "arn:aws:iam::123456789012:role/BYODEnclaveRole-t-001"}
        }

        kms_mock = MagicMock()
        kms_mock.create_key.return_value = {
            "KeyMetadata": {
                "Arn": "arn:aws:kms:us-east-1:123456789012:key/test-key-id",
                "KeyId": "test-key-id",
            }
        }

        return sts_mock, iam_mock, kms_mock

    def test_setup_success(self, runner, enclave_info):
        """Setup creates IAM role, KMS key, and registers with Lablytics."""
        with patch("byod_cli.cli.ConfigManager") as MockConfig, \
             patch("byod_cli.cli.APIClient") as MockAPI, \
             patch("boto3.client") as mock_boto3, \
             patch("time.sleep"):

            config = MockConfig.return_value
            config.get_api_key.return_value = "sk_live_test"
            config.get_api_url.return_value = "https://api.test"
            config.get_active_profile_name.return_value = "t-001"

            api = MockAPI.return_value
            api.get_enclave_info.return_value = enclave_info

            sts_mock, iam_mock, kms_mock = self._make_aws_mocks()
            mock_boto3.side_effect = _make_boto3_side_effect(sts_mock, iam_mock, kms_mock)

            result = runner.invoke(cli, ["setup"], catch_exceptions=False)

            assert result.exit_code == 0
            assert "Setup complete" in result.output
            iam_mock.create_role.assert_called_once()
            kms_mock.create_key.assert_called_once()
            iam_mock.put_role_policy.assert_called_once()
            api.register_kms_setup.assert_called_once()

    def test_setup_kms_policy_has_attestation(self, runner, enclave_info):
        """Setup creates KMS key with PCR0 attestation condition."""
        with patch("byod_cli.cli.ConfigManager") as MockConfig, \
             patch("byod_cli.cli.APIClient") as MockAPI, \
             patch("boto3.client") as mock_boto3, \
             patch("time.sleep"):

            config = MockConfig.return_value
            config.get_api_key.return_value = "sk_live_test"
            config.get_api_url.return_value = "https://api.test"
            config.get_active_profile_name.return_value = "t-001"

            api = MockAPI.return_value
            api.get_enclave_info.return_value = enclave_info

            sts_mock, iam_mock, kms_mock = self._make_aws_mocks()
            mock_boto3.side_effect = _make_boto3_side_effect(sts_mock, iam_mock, kms_mock)

            runner.invoke(cli, ["setup"], catch_exceptions=False)

            # Verify KMS key policy includes PCR0 attestation
            create_key_call = kms_mock.create_key.call_args
            policy = json.loads(create_key_call.kwargs.get("Policy", create_key_call[1]["Policy"]))

            pcr0_statement = None
            for stmt in policy["Statement"]:
                if stmt.get("Sid") == "RoleDecryptWithAttestation":
                    pcr0_statement = stmt
                    break

            assert pcr0_statement is not None
            condition = pcr0_statement["Condition"]["StringEqualsIgnoreCase"]
            assert condition["kms:RecipientAttestation:PCR0"] == enclave_info["pcr0_values"]

    def test_setup_role_already_exists(self, runner, enclave_info):
        """Setup handles existing IAM role gracefully and continues."""
        with patch("byod_cli.cli.ConfigManager") as MockConfig, \
             patch("byod_cli.cli.APIClient") as MockAPI, \
             patch("boto3.client") as mock_boto3, \
             patch("time.sleep"):

            config = MockConfig.return_value
            config.get_api_key.return_value = "sk_live_test"
            config.get_api_url.return_value = "https://api.test"
            config.get_active_profile_name.return_value = "t-001"

            api = MockAPI.return_value
            api.get_enclave_info.return_value = enclave_info

            sts_mock, iam_mock, kms_mock = self._make_aws_mocks()
            iam_mock.create_role.side_effect = ClientError(
                {"Error": {"Code": "EntityAlreadyExists", "Message": "Role exists"}},
                "CreateRole",
            )
            mock_boto3.side_effect = _make_boto3_side_effect(sts_mock, iam_mock, kms_mock)

            result = runner.invoke(cli, ["setup"], catch_exceptions=False)

            assert result.exit_code == 0
            assert "already exists" in result.output
            # KMS key should still be created
            kms_mock.create_key.assert_called_once()

    def test_setup_aws_credentials_error(self, runner, enclave_info):
        """Setup fails when AWS credentials are not configured."""
        with patch("byod_cli.cli.ConfigManager") as MockConfig, \
             patch("byod_cli.cli.APIClient") as MockAPI, \
             patch("boto3.client") as mock_boto3:

            config = MockConfig.return_value
            config.get_api_key.return_value = "sk_live_test"
            config.get_api_url.return_value = "https://api.test"

            api = MockAPI.return_value
            api.get_enclave_info.return_value = enclave_info

            sts_mock = MagicMock()
            sts_mock.get_caller_identity.side_effect = ClientError(
                {"Error": {"Code": "InvalidClientTokenId", "Message": "Bad creds"}},
                "GetCallerIdentity",
            )
            mock_boto3.return_value = sts_mock

            result = runner.invoke(cli, ["setup"])
            assert result.exit_code != 0

    def test_setup_registration_failure(self, runner, enclave_info):
        """Setup reports error when Lablytics registration fails."""
        with patch("byod_cli.cli.ConfigManager") as MockConfig, \
             patch("byod_cli.cli.APIClient") as MockAPI, \
             patch("boto3.client") as mock_boto3, \
             patch("time.sleep"):

            config = MockConfig.return_value
            config.get_api_key.return_value = "sk_live_test"
            config.get_api_url.return_value = "https://api.test"
            config.get_active_profile_name.return_value = "t-001"

            api = MockAPI.return_value
            api.get_enclave_info.return_value = enclave_info
            api.register_kms_setup.side_effect = APIError("Server error", 500)

            sts_mock, iam_mock, kms_mock = self._make_aws_mocks()
            mock_boto3.side_effect = _make_boto3_side_effect(sts_mock, iam_mock, kms_mock)

            result = runner.invoke(cli, ["setup"])
            assert result.exit_code != 0
            assert "not registered" in result.output

    def test_setup_enclave_info_error(self, runner):
        """Setup fails when enclave info API call fails."""
        with patch("byod_cli.cli.ConfigManager") as MockConfig, \
             patch("byod_cli.cli.APIClient") as MockAPI:

            config = MockConfig.return_value
            config.get_api_key.return_value = "sk_live_test"
            config.get_api_url.return_value = "https://api.test"

            api = MockAPI.return_value
            api.get_enclave_info.side_effect = APIError("Not found", 404)

            result = runner.invoke(cli, ["setup"])
            assert result.exit_code != 0


# ---------------------------------------------------------------------------
# Update-policy command
# ---------------------------------------------------------------------------


class TestUpdatePolicyCommand:
    def _make_policy_with_pcr0(self, pcr0_values):
        """Create a KMS key policy with given PCR0 values."""
        return {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Sid": "CustomerAdmin",
                    "Effect": "Allow",
                    "Action": ["kms:Create*"],
                    "Resource": "*",
                },
                {
                    "Sid": "RoleDecryptWithAttestation",
                    "Effect": "Allow",
                    "Action": "kms:Decrypt",
                    "Resource": "*",
                    "Condition": {
                        "StringEqualsIgnoreCase": {
                            "kms:RecipientAttestation:PCR0": pcr0_values
                        }
                    },
                },
            ],
        }

    def _setup_config_mocks(self, mock_config_cls, mock_api_cls, enclave_info):
        """Common config/API mock setup for update-policy tests."""
        config = mock_config_cls.return_value
        config.get_api_key.return_value = "sk_live_test"
        config.get_api_url.return_value = "https://api.test"
        config.get_active_profile_name.return_value = "t-001"
        config.get_profile.return_value = {
            "settings": {
                "kms_key_arn": "arn:aws:kms:us-east-1:123:key/test",
                "role_arn": "arn:aws:iam::123:role/BYODEnclaveRole-t-001",
            }
        }

        api = mock_api_cls.return_value
        api.get_enclave_info.return_value = enclave_info

        return config, api

    def test_update_policy_success(self, runner, enclave_info):
        """Update-policy fetches new PCR0 values and updates KMS key policy."""
        old_pcr0 = ["old_pcr0_value" * 3]
        new_pcr0 = enclave_info["pcr0_values"]

        with patch("byod_cli.cli.ConfigManager") as MockConfig, \
             patch("byod_cli.cli.APIClient") as MockAPI, \
             patch("boto3.client") as mock_boto3:

            self._setup_config_mocks(MockConfig, MockAPI, enclave_info)

            kms_mock = MagicMock()
            kms_mock.get_key_policy.return_value = {
                "Policy": json.dumps(self._make_policy_with_pcr0(old_pcr0))
            }
            mock_boto3.return_value = kms_mock

            result = runner.invoke(cli, ["update-policy"], catch_exceptions=False)

            assert result.exit_code == 0
            assert "updated successfully" in result.output
            kms_mock.put_key_policy.assert_called_once()

            # Verify the new policy contains the updated PCR0 values
            put_call = kms_mock.put_key_policy.call_args
            new_policy = json.loads(put_call.kwargs.get("Policy", put_call[1]["Policy"]))
            for stmt in new_policy["Statement"]:
                if stmt["Sid"] == "RoleDecryptWithAttestation":
                    assert stmt["Condition"]["StringEqualsIgnoreCase"][
                        "kms:RecipientAttestation:PCR0"
                    ] == new_pcr0

    def test_update_policy_already_current(self, runner, enclave_info):
        """Update-policy detects when policy is already up to date."""
        pcr0 = enclave_info["pcr0_values"]

        with patch("byod_cli.cli.ConfigManager") as MockConfig, \
             patch("byod_cli.cli.APIClient") as MockAPI, \
             patch("boto3.client") as mock_boto3:

            self._setup_config_mocks(MockConfig, MockAPI, enclave_info)

            kms_mock = MagicMock()
            kms_mock.get_key_policy.return_value = {
                "Policy": json.dumps(self._make_policy_with_pcr0(pcr0))
            }
            mock_boto3.return_value = kms_mock

            result = runner.invoke(cli, ["update-policy"], catch_exceptions=False)

            assert result.exit_code == 0
            assert "already up to date" in result.output
            kms_mock.put_key_policy.assert_not_called()

    def test_update_policy_no_active_profile(self, runner):
        """Update-policy fails when no active profile exists."""
        with patch("byod_cli.cli.ConfigManager") as MockConfig, \
             patch("byod_cli.cli.APIClient"):

            config = MockConfig.return_value
            config.get_api_key.return_value = "sk_live_test"
            config.get_api_url.return_value = "https://api.test"
            config.get_active_profile_name.return_value = None

            result = runner.invoke(cli, ["update-policy"])
            assert result.exit_code != 0

    def test_update_policy_no_kms_key_in_config(self, runner):
        """Update-policy fails when no KMS key ARN in config."""
        with patch("byod_cli.cli.ConfigManager") as MockConfig, \
             patch("byod_cli.cli.APIClient"):

            config = MockConfig.return_value
            config.get_api_key.return_value = "sk_live_test"
            config.get_api_url.return_value = "https://api.test"
            config.get_active_profile_name.return_value = "t-001"
            config.get_profile.return_value = {"settings": {}}

            result = runner.invoke(cli, ["update-policy"])
            assert result.exit_code != 0

    def test_update_policy_kms_read_error(self, runner, enclave_info):
        """Update-policy fails when KMS get_key_policy fails."""
        with patch("byod_cli.cli.ConfigManager") as MockConfig, \
             patch("byod_cli.cli.APIClient") as MockAPI, \
             patch("boto3.client") as mock_boto3:

            self._setup_config_mocks(MockConfig, MockAPI, enclave_info)

            kms_mock = MagicMock()
            kms_mock.get_key_policy.side_effect = ClientError(
                {"Error": {"Code": "NotFoundException", "Message": "Key not found"}},
                "GetKeyPolicy",
            )
            mock_boto3.return_value = kms_mock

            result = runner.invoke(cli, ["update-policy"])
            assert result.exit_code != 0
