"""Tests for CLI UX features.

Covers: --quiet, --no-color, --format json, deprecation warnings,
profile commands, completion command, --live flag, exit codes.
"""

import json
from unittest.mock import MagicMock, patch

import pytest
from byod_cli.cli import EXIT_AUTH, EXIT_ERROR, EXIT_NETWORK, EXIT_OK, cli
from click.testing import CliRunner


@pytest.fixture
def runner():
    return CliRunner()


# ---------------------------------------------------------------------------
# --quiet and --no-color flags
# ---------------------------------------------------------------------------

class TestQuietFlag:
    def test_quiet_suppresses_output(self, runner):
        """--quiet should suppress rich output."""
        with patch("byod_cli.cli.ConfigManager") as MockConfig:
            config_instance = MockConfig.return_value
            config_instance.is_authenticated.return_value = False

            result = runner.invoke(cli, ["--quiet", "auth", "status"], catch_exceptions=False)
            assert result.exit_code == 0
            # Quiet mode suppresses console.print output
            # The exact behavior depends on rich Console(quiet=True)

    def test_no_color_flag(self, runner):
        """--no-color should disable colored output."""
        with patch("byod_cli.cli.ConfigManager") as MockConfig:
            config_instance = MockConfig.return_value
            config_instance.is_authenticated.return_value = False

            result = runner.invoke(cli, ["--no-color", "auth", "status"], catch_exceptions=False)
            assert result.exit_code == 0


class TestNoColorEnvVar:
    def test_no_color_env(self, runner):
        """NO_COLOR env var should disable colors."""
        with patch("byod_cli.cli.ConfigManager") as MockConfig:
            config_instance = MockConfig.return_value
            config_instance.is_authenticated.return_value = False

            result = runner.invoke(
                cli, ["auth", "status"],
                catch_exceptions=False,
                env={"NO_COLOR": "1"},
            )
            assert result.exit_code == 0


# ---------------------------------------------------------------------------
# --format json on auth status
# ---------------------------------------------------------------------------

class TestAuthStatusJson:
    def test_not_authenticated_json(self, runner):
        with patch("byod_cli.cli.ConfigManager") as MockConfig:
            config_instance = MockConfig.return_value
            config_instance.is_authenticated.return_value = False

            result = runner.invoke(
                cli, ["auth", "status", "--format", "json"],
                catch_exceptions=False,
            )
            assert result.exit_code == 0
            data = json.loads(result.output)
            assert data["authenticated"] is False

    def test_authenticated_json(self, runner):
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
            config_instance.get_api_url.return_value = "https://api.test"

            client_instance = MockClient.return_value
            client_instance.verify_auth.return_value = {"tenant_id": "t-001"}
            client_instance.get_tenant_config.return_value = mock_tenant

            result = runner.invoke(
                cli, ["auth", "status", "--format", "json"],
                catch_exceptions=False,
            )
            assert result.exit_code == 0
            data = json.loads(result.output)
            assert data["authenticated"] is True
            assert data["organization"] == "Test Lab"
            assert data["tenant_id"] == "t-001"


# ---------------------------------------------------------------------------
# --format json on plugins
# ---------------------------------------------------------------------------

class TestPluginsJson:
    def test_json_format(self, runner):
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

            result = runner.invoke(
                cli, ["plugins", "--format", "json"],
                catch_exceptions=False,
            )
            assert result.exit_code == 0
            data = json.loads(result.output)
            assert len(data) == 2
            assert data[0]["name"] == "demo-count"


# ---------------------------------------------------------------------------
# Deprecation warnings
# ---------------------------------------------------------------------------

