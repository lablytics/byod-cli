"""Tests for CLI commands (byod_cli/cli.py).

Uses Click's CliRunner to test commands without real network/AWS calls.
Covers auth login/logout/status, list, status, plugins, config show.
"""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from byod_cli.cli import cli


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def config_dir(tmp_path):
    """Provide a temp config directory for CLI tests."""
    return tmp_path / ".byod"


# ---------------------------------------------------------------------------
# CLI root
# ---------------------------------------------------------------------------

class TestCLIRoot:
    def test_help(self, runner):
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        assert "BYOD" in result.output

    def test_version(self, runner):
        result = runner.invoke(cli, ["--version"])
        assert result.exit_code == 0


# ---------------------------------------------------------------------------
# Auth commands
# ---------------------------------------------------------------------------

class TestAuthLogin:
    def test_success(self, runner, tmp_path):
        mock_verify = {"tenant_id": "t-001", "email": "test@example.com"}
        mock_tenant = MagicMock(
            tenant_id="t-001",
            organization_name="Test Lab",
            region="us-east-1",
            customer_kms_key_arn=None,
        )

        with patch("byod_cli.cli.APIClient") as MockClient, \
             patch("byod_cli.cli.ConfigManager") as MockConfig:
            instance = MockClient.return_value
            instance.verify_auth.return_value = mock_verify
            instance.get_tenant_config.return_value = mock_tenant

            config_instance = MockConfig.return_value
            config_instance.get_api_url.return_value = "https://api.lablytics.test"
            config_instance.get_api_key.return_value = "sk_live_test"
            config_instance.profile_exists.return_value = False

            result = runner.invoke(
                cli, ["auth", "login", "--api-key", "sk_live_test"],
                catch_exceptions=False,
            )
            assert result.exit_code == 0
            assert "Authentication successful" in result.output

    def test_bad_key(self, runner, tmp_path):
        from byod_cli.api_client import AuthenticationError

        with patch("byod_cli.cli.APIClient") as MockClient, \
             patch("byod_cli.cli.ConfigManager") as MockConfig:
            instance = MockClient.return_value
            instance.verify_auth.side_effect = AuthenticationError("Invalid key", 401)

            config_instance = MockConfig.return_value
            config_instance.get_api_url.return_value = "https://api.lablytics.test"

            result = runner.invoke(
                cli, ["auth", "login", "--api-key", "bad_key"],
            )
            assert result.exit_code != 0


class TestAuthLogout:
    def test_success(self, runner):
        with patch("byod_cli.cli.ConfigManager") as MockConfig:
            config_instance = MockConfig.return_value
            result = runner.invoke(cli, ["auth", "logout"], catch_exceptions=False)
            assert result.exit_code == 0
            assert "Logged out" in result.output
            config_instance.clear_api_credentials.assert_called_once()


class TestAuthStatus:
    def test_not_authenticated(self, runner):
        with patch("byod_cli.cli.ConfigManager") as MockConfig:
            config_instance = MockConfig.return_value
            config_instance.is_authenticated.return_value = False

            result = runner.invoke(cli, ["auth", "status"], catch_exceptions=False)
            assert result.exit_code == 0
            assert "Not authenticated" in result.output

    def test_authenticated(self, runner):
        mock_tenant = MagicMock(
            tenant_id="t-001",
            organization_name="Test Lab",
            region="us-east-1",
        )

        with patch("byod_cli.cli.ConfigManager") as MockConfig, \
             patch("byod_cli.cli.APIClient") as MockClient:
            config_instance = MockConfig.return_value
            config_instance.is_authenticated.return_value = True
            config_instance.get_api_key.return_value = "sk_live_test"
            config_instance.get_api_url.return_value = "https://api.lablytics.test"

            client_instance = MockClient.return_value
            client_instance.verify_auth.return_value = {"tenant_id": "t-001"}
            client_instance.get_tenant_config.return_value = mock_tenant

            result = runner.invoke(cli, ["auth", "status"], catch_exceptions=False)
            assert result.exit_code == 0
            assert "Authenticated" in result.output


# ---------------------------------------------------------------------------
# List command
# ---------------------------------------------------------------------------

