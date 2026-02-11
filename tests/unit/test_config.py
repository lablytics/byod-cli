"""Tests for ConfigManager (byod_cli/config.py).

Covers config creation, profile CRUD, API credentials, env var overrides,
and global settings.
"""


import pytest

from byod_cli.config import ConfigManager


@pytest.fixture
def config_manager(temp_dir):
    return ConfigManager(config_dir=temp_dir)


# ---------------------------------------------------------------------------
# Initialization
# ---------------------------------------------------------------------------

class TestInit:
    def test_creates_config_dir(self, temp_dir):
        cfg_dir = temp_dir / "newdir"
        ConfigManager(config_dir=cfg_dir)
        assert cfg_dir.exists()

    def test_creates_default_config(self, config_manager):
        assert config_manager.config["version"] == 2
        assert config_manager.config["api_key"] is None
        assert config_manager.config["active_profile"] is None
        assert isinstance(config_manager.config["profiles"], dict)

    def test_persists_default_config(self, temp_dir):
        ConfigManager(config_dir=temp_dir)
        # Re-load from disk
        cm2 = ConfigManager(config_dir=temp_dir)
        assert cm2.config["version"] == 2


# ---------------------------------------------------------------------------
# API credentials
# ---------------------------------------------------------------------------

class TestApiCredentials:
    def test_set_and_get(self, config_manager):
        config_manager.set_api_credentials("sk_live_abc123")
        assert config_manager.get_api_key() == "sk_live_abc123"

    def test_set_with_custom_url(self, config_manager):
        config_manager.set_api_credentials("key", api_url="https://custom.io")
        assert config_manager.get_api_url() == "https://custom.io"

    def test_clear(self, config_manager):
        config_manager.set_api_credentials("sk_live_abc123")
        config_manager.clear_api_credentials()
        assert config_manager.get_api_key() is None

    def test_is_authenticated(self, config_manager):
        assert config_manager.is_authenticated() is False
        config_manager.set_api_credentials("sk_live_test")
        assert config_manager.is_authenticated() is True

    def test_env_var_override(self, config_manager, monkeypatch):
        config_manager.set_api_credentials("from_file")
        monkeypatch.setenv("BYOD_API_KEY", "from_env")
        assert config_manager.get_api_key() == "from_env"

    def test_api_url_env_override(self, config_manager, monkeypatch):
        monkeypatch.setenv("BYOD_API_URL", "https://override.io")
        assert config_manager.get_api_url() == "https://override.io"

    def test_default_api_url(self, config_manager):
        assert "cultivatedcode" in config_manager.get_api_url()

    def test_persists_across_loads(self, temp_dir):
        cm1 = ConfigManager(config_dir=temp_dir)
        cm1.set_api_credentials("sk_live_persist")
        cm2 = ConfigManager(config_dir=temp_dir)
        assert cm2.get_api_key() == "sk_live_persist"


# ---------------------------------------------------------------------------
# Profile management
# ---------------------------------------------------------------------------

class TestProfiles:
    def test_create_profile(self, config_manager):
        config_manager.create_profile("lab-a", "t-001", "Lab A", "us-east-1")
        assert config_manager.profile_exists("lab-a")

    def test_first_profile_becomes_active(self, config_manager):
        config_manager.create_profile("lab-a", "t-001", "Lab A")
        assert config_manager.get_active_profile_name() == "lab-a"

    def test_duplicate_profile_raises(self, config_manager):
        config_manager.create_profile("lab-a", "t-001", "Lab A")
        with pytest.raises(ValueError, match="already exists"):
            config_manager.create_profile("lab-a", "t-002", "Lab A Dupe")

    def test_get_profile(self, config_manager):
        config_manager.create_profile("lab-a", "t-001", "Lab A", "eu-west-1")
        p = config_manager.get_profile("lab-a")
        assert p["tenant_id"] == "t-001"
        assert p["organization_name"] == "Lab A"
        assert p["region"] == "eu-west-1"

    def test_get_missing_profile_raises(self, config_manager):
        with pytest.raises(ValueError, match="not found"):
            config_manager.get_profile("nope")

    def test_list_profiles(self, config_manager):
        config_manager.create_profile("alpha", "t1", "Alpha")
        config_manager.create_profile("beta", "t2", "Beta")
        names = config_manager.list_profiles()
        assert set(names) == {"alpha", "beta"}

    def test_delete_profile(self, config_manager):
        config_manager.create_profile("lab-a", "t-001", "Lab A")
        config_manager.delete_profile("lab-a")
        assert not config_manager.profile_exists("lab-a")

    def test_delete_active_switches(self, config_manager):
        config_manager.create_profile("a", "t1", "A")
        config_manager.create_profile("b", "t2", "B")
        config_manager.set_active_profile("a")
        config_manager.delete_profile("a")
        assert config_manager.get_active_profile_name() == "b"

    def test_delete_last_profile_clears_active(self, config_manager):
        config_manager.create_profile("only", "t1", "Only")
        config_manager.delete_profile("only")
        assert config_manager.get_active_profile_name() is None

    def test_delete_missing_raises(self, config_manager):
        with pytest.raises(ValueError, match="not found"):
            config_manager.delete_profile("nope")

    def test_set_active_profile(self, config_manager):
        config_manager.create_profile("a", "t1", "A")
        config_manager.create_profile("b", "t2", "B")
        config_manager.set_active_profile("b")
        assert config_manager.get_active_profile_name() == "b"

    def test_set_active_missing_raises(self, config_manager):
        with pytest.raises(ValueError, match="not found"):
            config_manager.set_active_profile("nope")

    def test_env_profile_override(self, config_manager, monkeypatch):
        config_manager.create_profile("a", "t1", "A")
        monkeypatch.setenv("BYOD_PROFILE", "env-profile")
        assert config_manager.get_active_profile_name() == "env-profile"

    def test_get_active_profile_config(self, config_manager):
        config_manager.create_profile("lab", "t1", "Lab", "us-west-2")
        cfg = config_manager.get_active_profile_config()
        assert cfg["tenant_id"] == "t1"
        assert cfg["region"] == "us-west-2"

    def test_get_active_no_profile_raises(self, config_manager):
        with pytest.raises(ValueError, match="No active profile"):
            config_manager.get_active_profile_config()


# ---------------------------------------------------------------------------
# Global settings
# ---------------------------------------------------------------------------

class TestGlobalSettings:
    def test_get_default(self, config_manager):
        assert config_manager.get_global_setting("log_level") == "info"

    def test_get_missing_returns_default(self, config_manager):
        assert config_manager.get_global_setting("nope", "fallback") == "fallback"

    def test_set_and_get(self, config_manager):
        config_manager.set_global_setting("timeout", 9999)
        assert config_manager.get_global_setting("timeout") == 9999


# ---------------------------------------------------------------------------
# Profile settings
# ---------------------------------------------------------------------------

class TestProfileSettings:
    def test_update_setting(self, config_manager):
        config_manager.create_profile("lab", "t1", "Lab")
        config_manager.update_profile_setting("lab", "timeout", 7200)
        p = config_manager.get_profile("lab")
        assert p["settings"]["timeout"] == 7200

    def test_update_missing_profile_raises(self, config_manager):
        with pytest.raises(ValueError, match="not found"):
            config_manager.update_profile_setting("nope", "key", "value")
