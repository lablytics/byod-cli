"""Tests for the submit command (byod_cli/cli.py).

Tests client-side encryption, presigned URL upload, and job submission.
"""

import os
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from byod_cli.api_client import (
    APIError,
    JobSubmission,
    PresignedUpload,
    TenantConfig,
)
from byod_cli.cli import cli


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def mock_tenant_config():
    return TenantConfig(
        tenant_id="t-001",
        organization_name="Test Lab",
        region="us-east-1",
        data_bucket="byod-data",
        results_bucket="byod-results",
        kms_key_arn=None,
        customer_kms_key_arn="arn:aws:kms:us-east-1:123456789012:key/test-key-id",
        tenant_prefix="tenant-t001",
    )


def _make_presigned_upload(index=0):
    """Create a mock PresignedUpload object."""
    return PresignedUpload(
        url=f"https://s3.amazonaws.com/bucket/upload-{index}",
        fields={"key": f"uploads/file-{index}", "policy": "abc"},
        s3_key=f"uploads/file-{index}.enc",
        expires_at=datetime(2026, 1, 1),
    )


MOCK_PLUGINS = [
    {
        "name": "demo-count",
        "version": "1.0.0",
        "description": "Demo plugin",
        "tags": [],
        "inputs": [
            {"name": "input_file", "type": "file", "formats": ["txt", "csv", "tsv", "log"]},
        ],
    },
    {
        "name": "genomic-qc",
        "version": "1.0.0",
        "description": "Genomic QC",
        "tags": [],
        "inputs": [
            {"name": "fastq_files", "type": "file", "pattern": "*.fastq*"},
        ],
    },
]


def _setup_submit_mocks(mock_config_cls, mock_api_cls, mock_tenant_config):
    """Common mock setup for submit tests. Returns (config, api) mock instances."""
    config = mock_config_cls.return_value
    config.get_api_key.return_value = "sk_live_test"
    config.get_api_url.return_value = "https://api.test"

    api = mock_api_cls.return_value
    api.get_tenant_config.return_value = mock_tenant_config
    api.list_plugins.return_value = MOCK_PLUGINS
    api.get_upload_url.side_effect = [
        _make_presigned_upload(1),
        _make_presigned_upload(2),
    ]
    api.submit_job.return_value = JobSubmission(
        job_id="test-job-001",
        status="submitted",
        created_at=datetime(2026, 1, 1),
        input_s3_key="uploads/file-1.enc",
        wrapped_key_s3_key="uploads/file-2.enc",
    )

    return config, api