class TestListCommand:
    def test_no_jobs(self, runner):
        with patch("byod_cli.cli.ConfigManager") as MockConfig, \
             patch("byod_cli.cli.APIClient") as MockClient:
            config_instance = MockConfig.return_value
            config_instance.get_api_key.return_value = "sk_live_test"
            config_instance.get_api_url.return_value = "https://api.test"

            client_instance = MockClient.return_value
            client_instance.list_jobs.return_value = []

            result = runner.invoke(cli, ["list"], catch_exceptions=False)
            assert result.exit_code == 0
            assert "No jobs found" in result.output

    def test_with_jobs(self, runner):
        jobs = [
            {"job_id": "j1", "plugin_name": "demo-count", "status": "completed",
             "created_at": "2026-01-01T00:00:00Z", "description": "test"},
        ]

        with patch("byod_cli.cli.ConfigManager") as MockConfig, \
             patch("byod_cli.cli.APIClient") as MockClient:
            config_instance = MockConfig.return_value
            config_instance.get_api_key.return_value = "sk_live_test"
            config_instance.get_api_url.return_value = "https://api.test"

            client_instance = MockClient.return_value
            client_instance.list_jobs.return_value = jobs

            result = runner.invoke(cli, ["list"], catch_exceptions=False)
            assert result.exit_code == 0
            assert "j1" in result.output

    def test_json_format(self, runner):
        jobs = [{"job_id": "j1", "status": "pending"}]

        with patch("byod_cli.cli.ConfigManager") as MockConfig, \
             patch("byod_cli.cli.APIClient") as MockClient:
            config_instance = MockConfig.return_value
            config_instance.get_api_key.return_value = "sk_live_test"
            config_instance.get_api_url.return_value = "https://api.test"

            client_instance = MockClient.return_value
            client_instance.list_jobs.return_value = jobs

            result = runner.invoke(cli, ["list", "--format", "json"], catch_exceptions=False)
            assert result.exit_code == 0
            parsed = json.loads(result.output)
            assert parsed[0]["job_id"] == "j1"


# ---------------------------------------------------------------------------
# Status command
# ---------------------------------------------------------------------------

class TestStatusCommand:
    def test_text_output(self, runner):
        status_info = {
            "job_id": "j1", "status": "completed",
            "plugin_name": "demo-count", "created_at": "2026-01-01",
        }

        with patch("byod_cli.cli.ConfigManager") as MockConfig, \
             patch("byod_cli.cli.APIClient") as MockClient:
            config_instance = MockConfig.return_value
            config_instance.get_api_key.return_value = "sk_live_test"
            config_instance.get_api_url.return_value = "https://api.test"

            client_instance = MockClient.return_value
            client_instance.get_job_status.return_value = status_info

            result = runner.invoke(cli, ["status", "j1"], catch_exceptions=False)
            assert result.exit_code == 0
            assert "j1" in result.output

    def test_json_output(self, runner):
        status_info = {"job_id": "j1", "status": "pending"}

        with patch("byod_cli.cli.ConfigManager") as MockConfig, \
             patch("byod_cli.cli.APIClient") as MockClient:
            config_instance = MockConfig.return_value
            config_instance.get_api_key.return_value = "sk_live_test"
            config_instance.get_api_url.return_value = "https://api.test"

            client_instance = MockClient.return_value
            client_instance.get_job_status.return_value = status_info

            result = runner.invoke(cli, ["status", "j1", "--format", "json"], catch_exceptions=False)
            assert result.exit_code == 0
            parsed = json.loads(result.output)
            assert parsed["status"] == "pending"


# ---------------------------------------------------------------------------
# Plugins command
# ---------------------------------------------------------------------------

class TestPluginsCommand:
    def test_empty(self, runner):
        with patch("byod_cli.cli.ConfigManager") as MockConfig, \
             patch("byod_cli.cli.APIClient") as MockClient:
            config_instance = MockConfig.return_value
            config_instance.get_api_key.return_value = "sk_live_test"
            config_instance.get_api_url.return_value = "https://api.test"

            client_instance = MockClient.return_value
            client_instance.list_plugins.return_value = []

            result = runner.invoke(cli, ["plugins"], catch_exceptions=False)
            assert result.exit_code == 0
            assert "No plugins" in result.output

    def test_with_plugins(self, runner):
        plugin_list = [
            {"name": "demo-count", "description": "Count things", "version": "1.0"},
            {"name": "genomic-qc", "description": "QC pipeline", "version": "2.0"},
        ]

        with patch("byod_cli.cli.ConfigManager") as MockConfig, \
             patch("byod_cli.cli.APIClient") as MockClient:
            config_instance = MockConfig.return_value
            config_instance.get_api_key.return_value = "sk_live_test"
            config_instance.get_api_url.return_value = "https://api.test"

            client_instance = MockClient.return_value
            client_instance.list_plugins.return_value = plugin_list

            result = runner.invoke(cli, ["plugins"], catch_exceptions=False)
            assert result.exit_code == 0
            assert "demo-count" in result.output
            assert "genomic-qc" in result.output


# ---------------------------------------------------------------------------
# Config show command
# ---------------------------------------------------------------------------

class TestConfigShow:
    def test_displays_config(self, runner):
        with patch("byod_cli.cli.ConfigManager") as MockConfig:
            config_instance = MockConfig.return_value
            config_instance.config_file = Path("/home/test/.byod/config.yaml")
            config_instance.get_api_url.return_value = "https://api.lablytics.io"
            config_instance.is_authenticated.return_value = True
            config_instance.list_profiles.return_value = ["t-001"]
            config_instance.get_active_profile_name.return_value = "t-001"
            config_instance.get_profile.return_value = {
                "organization_name": "Test Lab"
            }

            result = runner.invoke(cli, ["config", "show"], catch_exceptions=False)
            assert result.exit_code == 0
            assert "api.lablytics.io" in result.output
