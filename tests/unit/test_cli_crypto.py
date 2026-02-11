"""Tests for the standalone _encrypt_data / _decrypt_data helpers in cli.py.

These are simpler than EncryptionManager — no associated data, no file I/O.
"""

import os

import pytest
from cryptography.exceptions import InvalidTag

from byod_cli.cli import NONCE_SIZE, _decrypt_data, _encrypt_data


class TestEncryptDecryptData:
    def test_roundtrip(self):
        key = os.urandom(32)
        plaintext = b"Hello, BYOD!"
        encrypted = _encrypt_data(plaintext, key)
        assert _decrypt_data(encrypted, key) == plaintext

    def test_output_format(self):
        """Output length = 12 (nonce) + len(plaintext) + 16 (tag)."""
        key = os.urandom(32)
        plaintext = b"ATCGATCG" * 100
        encrypted = _encrypt_data(plaintext, key)
        assert len(encrypted) == NONCE_SIZE + len(plaintext) + 16

    def test_nondeterministic(self):
        key = os.urandom(32)
        plaintext = b"same input twice"
        enc1 = _encrypt_data(plaintext, key)
        enc2 = _encrypt_data(plaintext, key)
        assert enc1 != enc2

    def test_wrong_key_fails(self):
        key1 = os.urandom(32)
        key2 = os.urandom(32)
        encrypted = _encrypt_data(b"secret", key1)
        with pytest.raises(InvalidTag):
            _decrypt_data(encrypted, key2)

    def test_empty_plaintext(self):
        key = os.urandom(32)
        encrypted = _encrypt_data(b"", key)
        assert _decrypt_data(encrypted, key) == b""
        # nonce + 0-byte ciphertext + tag
        assert len(encrypted) == NONCE_SIZE + 0 + 16

    def test_large_plaintext(self):
        """Verify encrypt/decrypt with 10 MB of data."""
        key = os.urandom(32)
        plaintext = os.urandom(10 * 1024 * 1024)
        encrypted = _encrypt_data(plaintext, key)
        assert _decrypt_data(encrypted, key) == plaintext
