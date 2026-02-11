"""
Configuration Management Module for BYOD CLI

Handles loading, saving, and managing CLI configuration including profiles.
Configuration is stored in YAML format in ~/.byod/config.yaml

Configuration Structure:
-----------------------
version: 2
api_url: https://api.lablytics.io
api_key: sk_live_...  # Stored securely

profiles:
  profile-name:
    tenant_id: tenant-abc123
    organization_name: Acme Biotech
    region: us-east-1
    # Buckets are managed by Lablytics - fetched from API
    created_at: 2024-01-15T10:30:00Z
    settings:
      timeout: 3600

global:
  log_level: info
  color_output: true
"""

from __future__ import annotations

import logging
import os
import stat
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)


class ConfigManager:
    """
    Manages CLI configuration and profiles.

    Handles:
    - Profile creation and management
    - Configuration loading and saving
    - Environment variable overrides
    - Default settings
    """

    DEFAULT_CONFIG_DIR = Path.home() / ".byod"
    CONFIG_FILE_NAME = "config.yaml"

    def __init__(self, config_dir: Path | None = None) -> None:
        """
        Initialize configuration manager.

        Args:
            config_dir: Configuration directory (default: ~/.byod/)
        """
        self.config_dir = config_dir or self.DEFAULT_CONFIG_DIR
        self.config_file = self.config_dir / self.CONFIG_FILE_NAME

        # Ensure config directory exists with restricted permissions
        self.config_dir.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(self.config_dir, stat.S_IRWXU)  # 700
        except OSError:
            pass  # Windows doesn't support chmod the same way

        # Load or create config
        self.config = self._load_config()

    def _load_config(self) -> dict[str, Any]:
        """Load configuration from file or create default."""
        if self.config_file.exists():
            with open(self.config_file) as f:
                config = yaml.safe_load(f) or {}
                logger.debug(f"Loaded config from {self.config_file}")
                return config
        else:
            default_config: dict[str, Any] = {
                "version": 2,
                "api_url": "https://byod.cultivatedcode.co/",
                "api_key": None,
                "active_profile": None,
                "profiles": {},
                "global": {
                    "log_level": "info",
                    "color_output": True,
                    "verify_ssl": True,
                    "timeout": 3600,
                },
            }
            self._save_config(default_config)
            logger.info(f"Created default config at {self.config_file}")
            return default_config

    def _save_config(self, config: dict[str, Any] | None = None) -> None:
        """Save configuration to file."""
        config_to_save = config or self.config

        with open(self.config_file, "w") as f:
            yaml.dump(config_to_save, f, default_flow_style=False, sort_keys=False)

        # Set restrictive permissions
        try:
            os.chmod(self.config_file, stat.S_IRUSR | stat.S_IWUSR)  # 600
        except OSError:
            pass

        logger.debug(f"Saved config to {self.config_file}")

    # =========================================================================
    # API Authentication
    # =========================================================================

    def set_api_credentials(self, api_key: str, api_url: str | None = None) -> None:
        """
        Store API credentials.

        Args:
            api_key: Lablytics API key
            api_url: Optional custom API URL (for self-hosted)
        """
        self.config["api_key"] = api_key
        if api_url:
            self.config["api_url"] = api_url
        self._save_config()
        logger.info("API credentials saved")

    def get_api_key(self) -> str | None:
        """Get stored API key."""
        # Environment variable takes precedence
        env_key = os.environ.get("BYOD_API_KEY")
        if env_key:
            return env_key
        return self.config.get("api_key")

    def get_api_url(self) -> str:
        """Get API URL."""
        env_url = os.environ.get("BYOD_API_URL")
        if env_url:
            return env_url
        return self.config.get("api_url", "https://byod.cultivatedcode.co/")

    def clear_api_credentials(self) -> None:
        """Remove stored API credentials."""
        self.config["api_key"] = None
        self._save_config()
        logger.info("API credentials cleared")

    def is_authenticated(self) -> bool:
        """Check if API credentials are configured."""
        return self.get_api_key() is not None

    # =========================================================================
    # Profile Management
    # =========================================================================

    def create_profile(
        self,
        name: str,
        tenant_id: str,
        organization_name: str,
        region: str = "us-east-1",
    ) -> None:
        """
        Create a new profile from platform tenant config.

        Args:
            name: Profile name
            tenant_id: Tenant ID from platform
            organization_name: Organization name
            region: AWS region

        Raises:
            ValueError: If profile already exists
        """
        if name in self.config.get("profiles", {}):
            raise ValueError(f"Profile '{name}' already exists")

        profile = {
            "tenant_id": tenant_id,
            "organization_name": organization_name,
            "region": region,
            "created_at": datetime.now().isoformat(),
            "settings": {
                "timeout": 3600,
            },
        }

        if "profiles" not in self.config:
            self.config["profiles"] = {}

        self.config["profiles"][name] = profile

        # Set as active if it's the first profile
        if self.config["active_profile"] is None:
            self.config["active_profile"] = name

        self._save_config()
        logger.info(f"Created profile: {name}")

    def delete_profile(self, name: str) -> None:
        """Delete a profile."""
        if name not in self.config.get("profiles", {}):
            raise ValueError(f"Profile '{name}' not found")

        del self.config["profiles"][name]

        if self.config.get("active_profile") == name:
            remaining_profiles = list(self.config["profiles"].keys())
            self.config["active_profile"] = remaining_profiles[0] if remaining_profiles else None

        self._save_config()
        logger.info(f"Deleted profile: {name}")

    def get_profile(self, name: str) -> dict[str, Any]:
        """Get profile configuration."""
        profiles = self.config.get("profiles", {})
        if name not in profiles:
            raise ValueError(f"Profile '{name}' not found")
        return profiles[name].copy()

    def list_profiles(self) -> list[str]:
        """List all profile names."""
        return list(self.config.get("profiles", {}).keys())

    def profile_exists(self, name: str) -> bool:
        """Check if a profile exists."""
        return name in self.config.get("profiles", {})

    def set_active_profile(self, name: str) -> None:
        """Set the active profile."""
        if not self.profile_exists(name):
            raise ValueError(f"Profile '{name}' not found")
        self.config["active_profile"] = name
        self._save_config()
        logger.info(f"Set active profile: {name}")

    def get_active_profile_name(self) -> str | None:
        """Get the name of the active profile."""
        env_profile = os.environ.get("BYOD_PROFILE")
        if env_profile:
            return env_profile
        return self.config.get("active_profile")

    def get_active_profile_config(self) -> dict[str, Any]:
        """Get the active profile configuration."""
        active_name = self.get_active_profile_name()

        if not active_name:
            raise ValueError("No active profile set. Run 'byod init' to create one.")

        profile_config = self.get_profile(active_name)

        if "BYOD_API_URL" in os.environ:
            profile_config["api_url"] = os.environ["BYOD_API_URL"]

        return profile_config

    def get_global_setting(self, key: str, default: Any = None) -> Any:
        """Get a global setting value."""
        return self.config.get("global", {}).get(key, default)

    def set_global_setting(self, key: str, value: Any) -> None:
        """Set a global setting value."""
        if "global" not in self.config:
            self.config["global"] = {}
        self.config["global"][key] = value
        self._save_config()
        logger.info(f"Set global setting: {key} = {value}")

    def update_profile_setting(self, profile_name: str, key: str, value: Any) -> None:
        """Update a setting for a specific profile."""
        if not self.profile_exists(profile_name):
            raise ValueError(f"Profile '{profile_name}' not found")

        if "settings" not in self.config["profiles"][profile_name]:
            self.config["profiles"][profile_name]["settings"] = {}

        self.config["profiles"][profile_name]["settings"][key] = value
        self._save_config()
        logger.info(f"Updated {profile_name}.{key} = {value}")

    def get_config_dict(self) -> dict[str, Any]:
        """Get the entire configuration dictionary."""
        return self.config.copy()