class TestSubmitCommand:
    def test_submit_file_success(self, runner, tmp_path, mock_tenant_config):
        """Submit a single file - happy path."""
        test_file = tmp_path / "sample.txt"
        test_file.write_bytes(b"line one\nline two\nline three\n")

        with patch("byod_cli.cli.ConfigManager") as MockConfig, \
             patch("byod_cli.cli.APIClient") as MockAPI, \
             patch("boto3.client") as mock_boto3, \
             patch("requests.post") as mock_post:

            _, api = _setup_submit_mocks(MockConfig, MockAPI, mock_tenant_config)

            # Mock KMS generate_data_key
            mock_kms = MagicMock()
            mock_kms.generate_data_key.return_value = {
                "Plaintext": os.urandom(32),
                "CiphertextBlob": b"wrapped-key-data",
            }
            mock_boto3.return_value = mock_kms

            # Mock successful uploads
            mock_response = MagicMock()
            mock_response.ok = True
            mock_post.return_value = mock_response

            result = runner.invoke(
                cli, ["submit", "demo-count", str(test_file)],
                catch_exceptions=False,
            )

            assert result.exit_code == 0
            assert "test-job-001" in result.output
            assert mock_post.call_count == 2  # data + wrapped key
            api.submit_job.assert_called_once()

    def test_submit_directory_creates_tarball(self, runner, tmp_path, mock_tenant_config):
        """Submit a directory - should create tar.gz before encrypting."""
        data_dir = tmp_path / "samples"
        data_dir.mkdir()
        (data_dir / "file1.fastq").write_bytes(b"@SEQ_001\nATCG\n")
        (data_dir / "file2.fastq").write_bytes(b"@SEQ_002\nGCTA\n")

        with patch("byod_cli.cli.ConfigManager") as MockConfig, \
             patch("byod_cli.cli.APIClient") as MockAPI, \
             patch("boto3.client") as mock_boto3, \
             patch("requests.post") as mock_post:

            _setup_submit_mocks(MockConfig, MockAPI, mock_tenant_config)

            mock_kms = MagicMock()
            mock_kms.generate_data_key.return_value = {
                "Plaintext": os.urandom(32),
                "CiphertextBlob": b"wrapped-key-data",
            }
            mock_boto3.return_value = mock_kms

            mock_response = MagicMock()
            mock_response.ok = True
            mock_post.return_value = mock_response

            result = runner.invoke(
                cli, ["submit", "genomic-qc", str(data_dir)],
                catch_exceptions=False,
            )

            assert result.exit_code == 0
            assert "test-job-001" in result.output

    def test_submit_with_description_and_tags(self, runner, tmp_path, mock_tenant_config):
        """Submit with --description and --tags passes metadata to API."""
        test_file = tmp_path / "data.txt"
        test_file.write_bytes(b"test data")

        with patch("byod_cli.cli.ConfigManager") as MockConfig, \
             patch("byod_cli.cli.APIClient") as MockAPI, \
             patch("boto3.client") as mock_boto3, \
             patch("requests.post") as mock_post:

            _, api = _setup_submit_mocks(MockConfig, MockAPI, mock_tenant_config)

            mock_kms = MagicMock()
            mock_kms.generate_data_key.return_value = {
                "Plaintext": os.urandom(32),
                "CiphertextBlob": b"wrapped-key-data",
            }
            mock_boto3.return_value = mock_kms

            mock_response = MagicMock()
            mock_response.ok = True
            mock_post.return_value = mock_response

            result = runner.invoke(cli, [
                "submit", "demo-count", str(test_file),
                "--description", "My test run",
                "--tags", "experiment=exp001",
                "--tags", "batch=1",
            ], catch_exceptions=False)

            assert result.exit_code == 0
            _, kwargs = api.submit_job.call_args
            assert kwargs["description"] == "My test run"
            assert kwargs["tags"] == {"experiment": "exp001", "batch": "1"}

    def test_submit_not_authenticated(self, runner, tmp_path):
        """Submit fails when not authenticated."""
        test_file = tmp_path / "data.txt"
        test_file.write_bytes(b"test")

        with patch("byod_cli.cli.ConfigManager") as MockConfig:
            config = MockConfig.return_value
            config.get_api_key.return_value = None

            result = runner.invoke(cli, ["submit", "demo-count", str(test_file)])
            assert result.exit_code != 0

    def test_submit_no_kms_key(self, runner, tmp_path):
        """Submit fails when no KMS key is configured."""
        test_file = tmp_path / "data.txt"
        test_file.write_bytes(b"test")

        with patch("byod_cli.cli.ConfigManager") as MockConfig, \
             patch("byod_cli.cli.APIClient") as MockAPI:

            config = MockConfig.return_value
            config.get_api_key.return_value = "sk_live_test"
            config.get_api_url.return_value = "https://api.test"

            api = MockAPI.return_value
            api.list_plugins.return_value = MOCK_PLUGINS
            api.get_tenant_config.return_value = TenantConfig(
                tenant_id="t-001",
                organization_name="Test",
                region="us-east-1",
                data_bucket="b",
                results_bucket="r",
                kms_key_arn=None,
                customer_kms_key_arn=None,
                tenant_prefix="t",
            )

            result = runner.invoke(cli, ["submit", "demo-count", str(test_file)])
            assert result.exit_code != 0

    def test_submit_upload_failure(self, runner, tmp_path, mock_tenant_config):
        """Submit fails when upload returns error."""
        test_file = tmp_path / "data.txt"
        test_file.write_bytes(b"test data")

        with patch("byod_cli.cli.ConfigManager") as MockConfig, \
             patch("byod_cli.cli.APIClient") as MockAPI, \
             patch("boto3.client") as mock_boto3, \
             patch("requests.post") as mock_post:

            _setup_submit_mocks(MockConfig, MockAPI, mock_tenant_config)

            mock_kms = MagicMock()
            mock_kms.generate_data_key.return_value = {
                "Plaintext": os.urandom(32),
                "CiphertextBlob": b"wrapped-key-data",
            }
            mock_boto3.return_value = mock_kms

            # Upload fails
            mock_response = MagicMock()
            mock_response.ok = False
            mock_response.status_code = 500
            mock_post.return_value = mock_response

            result = runner.invoke(cli, ["submit", "demo-count", str(test_file)])
            assert result.exit_code != 0

    def test_submit_invalid_tag_format(self, runner, tmp_path):
        """Submit fails with invalid tag format (no = sign)."""
        test_file = tmp_path / "data.txt"
        test_file.write_bytes(b"test")

        with patch("byod_cli.cli.ConfigManager") as MockConfig, \
             patch("byod_cli.cli.APIClient"):

            config = MockConfig.return_value
            config.get_api_key.return_value = "sk_live_test"
            config.get_api_url.return_value = "https://api.test"

            result = runner.invoke(cli, [
                "submit", "demo-count", str(test_file),
                "--tags", "invalid-no-equals",
            ])
            assert result.exit_code != 0

    def test_submit_api_error(self, runner, tmp_path, mock_tenant_config):
        """Submit handles API error during job submission."""
        test_file = tmp_path / "data.txt"
        test_file.write_bytes(b"test data")

        with patch("byod_cli.cli.ConfigManager") as MockConfig, \
             patch("byod_cli.cli.APIClient") as MockAPI, \
             patch("boto3.client") as mock_boto3, \
             patch("requests.post") as mock_post:

            _, api = _setup_submit_mocks(MockConfig, MockAPI, mock_tenant_config)
            api.submit_job.side_effect = APIError("Server error", 500)

            mock_kms = MagicMock()
            mock_kms.generate_data_key.return_value = {
                "Plaintext": os.urandom(32),
                "CiphertextBlob": b"wrapped-key-data",
            }
            mock_boto3.return_value = mock_kms

            mock_response = MagicMock()
            mock_response.ok = True
            mock_post.return_value = mock_response

            result = runner.invoke(cli, ["submit", "demo-count", str(test_file)])
            assert result.exit_code != 0