class TestDeprecationWarnings:
    def test_retrieve_deprecated(self, runner):
        """retrieve command should show deprecation warning."""
        with patch("byod_cli.cli.ConfigManager") as MockConfig, \
             patch("byod_cli.cli.APIClient") as MockClient:
            config_instance = MockConfig.return_value
            config_instance.get_api_key.return_value = "sk_live_test"
            config_instance.get_api_url.return_value = "https://api.test"

            client_instance = MockClient.return_value
            client_instance.get_download_url.return_value = MagicMock(url="http://test", s3_key="k")
            client_instance.get_tenant_config.return_value = MagicMock(
                customer_kms_key_arn="arn:aws:kms:us-east-1:123:key/abc",
                kms_key_arn="arn:aws:kms:us-east-1:123:key/abc",
                region="us-east-1",
            )

            # Just check the deprecation warning appears - the command will fail
            # on actual download, but the warning is printed first
            result = runner.invoke(
                cli, ["retrieve", "j1", "-o", "/tmp/test-output-retrieve"],
            )
            output = result.output
            assert "deprecated" in output.lower() or "DeprecationWarning" in output

    def test_decrypt_deprecated(self, runner, tmp_path):
        """decrypt command should show deprecation warning."""
        # Create minimal results dir
        results_dir = tmp_path / "results"
        results_dir.mkdir()
        manifest = {
            "job_id": "j1",
            "encrypted_file": "output.enc",
            "wrapped_key_file": "output_key.bin",
            "kms_key_id": "arn:aws:kms:us-east-1:123:key/abc",
            "region": "us-east-1",
        }
        (results_dir / "results-manifest.json").write_text(json.dumps(manifest))
        (results_dir / "output.enc").write_bytes(b"encrypted")
        (results_dir / "output_key.bin").write_bytes(b"key")

        with patch("byod_cli.cli.ConfigManager"):
            result = runner.invoke(
                cli, ["decrypt", str(results_dir), "-o", str(tmp_path / "out")],
            )
            output = result.output
            assert "deprecated" in output.lower() or "DeprecationWarning" in output


# ---------------------------------------------------------------------------
# --wait flag (--live and --track are hidden aliases)
# ---------------------------------------------------------------------------

class TestWaitFlag:
    def test_help_shows_wait(self, runner):
        """submit --help should show --wait."""
        result = runner.invoke(cli, ["submit", "--help"])
        assert "--wait" in result.output

    def test_live_and_track_are_hidden(self, runner):
        """--live and --track should not appear in help (they are hidden aliases)."""
        result = runner.invoke(cli, ["submit", "--help"])
        assert "--live" not in result.output
        assert "--track" not in result.output


# ---------------------------------------------------------------------------
# Profile commands
# ---------------------------------------------------------------------------

