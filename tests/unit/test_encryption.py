"""Tests for EncryptionManager (byod_cli/encryption.py).

Covers DEK generation, wrap/unwrap, file encrypt/decrypt, and
associated-data binding that prevents key- and file-substitution attacks.
"""

import os

import pytest
from byod_cli.encryption import EncryptionManager
from cryptography.exceptions import InvalidTag

# ---------------------------------------------------------------------------
# DEK generation
# ---------------------------------------------------------------------------

class TestGenerateDek:
    def test_is_32_bytes(self, encryption_manager):
        dek = encryption_manager.generate_dek()
        assert len(dek) == 32

    def test_is_unique(self, encryption_manager):
        dek1 = encryption_manager.generate_dek()
        dek2 = encryption_manager.generate_dek()
        assert dek1 != dek2


# ---------------------------------------------------------------------------
# DEK wrapping / unwrapping
# ---------------------------------------------------------------------------

class TestWrapUnwrap:
    def test_roundtrip(self, encryption_manager):
        dek = encryption_manager.generate_dek()
        nonce, wrapped = encryption_manager.wrap_dek(dek)
        recovered = encryption_manager.unwrap_dek(nonce, wrapped)
        assert recovered == dek

    def test_unwrap_wrong_key_raises(self, mock_key_manager):
        """Unwrapping with a different master key must fail."""
        key_id_a = mock_key_manager.generate_master_key("profile-a")
        key_id_b = mock_key_manager.generate_master_key("profile-b")

        em_a = EncryptionManager(mock_key_manager, key_id_a)
        em_b = EncryptionManager(mock_key_manager, key_id_b)

        dek = em_a.generate_dek()
        nonce, wrapped = em_a.wrap_dek(dek)

        with pytest.raises(InvalidTag):
            em_b.unwrap_dek(nonce, wrapped)

    def test_wrap_binds_to_key_id(self, mock_key_manager):
        """Associated data includes key_id — same master key bytes but
        different key_id must fail unwrap."""
        # Store the same raw key under two different IDs
        raw_key = os.urandom(32)
        mock_key_manager._keys["id-alpha"] = raw_key
        mock_key_manager._keys["id-beta"] = raw_key

        em_alpha = EncryptionManager(mock_key_manager, "id-alpha")
        em_beta = EncryptionManager(mock_key_manager, "id-beta")

        dek = em_alpha.generate_dek()
        nonce, wrapped = em_alpha.wrap_dek(dek)

        # Same key bytes, but different associated data → must fail
        with pytest.raises(InvalidTag):
            em_beta.unwrap_dek(nonce, wrapped)


# ---------------------------------------------------------------------------
# File encrypt / decrypt
# ---------------------------------------------------------------------------

class TestFileEncryptDecrypt:
    def test_roundtrip(self, encryption_manager, sample_file, temp_dir):
        dek = encryption_manager.generate_dek()

        enc_path = temp_dir / "sample.fastq.enc"
        dec_path = temp_dir / "sample.fastq"

        meta = encryption_manager.encrypt_file(sample_file, enc_path, dek)
        encryption_manager.decrypt_file(enc_path, dec_path, dek)

        assert dec_path.read_bytes() == sample_file.read_bytes()
        assert meta["original_size"] == sample_file.stat().st_size

    def test_encrypted_file_format(self, encryption_manager, sample_file, temp_dir):
        """Output format: [12-byte nonce][ciphertext][16-byte tag]."""
        dek = encryption_manager.generate_dek()
        enc_path = temp_dir / "sample.fastq.enc"
        encryption_manager.encrypt_file(sample_file, enc_path, dek)

        encrypted = enc_path.read_bytes()
        plaintext_len = sample_file.stat().st_size
        # nonce(12) + ciphertext(same as plaintext) + tag(16)
        assert len(encrypted) == 12 + plaintext_len + 16

    def test_is_nondeterministic(self, encryption_manager, sample_file, temp_dir):
        dek = encryption_manager.generate_dek()
        enc_a = temp_dir / "a.enc"
        enc_b = temp_dir / "b.enc"
        encryption_manager.encrypt_file(sample_file, enc_a, dek)
        encryption_manager.encrypt_file(sample_file, enc_b, dek)
        assert enc_a.read_bytes() != enc_b.read_bytes()

    def test_tampered_ciphertext_fails(self, encryption_manager, sample_file, temp_dir):
        dek = encryption_manager.generate_dek()
        enc_path = temp_dir / "sample.fastq.enc"
        dec_path = temp_dir / "sample.fastq"

        encryption_manager.encrypt_file(sample_file, enc_path, dek)

        # Flip a bit in the ciphertext (after the 12-byte nonce)
        data = bytearray(enc_path.read_bytes())
        data[20] ^= 0xFF
        enc_path.write_bytes(bytes(data))

        with pytest.raises(InvalidTag):
            encryption_manager.decrypt_file(enc_path, dec_path, dek)

    def test_wrong_dek_fails(self, encryption_manager, sample_file, temp_dir):
        dek1 = encryption_manager.generate_dek()
        dek2 = encryption_manager.generate_dek()

        enc_path = temp_dir / "sample.fastq.enc"
        dec_path = temp_dir / "sample.fastq"

        encryption_manager.encrypt_file(sample_file, enc_path, dek1)

        with pytest.raises(InvalidTag):
            encryption_manager.decrypt_file(enc_path, dec_path, dek2)

    def test_checksum_verification(self, encryption_manager, sample_file, temp_dir):
        dek = encryption_manager.generate_dek()
        enc_path = temp_dir / "sample.fastq.enc"
        dec_path = temp_dir / "sample.fastq"

        encryption_manager.encrypt_file(sample_file, enc_path, dek)

        with pytest.raises(ValueError, match="Checksum mismatch"):
            encryption_manager.decrypt_file(
                enc_path, dec_path, dek, expected_checksum="0" * 64
            )

    def test_associated_data_filename_binding(self, encryption_manager, sample_file, temp_dir):
        """encrypt_file uses input_path.name as AD; decrypt_file uses output_path.name.
        When filenames match (standard round-trip) it works. When they differ, it fails."""
        dek = encryption_manager.generate_dek()
        enc_path = temp_dir / "sample.fastq.enc"

        encryption_manager.encrypt_file(sample_file, enc_path, dek)

        # Decrypt to a file with a *different* name → different associated data → InvalidTag
        wrong_name = temp_dir / "wrong_name.txt"
        with pytest.raises(InvalidTag):
            encryption_manager.decrypt_file(enc_path, wrong_name, dek)
