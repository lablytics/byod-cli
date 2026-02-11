"""Shared test fixtures for BYOD CLI tests."""

import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from byod_cli.encryption import EncryptionManager


@pytest.fixture
def temp_dir():
    """Provide a temporary directory that is cleaned up after the test."""
    with tempfile.TemporaryDirectory() as td:
        yield Path(td)


@pytest.fixture
def sample_file(temp_dir):
    """Create a sample plaintext file with repeating ATCG data."""
    path = temp_dir / "sample.fastq"
    # ~1KB of fake genomic data
    content = b"@SEQ_001\nATCGATCGATCGATCG\n+\nIIIIIIIIIIIIIIII\n" * 25
    path.write_bytes(content)
    return path


@pytest.fixture
def aes_key():
    """Generate a random 256-bit AES key."""
    return os.urandom(32)


@pytest.fixture
def mock_key_manager(tmp_path):
    """
    A mock KeyManager that stores keys in a dict instead of the filesystem.

    Supports generate_master_key and get_master_key.
    """
    keys = {}
    manager = MagicMock()

    def generate_master_key(profile_name, key_size_bits=256):
        key_id = f"{profile_name}-test"
        keys[key_id] = os.urandom(key_size_bits // 8)
        return key_id

    def get_master_key(key_id):
        if key_id not in keys:
            raise FileNotFoundError(f"Master key not found: {key_id}")
        return keys[key_id]

    manager.generate_master_key = generate_master_key
    manager.get_master_key = get_master_key
    manager._keys = keys  # expose for test introspection
    return manager


@pytest.fixture
def encryption_manager(mock_key_manager):
    """EncryptionManager wired to the mock key manager with a fresh master key."""
    key_id = mock_key_manager.generate_master_key("test-profile")
    return EncryptionManager(mock_key_manager, key_id)
