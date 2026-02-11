"""
Key Management Module for BYOD CLI

Handles generation, storage, and retrieval of local encryption keys.
Keys are stored in the user's home directory with restricted permissions.

Security Design:
----------------
- Master keys are stored with filesystem-level protection (mode 600)
- Keys are never transmitted to the platform
- Key rotation is supported with backward compatibility
- Backup and restore functionality with password protection

Storage Location: ~/.byod/keys/
"""

from __future__ import annotations

import json
import logging
import os
import stat
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class KeyManager:
    """
    Manages local encryption keys for BYOD CLI.

    Handles:
    - Master key generation and storage
    - Key retrieval and validation
    - Key backup and restoration
    - Key rotation
    """

    def __init__(self, config_dir: Path | None = None) -> None:
        """
        Initialize key manager.

        Args:
            config_dir: Configuration directory (default: ~/.byod/)
        """
        if config_dir is None:
            config_dir = Path.home() / ".byod"

        self.config_dir = config_dir
        self.keys_dir = config_dir / "keys"
        self.keys_dir.mkdir(parents=True, exist_ok=True)

        # Set restrictive permissions on keys directory
        try:
            os.chmod(self.keys_dir, stat.S_IRWXU)  # 700
        except OSError:
            pass

    def generate_master_key(self, profile_name: str, key_size_bits: int = 256) -> str:
        """
        Generate a new master encryption key for a profile.

        Args:
            profile_name: Name of the profile
            key_size_bits: Key size (128, 192, or 256)

        Returns:
            Key ID (unique identifier for this key)
        """
        if key_size_bits not in [128, 192, 256]:
            raise ValueError("Key size must be 128, 192, or 256 bits")

        key_size_bytes = key_size_bits // 8

        # Generate random key using OS entropy
        master_key = os.urandom(key_size_bytes)

        # Create key ID with timestamp
        key_id = f"{profile_name}-{datetime.now().strftime('%Y%m%d%H%M%S')}"

        # Store key metadata
        key_metadata: dict[str, Any] = {
            "key_id": key_id,
            "profile": profile_name,
            "key_size_bits": key_size_bits,
            "created_at": datetime.now().isoformat(),
            "algorithm": "AES-GCM",
        }

        # Save key file
        key_file = self.keys_dir / f"{key_id}.key"
        with open(key_file, "wb") as f:
            f.write(master_key)

        # Set restrictive permissions
        try:
            os.chmod(key_file, stat.S_IRUSR | stat.S_IWUSR)  # 600
        except OSError:
            pass

        # Save metadata
        metadata_file = self.keys_dir / f"{key_id}.meta.json"
        with open(metadata_file, "w") as f:
            json.dump(key_metadata, f, indent=2)

        try:
            os.chmod(metadata_file, stat.S_IRUSR | stat.S_IWUSR)  # 600
        except OSError:
            pass

        logger.info(f"Generated master key: {key_id}")
        return key_id

    def get_master_key(self, key_id: str) -> bytes:
        """
        Retrieve a master key by its ID.

        Args:
            key_id: Key identifier

        Returns:
            Master key bytes

        Raises:
            FileNotFoundError: If key doesn't exist
        """
        key_file = self.keys_dir / f"{key_id}.key"

        if not key_file.exists():
            raise FileNotFoundError(f"Master key not found: {key_id}")

        with open(key_file, "rb") as f:
            master_key = f.read()

        return master_key

    def list_keys(self) -> list[dict[str, Any]]:
        """
        List all available keys (metadata only, not the keys themselves).

        Returns:
            List of key metadata dictionaries
        """
        keys: list[dict[str, Any]] = []

        for meta_file in self.keys_dir.glob("*.meta.json"):
            with open(meta_file) as f:
                metadata = json.load(f)
                keys.append(metadata)

        return sorted(keys, key=lambda x: x["created_at"], reverse=True)

    def key_exists(self, key_id: str) -> bool:
        """Check if a key exists."""
        key_file = self.keys_dir / f"{key_id}.key"
        return key_file.exists()

    def get_key_metadata(self, key_id: str) -> dict[str, Any]:
        """Get metadata for a specific key."""
        metadata_file = self.keys_dir / f"{key_id}.meta.json"
        if not metadata_file.exists():
            raise FileNotFoundError(f"Key metadata not found: {key_id}")

        with open(metadata_file) as f:
            return json.load(f)

    def rotate_key(self, old_key_id: str, profile_name: str) -> str:
        """
        Generate a new key and mark old key as rotated.

        Args:
            old_key_id: Key to rotate
            profile_name: Profile name

        Returns:
            New key ID

        Note: This doesn't re-encrypt existing data.
        """
        new_key_id = self.generate_master_key(profile_name)

        # Mark old key as rotated
        old_meta_file = self.keys_dir / f"{old_key_id}.meta.json"
        if old_meta_file.exists():
            with open(old_meta_file) as f:
                old_metadata = json.load(f)

            old_metadata["rotated_at"] = datetime.now().isoformat()
            old_metadata["rotated_to"] = new_key_id

            with open(old_meta_file, "w") as f:
                json.dump(old_metadata, f, indent=2)

        logger.info(f"Rotated key {old_key_id} -> {new_key_id}")
        return new_key_id

    def delete_key(self, key_id: str, confirm: bool = False) -> None:
        """
        Delete a key (use with extreme caution!).

        Args:
            key_id: Key to delete
            confirm: Must be True to actually delete

        Warning: Deleting a key makes all data encrypted with it unrecoverable!
        """
        if not confirm:
            raise ValueError("Must confirm key deletion (set confirm=True)")

        key_file = self.keys_dir / f"{key_id}.key"
        meta_file = self.keys_dir / f"{key_id}.meta.json"

        if key_file.exists():
            # Securely overwrite before deleting
            file_size = key_file.stat().st_size
            with open(key_file, "wb") as f:
                f.write(os.urandom(file_size))
            key_file.unlink()

        if meta_file.exists():
            meta_file.unlink()

        logger.warning(f"Deleted key: {key_id}")
