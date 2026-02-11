"""Tests for retrieve, decrypt, and get commands (byod_cli/cli.py).

Tests downloading encrypted results, KMS key unwrapping, and AES-256-GCM decryption.
Uses real cryptographic operations to verify decrypt correctness.
"""

import io
import json
import os
import tarfile
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest
from byod_cli.api_client import (
    PresignedDownload,
    TenantConfig,
)
from byod_cli.cli import _encrypt_data, cli
from click.testing import CliRunner


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def result_key():
    """A 32-byte AES key used to encrypt fake results."""
    return os.urandom(32)


@pytest.fixture
def mock_tenant_config():
    return TenantConfig(
        tenant_id="t-001",
        organization_name="Test Lab",
        region="us-east-1",
        data_bucket="byod-data",
        results_bucket="byod-results",
        kms_key_arn=None,
        customer_kms_key_arn="arn:aws:kms:us-east-1:123456789012:key/test-key",
        tenant_prefix="tenant-t001",
    )


def _make_tar_gz(files: dict) -> bytes:
    """Create a tar.gz archive from a dict of {filename: content}."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for name, content in files.items():
            info = tarfile.TarInfo(name=name)
            info.size = len(content)
            tar.addfile(info, io.BytesIO(content))
    return buf.getvalue()


def _make_download_presigned(filename):
    """Create a PresignedDownload mock."""
    return PresignedDownload(
        url=f"https://s3.amazonaws.com/bucket/{filename}",
        s3_key=f"results/{filename}",
        expires_at=datetime(2026, 1, 1),
    )


# ---------------------------------------------------------------------------
# Retrieve command
# ---------------------------------------------------------------------------


class TestRetrieveCommand:
    def test_retrieve_success(self, runner, tmp_path, mock_tenant_config):
        """Retrieve downloads encrypted results and creates manifest."""
        output_dir = tmp_path / "results"

        with patch("byod_cli.cli.ConfigManager") as MockConfig, \
             patch("byod_cli.cli.APIClient") as MockAPI, \
             patch("requests.get") as mock_get:

            config = MockConfig.return_value
            config.get_api_key.return_value = "sk_live_test"
            config.get_api_url.return_value = "https://api.test"

            api = MockAPI.return_value
            api.get_download_url.side_effect = [
                _make_download_presigned("output.enc"),
                _make_download_presigned("output_key.bin"),
            ]
            api.get_tenant_config.return_value = mock_tenant_config

            # Mock streamed download for encrypted results
            enc_response = MagicMock()
            enc_response.ok = True
            enc_response.iter_content.return_value = [b"encrypted-data-chunk"]

            # Mock download for wrapped key
            key_response = MagicMock()
            key_response.ok = True
            key_response.content = b"wrapped-key-bytes"

            mock_get.side_effect = [enc_response, key_response]

            result = runner.invoke(
                cli, ["retrieve", "job-001", "-o", str(output_dir)],
                catch_exceptions=False,
            )

            assert result.exit_code == 0
            assert "Results downloaded" in result.output
            assert (output_dir / "output.enc").exists()
            assert (output_dir / "output_key.bin").exists()
            assert (output_dir / "results-manifest.json").exists()

            # Verify manifest content
            manifest = json.loads((output_dir / "results-manifest.json").read_text())
            assert manifest["job_id"] == "job-001"
            assert manifest["kms_key_id"] == mock_tenant_config.customer_kms_key_arn

    def test_retrieve_nonempty_dir_fails(self, runner, tmp_path):
        """Retrieve fails if output dir is not empty (without --overwrite)."""
        output_dir = tmp_path / "results"
        output_dir.mkdir()
        (output_dir / "existing.txt").write_text("data")

        with patch("byod_cli.cli.ConfigManager") as MockConfig:
            config = MockConfig.return_value
            config.get_api_key.return_value = "sk_live_test"
            config.get_api_url.return_value = "https://api.test"

            result = runner.invoke(cli, ["retrieve", "job-001", "-o", str(output_dir)])
            assert result.exit_code != 0
            assert "not empty" in " ".join(result.output.split())

    def test_retrieve_with_overwrite(self, runner, tmp_path, mock_tenant_config):
        """Retrieve with --overwrite works even if dir is not empty."""
        output_dir = tmp_path / "results"
        output_dir.mkdir()
        (output_dir / "existing.txt").write_text("data")

        with patch("byod_cli.cli.ConfigManager") as MockConfig, \
             patch("byod_cli.cli.APIClient") as MockAPI, \
             patch("requests.get") as mock_get:

            config = MockConfig.return_value
            config.get_api_key.return_value = "sk_live_test"
            config.get_api_url.return_value = "https://api.test"

            api = MockAPI.return_value
            api.get_download_url.side_effect = [
                _make_download_presigned("output.enc"),
                _make_download_presigned("output_key.bin"),
            ]
            api.get_tenant_config.return_value = mock_tenant_config

            enc_response = MagicMock()
            enc_response.ok = True
            enc_response.iter_content.return_value = [b"data"]

            key_response = MagicMock()
            key_response.ok = True
            key_response.content = b"key"

            mock_get.side_effect = [enc_response, key_response]

            result = runner.invoke(
                cli, ["retrieve", "job-001", "-o", str(output_dir), "--overwrite"],
                catch_exceptions=False,
            )
            assert result.exit_code == 0

    def test_retrieve_download_failure(self, runner, tmp_path):
        """Retrieve fails when download returns error."""
        output_dir = tmp_path / "results"

        with patch("byod_cli.cli.ConfigManager") as MockConfig, \
             patch("byod_cli.cli.APIClient") as MockAPI, \
             patch("requests.get") as mock_get:

            config = MockConfig.return_value
            config.get_api_key.return_value = "sk_live_test"
            config.get_api_url.return_value = "https://api.test"

            api = MockAPI.return_value
            api.get_download_url.side_effect = [
                _make_download_presigned("output.enc"),
                _make_download_presigned("output_key.bin"),
            ]

            # Download fails
            enc_response = MagicMock()
            enc_response.ok = False
            enc_response.status_code = 404
            mock_get.return_value = enc_response

            result = runner.invoke(cli, ["retrieve", "job-001", "-o", str(output_dir)])
            assert result.exit_code != 0


# ---------------------------------------------------------------------------
# Decrypt command
# ---------------------------------------------------------------------------


class TestDecryptCommand:
    def _create_encrypted_results(self, results_dir, plaintext, result_key):
        """Helper: write encrypted data and manifest to results_dir."""
        results_dir.mkdir(parents=True, exist_ok=True)

        encrypted = _encrypt_data(plaintext, result_key)
        (results_dir / "output.enc").write_bytes(encrypted)
        (results_dir / "output_key.bin").write_bytes(b"fake-wrapped-key")

        manifest = {
            "job_id": "job-001",
            "encrypted_file": "output.enc",
            "wrapped_key_file": "output_key.bin",
            "kms_key_id": "arn:aws:kms:us-east-1:123:key/test",
            "region": "us-east-1",
        }
        (results_dir / "results-manifest.json").write_text(json.dumps(manifest))

    def _mock_kms(self, mock_boto3, result_key):
        """Helper: set up KMS mock that returns result_key."""
        mock_kms = MagicMock()
        mock_kms.decrypt.return_value = {"Plaintext": result_key}
        mock_kms.describe_key.return_value = {
            "KeyMetadata": {"KeyState": "Enabled", "KeyUsage": "ENCRYPT_DECRYPT"}
        }
        mock_boto3.return_value = mock_kms
        return mock_kms

    def test_decrypt_raw_file(self, runner, tmp_path, result_key):
        """Decrypt raw (non-archive) encrypted results."""
        results_dir = tmp_path / "results"
        output_dir = tmp_path / "decrypted"
        plaintext = b"Hello, this is the decrypted result data."

        self._create_encrypted_results(results_dir, plaintext, result_key)

        with patch("byod_cli.cli.ConfigManager"), \
             patch("boto3.client") as mock_boto3:

            self._mock_kms(mock_boto3, result_key)

            result = runner.invoke(
                cli, ["decrypt", str(results_dir), "-o", str(output_dir)],
                catch_exceptions=False,
            )

            assert result.exit_code == 0
            assert "Results decrypted" in result.output
            assert (output_dir / "output.bin").exists()
            assert (output_dir / "output.bin").read_bytes() == plaintext

    def test_decrypt_tar_archive(self, runner, tmp_path, result_key):
        """Decrypt tar.gz archive results and extract files."""
        results_dir = tmp_path / "results"
        output_dir = tmp_path / "decrypted"

        archive = _make_tar_gz({
            "report.html": b"<html>QC Report</html>",
            "summary.txt": b"All samples passed QC.",
        })
        self._create_encrypted_results(results_dir, archive, result_key)

        with patch("byod_cli.cli.ConfigManager"), \
             patch("boto3.client") as mock_boto3:

            self._mock_kms(mock_boto3, result_key)

            result = runner.invoke(
                cli, ["decrypt", str(results_dir), "-o", str(output_dir)],
                catch_exceptions=False,
            )

            assert result.exit_code == 0
            assert "Results decrypted" in result.output
            assert (output_dir / "report.html").exists()
            assert (output_dir / "summary.txt").exists()
            assert (output_dir / "report.html").read_bytes() == b"<html>QC Report</html>"

    def test_decrypt_missing_manifest(self, runner, tmp_path):
        """Decrypt fails if no manifest exists."""
        results_dir = tmp_path / "results"
        results_dir.mkdir()
        output_dir = tmp_path / "decrypted"

        with patch("byod_cli.cli.ConfigManager"):
            result = runner.invoke(cli, ["decrypt", str(results_dir), "-o", str(output_dir)])
            assert result.exit_code != 0

    def test_decrypt_skips_manifest_in_archive(self, runner, tmp_path, result_key):
        """Decrypt skips __manifest__.json when extracting archives."""
        results_dir = tmp_path / "results"
        output_dir = tmp_path / "decrypted"

        archive = _make_tar_gz({
            "__manifest__.json": b'{"internal": true}',
            "output.txt": b"real output",
        })
        self._create_encrypted_results(results_dir, archive, result_key)

        with patch("byod_cli.cli.ConfigManager"), \
             patch("boto3.client") as mock_boto3:

            self._mock_kms(mock_boto3, result_key)

            result = runner.invoke(
                cli, ["decrypt", str(results_dir), "-o", str(output_dir)],
                catch_exceptions=False,
            )

            assert result.exit_code == 0
            assert not (output_dir / "__manifest__.json").exists()
            assert (output_dir / "output.txt").exists()


# ---------------------------------------------------------------------------
# Get command (combined retrieve + decrypt)
# ---------------------------------------------------------------------------


class TestGetCommand:
    def _setup_get_mocks(
        self, mock_config_cls, mock_api_cls, mock_get,
        mock_boto3, mock_tenant_config, encrypted_data, wrapped_key, result_key,
    ):
        """Common mock setup for get command tests."""
        config = mock_config_cls.return_value
        config.get_api_key.return_value = "sk_live_test"
        config.get_api_url.return_value = "https://api.test"

        api = mock_api_cls.return_value
        api.get_download_url.side_effect = [
            _make_download_presigned("output.enc"),
            _make_download_presigned("output_key.bin"),
        ]
        api.get_tenant_config.return_value = mock_tenant_config

        # Mock download responses
        enc_response = MagicMock()
        enc_response.ok = True
        enc_response.iter_content.return_value = [encrypted_data]

        key_response = MagicMock()
        key_response.ok = True
        key_response.content = wrapped_key

        mock_get.side_effect = [enc_response, key_response]

        # Mock KMS decrypt
        mock_kms = MagicMock()
        mock_kms.decrypt.return_value = {"Plaintext": result_key}
        mock_boto3.return_value = mock_kms

        return config, api

    def test_get_success_raw(self, runner, tmp_path, result_key, mock_tenant_config):
        """Get retrieves, decrypts, and writes raw output."""
        output_dir = tmp_path / "output"
        plaintext = b"Result data from enclave processing."
        encrypted = _encrypt_data(plaintext, result_key)

        with patch("byod_cli.cli.ConfigManager") as MockConfig, \
             patch("byod_cli.cli.APIClient") as MockAPI, \
             patch("boto3.client") as mock_boto3, \
             patch("requests.get") as mock_get:

            self._setup_get_mocks(
                MockConfig, MockAPI, mock_get, mock_boto3,
                mock_tenant_config, encrypted, b"wrapped", result_key,
            )

            result = runner.invoke(
                cli, ["get", "job-001", "-o", str(output_dir)],
                catch_exceptions=False,
            )

            assert result.exit_code == 0
            assert "retrieved and decrypted" in result.output
            assert (output_dir / "output.bin").exists()
            assert (output_dir / "output.bin").read_bytes() == plaintext

    def test_get_success_archive(self, runner, tmp_path, result_key, mock_tenant_config):
        """Get retrieves, decrypts, and extracts tar.gz archive."""
        output_dir = tmp_path / "output"

        archive = _make_tar_gz({
            "results.csv": b"sample,score\nA,99\nB,95\n",
            "log.txt": b"Processing completed.",
        })
        encrypted = _encrypt_data(archive, result_key)

        with patch("byod_cli.cli.ConfigManager") as MockConfig, \
             patch("byod_cli.cli.APIClient") as MockAPI, \
             patch("boto3.client") as mock_boto3, \
             patch("requests.get") as mock_get:

            self._setup_get_mocks(
                MockConfig, MockAPI, mock_get, mock_boto3,
                mock_tenant_config, encrypted, b"wrapped", result_key,
            )

            result = runner.invoke(
                cli, ["get", "job-001", "-o", str(output_dir)],
                catch_exceptions=False,
            )

            assert result.exit_code == 0
            assert (output_dir / "results.csv").exists()
            assert (output_dir / "log.txt").exists()

    def test_get_cleans_up_encrypted_files(self, runner, tmp_path, result_key, mock_tenant_config):
        """Get cleans up encrypted files by default."""
        output_dir = tmp_path / "output"
        encrypted = _encrypt_data(b"data", result_key)

        with patch("byod_cli.cli.ConfigManager") as MockConfig, \
             patch("byod_cli.cli.APIClient") as MockAPI, \
             patch("boto3.client") as mock_boto3, \
             patch("requests.get") as mock_get:

            self._setup_get_mocks(
                MockConfig, MockAPI, mock_get, mock_boto3,
                mock_tenant_config, encrypted, b"wrapped", result_key,
            )

            result = runner.invoke(
                cli, ["get", "job-001", "-o", str(output_dir)],
                catch_exceptions=False,
            )

            assert result.exit_code == 0
            assert not (output_dir / "output.enc").exists()
            assert not (output_dir / "output_key.bin").exists()

    def test_get_keep_encrypted(self, runner, tmp_path, result_key, mock_tenant_config):
        """Get with --keep-encrypted preserves encrypted files."""
        output_dir = tmp_path / "output"
        encrypted = _encrypt_data(b"data", result_key)

        with patch("byod_cli.cli.ConfigManager") as MockConfig, \
             patch("byod_cli.cli.APIClient") as MockAPI, \
             patch("boto3.client") as mock_boto3, \
             patch("requests.get") as mock_get:

            self._setup_get_mocks(
                MockConfig, MockAPI, mock_get, mock_boto3,
                mock_tenant_config, encrypted, b"wrapped", result_key,
            )

            result = runner.invoke(
                cli, ["get", "job-001", "-o", str(output_dir), "--keep-encrypted"],
                catch_exceptions=False,
            )

            assert result.exit_code == 0
            assert (output_dir / "output.enc").exists()
            assert (output_dir / "output_key.bin").exists()

    def test_get_nonempty_dir_fails(self, runner, tmp_path):
        """Get fails if output dir is not empty (without --overwrite)."""
        output_dir = tmp_path / "output"
        output_dir.mkdir()
        (output_dir / "existing.txt").write_text("data")

        with patch("byod_cli.cli.ConfigManager") as MockConfig:
            config = MockConfig.return_value
            config.get_api_key.return_value = "sk_live_test"
            config.get_api_url.return_value = "https://api.test"

            result = runner.invoke(cli, ["get", "job-001", "-o", str(output_dir)])
            assert result.exit_code != 0
            assert "not empty" in " ".join(result.output.split())
