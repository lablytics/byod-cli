"""Tests for EncryptionManager encrypt_path/decrypt_path and _collect_files.

Covers directory encryption, manifest generation, decryption with manifest,
file collection with include/exclude patterns.
"""

import json

import pytest

# ---------------------------------------------------------------------------
# encrypt_path
# ---------------------------------------------------------------------------

class TestEncryptPath:
    def test_single_file(self, encryption_manager, temp_dir):
        """encrypt_path on a single file should encrypt it and produce manifest."""
        plaintext = b"ATCGATCG\n" * 100
        input_file = temp_dir / "sample.fastq"
        input_file.write_bytes(plaintext)

        output_dir = temp_dir / "encrypted"
        result = encryption_manager.encrypt_path(input_file, output_dir)

        assert result["files_encrypted"] == 1
        assert result["total_size_mb"] > 0
        assert (output_dir / "encryption-manifest.json").exists()
        assert (output_dir / "sample.fastq.enc").exists()

    def test_directory_multiple_files(self, encryption_manager, temp_dir):
        """encrypt_path on a directory should encrypt all files."""
        input_dir = temp_dir / "data"
        input_dir.mkdir()
        for i in range(3):
            (input_dir / f"file_{i}.txt").write_text(f"content {i}")

        output_dir = temp_dir / "encrypted"
        result = encryption_manager.encrypt_path(input_dir, output_dir)

        assert result["files_encrypted"] == 3
        manifest = json.loads((output_dir / "encryption-manifest.json").read_text())
        assert manifest["total_files"] == 3
        assert manifest["encryption_algorithm"] == "AES-256-GCM"

    def test_manifest_structure(self, encryption_manager, temp_dir):
        """Manifest should contain all required fields."""
        input_file = temp_dir / "test.txt"
        input_file.write_text("hello world")

        output_dir = temp_dir / "encrypted"
        encryption_manager.encrypt_path(input_file, output_dir)

        manifest = json.loads((output_dir / "encryption-manifest.json").read_text())
        assert "version" in manifest
        assert "dek_nonce" in manifest
        assert "wrapped_dek" in manifest
        assert "timestamp" in manifest
        assert "files" in manifest
        assert manifest["files"][0]["original_name"] == "test.txt"
        assert "checksum" in manifest["files"][0]

    def test_preserve_structure(self, encryption_manager, temp_dir):
        """preserve_structure=True should maintain directory hierarchy."""
        input_dir = temp_dir / "data"
        sub = input_dir / "subdir"
        sub.mkdir(parents=True)
        (sub / "nested.txt").write_text("nested content")
        (input_dir / "top.txt").write_text("top content")

        output_dir = temp_dir / "encrypted"
        result = encryption_manager.encrypt_path(
            input_dir, output_dir, preserve_structure=True
        )

        assert result["files_encrypted"] == 2
        assert (output_dir / "subdir" / "nested.txt.enc").exists()
        assert (output_dir / "top.txt.enc").exists()

    def test_empty_directory_raises(self, encryption_manager, temp_dir):
        """encrypt_path on an empty directory should raise ValueError."""
        empty_dir = temp_dir / "empty"
        empty_dir.mkdir()
        output_dir = temp_dir / "encrypted"

        with pytest.raises(ValueError, match="No files found"):
            encryption_manager.encrypt_path(empty_dir, output_dir)


# ---------------------------------------------------------------------------
# decrypt_path
# ---------------------------------------------------------------------------