class TestProfileCommands:
    def test_profile_list_empty(self, runner):
        with patch("byod_cli.cli.ConfigManager") as MockConfig:
            config_instance = MockConfig.return_value
            config_instance.list_profiles.return_value = []

            result = runner.invoke(cli, ["profile", "list"], catch_exceptions=False)
            assert result.exit_code == 0
            assert "No profiles" in result.output

    def test_profile_list_with_profiles(self, runner):
        with patch("byod_cli.cli.ConfigManager") as MockConfig:
            config_instance = MockConfig.return_value
            config_instance.list_profiles.return_value = ["t-001", "t-002"]
            config_instance.get_active_profile_name.return_value = "t-001"
            config_instance.get_profile.side_effect = lambda name: {
                "t-001": {"organization_name": "Lab A", "region": "us-east-1"},
                "t-002": {"organization_name": "Lab B", "region": "eu-west-1"},
            }[name]

            result = runner.invoke(cli, ["profile", "list"], catch_exceptions=False)
            assert result.exit_code == 0
            assert "Lab A" in result.output
            assert "Lab B" in result.output

    def test_profile_switch_success(self, runner):
        with patch("byod_cli.cli.ConfigManager") as MockConfig:
            config_instance = MockConfig.return_value

            result = runner.invoke(cli, ["profile", "switch", "t-001"], catch_exceptions=False)
            assert result.exit_code == 0
            config_instance.set_active_profile.assert_called_once_with("t-001")

    def test_profile_switch_not_found(self, runner):
        with patch("byod_cli.cli.ConfigManager") as MockConfig:
            config_instance = MockConfig.return_value
            config_instance.set_active_profile.side_effect = ValueError("Profile 'nope' not found")
            config_instance.list_profiles.return_value = ["t-001"]

            result = runner.invoke(cli, ["profile", "switch", "nope"])
            assert result.exit_code == EXIT_ERROR

    def test_profile_show_no_profile(self, runner):
        with patch("byod_cli.cli.ConfigManager") as MockConfig:
            config_instance = MockConfig.return_value
            config_instance.get_active_profile_name.return_value = None

            result = runner.invoke(cli, ["profile", "show"], catch_exceptions=False)
            assert result.exit_code == 0
            assert "No active profile" in result.output

    def test_profile_show_with_profile(self, runner):
        with patch("byod_cli.cli.ConfigManager") as MockConfig:
            config_instance = MockConfig.return_value
            config_instance.get_active_profile_name.return_value = "t-001"
            config_instance.get_profile.return_value = {
                "tenant_id": "t-001",
                "organization_name": "Test Lab",
                "region": "us-east-1",
                "created_at": "2026-01-01",
                "settings": {
                    "kms_key_arn": "arn:aws:kms:us-east-1:123:key/abc",
                    "role_arn": "arn:aws:iam::123:role/BYODEnclaveRole",
                },
            }

            result = runner.invoke(cli, ["profile", "show"], catch_exceptions=False)
            assert result.exit_code == 0
            assert "Test Lab" in result.output


# ---------------------------------------------------------------------------
# Shell completion
# ---------------------------------------------------------------------------

class TestCompletion:
    def test_completion_bash(self, runner):
        result = runner.invoke(cli, ["completion", "bash"], catch_exceptions=False)
        assert result.exit_code == 0
        # Should output some shell script content
        assert len(result.output) > 0

    def test_completion_invalid_shell(self, runner):
        result = runner.invoke(cli, ["completion", "powershell"])
        assert result.exit_code != 0


# ---------------------------------------------------------------------------
# Exit codes
# ---------------------------------------------------------------------------

class TestExitCodes:
    def test_exit_code_constants(self):
        assert EXIT_OK == 0
        assert EXIT_ERROR == 1
        assert EXIT_AUTH == 2
        assert EXIT_NETWORK == 3

    def test_auth_failure_exit_code(self, runner):
        from byod_cli.api_client import AuthenticationError

        with patch("byod_cli.cli.ConfigManager") as MockConfig, \
             patch("byod_cli.cli.APIClient") as MockClient:
            config_instance = MockConfig.return_value
            config_instance.get_api_key.return_value = "sk_live_test"
            config_instance.get_api_url.return_value = "https://api.test"

            MockClient.return_value.verify_auth.side_effect = AuthenticationError("Bad", 401)

            result = runner.invoke(
                cli, ["auth", "login", "--api-key", "bad_key"],
            )
            assert result.exit_code == EXIT_AUTH


# ---------------------------------------------------------------------------
# Improved error messages
# ---------------------------------------------------------------------------

class TestErrorMessages:
    def test_unauthenticated_message(self, runner):
        with patch("byod_cli.cli.ConfigManager") as MockConfig:
            config_instance = MockConfig.return_value
            config_instance.get_api_key.return_value = None

            result = runner.invoke(cli, ["status", "j1"])
            assert "byod auth login" in result.output
            assert "byod.cultivatedcode.co" in result.output

    def test_auth_login_url_updated(self, runner):
        """auth login help should reference cultivatedcode.co."""
        result = runner.invoke(cli, ["auth", "login", "--help"])
        assert "byod.cultivatedcode.co" in result.output
        assert "app.lablytics.io" not in result.output
