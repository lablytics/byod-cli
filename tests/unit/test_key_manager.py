"""Tests for KeyManager (byod_cli/key_manager.py).

Covers key generation, storage, retrieval, listing, rotation, and deletion.
"""

import json

import pytest
from byod_cli.key_manager import KeyManager


@pytest.fixture
def key_manager(temp_dir):
    return KeyManager(config_dir=temp_dir)


# ---------------------------------------------------------------------------
# Key generation
# ---------------------------------------------------------------------------

class TestGenerateMasterKey:
    def test_generates_key_and_returns_id(self, key_manager):
        key_id = key_manager.generate_master_key("test-profile")
        assert key_id.startswith("test-profile-")

    def test_key_is_correct_size(self, key_manager):
        key_id = key_manager.generate_master_key("p", key_size_bits=256)
        key = key_manager.get_master_key(key_id)
        assert len(key) == 32

    def test_128_bit_key(self, key_manager):
        key_id = key_manager.generate_master_key("p", key_size_bits=128)
        key = key_manager.get_master_key(key_id)
        assert len(key) == 16

    def test_192_bit_key(self, key_manager):
        key_id = key_manager.generate_master_key("p", key_size_bits=192)
        key = key_manager.get_master_key(key_id)
        assert len(key) == 24

    def test_invalid_key_size_raises(self, key_manager):
        with pytest.raises(ValueError, match="Key size must be"):
            key_manager.generate_master_key("p", key_size_bits=512)

    def test_creates_key_file(self, key_manager):
        key_id = key_manager.generate_master_key("prof")
        key_file = key_manager.keys_dir / f"{key_id}.key"
        assert key_file.exists()

    def test_creates_metadata_file(self, key_manager):
        key_id = key_manager.generate_master_key("prof")
        meta_file = key_manager.keys_dir / f"{key_id}.meta.json"
        assert meta_file.exists()

        meta = json.loads(meta_file.read_text())
        assert meta["key_id"] == key_id
        assert meta["profile"] == "prof"
        assert meta["key_size_bits"] == 256
        assert meta["algorithm"] == "AES-GCM"

    def test_generated_keys_are_unique(self, key_manager):
        k1 = key_manager.get_master_key(key_manager.generate_master_key("a"))
        k2 = key_manager.get_master_key(key_manager.generate_master_key("b"))
        assert k1 != k2


# ---------------------------------------------------------------------------
# Key retrieval
# ---------------------------------------------------------------------------

class TestGetMasterKey:
    def test_roundtrip(self, key_manager):
        key_id = key_manager.generate_master_key("p")
        key = key_manager.get_master_key(key_id)
        assert isinstance(key, bytes)
        assert len(key) == 32

    def test_missing_key_raises(self, key_manager):
        with pytest.raises(FileNotFoundError, match="Master key not found"):
            key_manager.get_master_key("nonexistent-key")


# ---------------------------------------------------------------------------
# Key listing
# ---------------------------------------------------------------------------

class TestListKeys:
    def test_empty_initially(self, key_manager):
        assert key_manager.list_keys() == []

    def test_lists_all_keys(self, key_manager):
        key_manager.generate_master_key("alpha")
        key_manager.generate_master_key("beta")
        keys = key_manager.list_keys()
        assert len(keys) == 2
        profiles = {k["profile"] for k in keys}
        assert profiles == {"alpha", "beta"}

    def test_sorted_by_created_at_desc(self, key_manager):
        import time
        key_manager.generate_master_key("first")
        time.sleep(1.1)  # Ensure different timestamps
        key_manager.generate_master_key("second")
        keys = key_manager.list_keys()
        assert keys[0]["profile"] == "second"
        assert keys[1]["profile"] == "first"


# ---------------------------------------------------------------------------
# Key existence
# ---------------------------------------------------------------------------

class TestKeyExists:
    def test_exists(self, key_manager):
        key_id = key_manager.generate_master_key("p")
        assert key_manager.key_exists(key_id) is True

    def test_does_not_exist(self, key_manager):
        assert key_manager.key_exists("no-such-key") is False


# ---------------------------------------------------------------------------
# Key metadata
# ---------------------------------------------------------------------------

class TestGetKeyMetadata:
    def test_success(self, key_manager):
        key_id = key_manager.generate_master_key("prof")
        meta = key_manager.get_key_metadata(key_id)
        assert meta["key_id"] == key_id
        assert meta["profile"] == "prof"

    def test_missing_raises(self, key_manager):
        with pytest.raises(FileNotFoundError, match="Key metadata not found"):
            key_manager.get_key_metadata("nope")


# ---------------------------------------------------------------------------
# Key rotation
# ---------------------------------------------------------------------------

class TestRotateKey:
    def test_returns_valid_key_id(self, key_manager):
        old_id = key_manager.generate_master_key("old-prof")
        new_id = key_manager.rotate_key(old_id, "new-prof")
        assert new_id.startswith("new-prof-")
        assert key_manager.key_exists(new_id)

    def test_marks_old_key_as_rotated(self, key_manager):
        old_id = key_manager.generate_master_key("old-prof")
        new_id = key_manager.rotate_key(old_id, "new-prof")

        old_meta = key_manager.get_key_metadata(old_id)
        assert "rotated_at" in old_meta
        assert old_meta["rotated_to"] == new_id

    def test_old_key_still_readable(self, key_manager):
        old_id = key_manager.generate_master_key("old-prof")
        key_manager.rotate_key(old_id, "new-prof")
        assert len(key_manager.get_master_key(old_id)) == 32


# ---------------------------------------------------------------------------
# Key deletion
# ---------------------------------------------------------------------------

class TestDeleteKey:
    def test_requires_confirmation(self, key_manager):
        key_id = key_manager.generate_master_key("p")
        with pytest.raises(ValueError, match="Must confirm"):
            key_manager.delete_key(key_id, confirm=False)

    def test_deletes_key_file(self, key_manager):
        key_id = key_manager.generate_master_key("p")
        key_manager.delete_key(key_id, confirm=True)
        assert not key_manager.key_exists(key_id)

    def test_deletes_metadata_file(self, key_manager):
        key_id = key_manager.generate_master_key("p")
        key_manager.delete_key(key_id, confirm=True)
        meta_file = key_manager.keys_dir / f"{key_id}.meta.json"
        assert not meta_file.exists()

    def test_deleted_key_not_retrievable(self, key_manager):
        key_id = key_manager.generate_master_key("p")
        key_manager.delete_key(key_id, confirm=True)
        with pytest.raises(FileNotFoundError):
            key_manager.get_master_key(key_id)