class TestDecryptPath:
    def test_roundtrip_single_file(self, encryption_manager, temp_dir):
        """encrypt_path then decrypt_path should recover original content."""
        original = b"sensitive genomic data\n" * 50
        input_file = temp_dir / "sample.fastq"
        input_file.write_bytes(original)

        enc_dir = temp_dir / "encrypted"
        encryption_manager.encrypt_path(input_file, enc_dir)

        dec_dir = temp_dir / "decrypted"
        result = encryption_manager.decrypt_path(enc_dir, dec_dir)

        assert result["files_decrypted"] == 1
        assert (dec_dir / "sample.fastq").read_bytes() == original

    def test_roundtrip_multiple_files(self, encryption_manager, temp_dir):
        """Roundtrip with multiple files should recover all content."""
        input_dir = temp_dir / "data"
        input_dir.mkdir()
        originals = {}
        for i in range(3):
            content = f"content for file {i}\n" * 20
            (input_dir / f"file_{i}.txt").write_text(content)
            originals[f"file_{i}.txt"] = content

        enc_dir = temp_dir / "encrypted"
        encryption_manager.encrypt_path(input_dir, enc_dir)

        dec_dir = temp_dir / "decrypted"
        result = encryption_manager.decrypt_path(enc_dir, dec_dir)

        assert result["files_decrypted"] == 3
        for name, content in originals.items():
            assert (dec_dir / name).read_text() == content

    def test_missing_manifest_raises(self, encryption_manager, temp_dir):
        """decrypt_path without manifest should raise FileNotFoundError."""
        empty_dir = temp_dir / "no_manifest"
        empty_dir.mkdir()

        with pytest.raises(FileNotFoundError, match="manifest"):
            encryption_manager.decrypt_path(empty_dir, temp_dir / "out")

    def test_verify_checksum(self, encryption_manager, temp_dir):
        """decrypt_path with verify=True should catch corrupted files."""
        input_file = temp_dir / "data.txt"
        input_file.write_text("original data")

        enc_dir = temp_dir / "encrypted"
        encryption_manager.encrypt_path(input_file, enc_dir)

        # Corrupt the manifest checksum
        manifest_path = enc_dir / "encryption-manifest.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["files"][0]["checksum"] = "0" * 64
        manifest_path.write_text(json.dumps(manifest))

        dec_dir = temp_dir / "decrypted"
        with pytest.raises(ValueError, match="[Cc]hecksum"):
            encryption_manager.decrypt_path(enc_dir, dec_dir, verify=True)

    def test_skip_verify(self, encryption_manager, temp_dir):
        """decrypt_path with verify=False should not check checksums."""
        input_file = temp_dir / "data.txt"
        input_file.write_text("original data")

        enc_dir = temp_dir / "encrypted"
        encryption_manager.encrypt_path(input_file, enc_dir)

        # Corrupt the manifest checksum
        manifest_path = enc_dir / "encryption-manifest.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["files"][0]["checksum"] = "0" * 64
        manifest_path.write_text(json.dumps(manifest))

        dec_dir = temp_dir / "decrypted"
        result = encryption_manager.decrypt_path(enc_dir, dec_dir, verify=False)
        assert result["files_decrypted"] == 1


# ---------------------------------------------------------------------------
# _collect_files
# ---------------------------------------------------------------------------

class TestCollectFiles:
    def _make_tree(self, temp_dir):
        """Create a directory tree for testing."""
        d = temp_dir / "tree"
        d.mkdir()
        (d / "a.txt").write_text("a")
        (d / "b.fastq").write_text("b")
        (d / "c.fastq.gz").write_text("c")
        sub = d / "sub"
        sub.mkdir()
        (sub / "d.txt").write_text("d")
        (sub / "e.log").write_text("e")
        return d

    def test_collects_all_files(self, encryption_manager, temp_dir):
        d = self._make_tree(temp_dir)
        files = encryption_manager._collect_files(d, None, None)
        assert len(files) == 5

    def test_include_pattern(self, encryption_manager, temp_dir):
        d = self._make_tree(temp_dir)
        files = encryption_manager._collect_files(d, None, ["*.fastq"])
        names = [f.name for f in files]
        assert names == ["b.fastq"]

    def test_exclude_pattern(self, encryption_manager, temp_dir):
        d = self._make_tree(temp_dir)
        files = encryption_manager._collect_files(d, ["*.log"], None)
        names = {f.name for f in files}
        assert "e.log" not in names
        assert len(files) == 4

    def test_include_and_exclude(self, encryption_manager, temp_dir):
        d = self._make_tree(temp_dir)
        files = encryption_manager._collect_files(d, ["*.gz"], ["*.fastq*"])
        # Include *.fastq* captures b.fastq and c.fastq.gz, exclude *.gz removes c.fastq.gz
        names = [f.name for f in files]
        assert "b.fastq" in names
        assert "c.fastq.gz" not in names

    def test_returns_sorted_unique(self, encryption_manager, temp_dir):
        d = self._make_tree(temp_dir)
        files = encryption_manager._collect_files(d, None, None)
        assert files == sorted(set(files))
