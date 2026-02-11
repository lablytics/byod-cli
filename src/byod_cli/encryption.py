"""
Encryption Module for BYOD CLI

This module handles all client-side encryption operations using AES-256-GCM.
Data is encrypted before transmission and keys never leave the client.

Security Design:
----------------
1. Each dataset gets a unique Data Encryption Key (DEK)
2. DEK is randomly generated using os.urandom()
3. Data is encrypted with AES-256-GCM (authenticated encryption)
4. DEK is wrapped (encrypted) with customer's master key
5. Only the wrapped DEK is uploaded to the platform
6. Enclave must prove its identity before platform provides wrapped DEK
7. Only genuine Nitro Enclave can unwrap DEK using KMS

Key Hierarchy:
--------------
Customer Master Key (CMK)
  |
  +-> Data Encryption Key (DEK) [unique per dataset]
       |
       +-> File 1, File 2, File 3, ... [all encrypted with same DEK]

This allows efficient key management while maintaining security:
- CMK rotations don't require re-encrypting all data
- DEKs can be revoked per-dataset
- Multiple files in a dataset share the same DEK for efficiency
"""

from __future__ import annotations

import fnmatch
import hashlib
import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from tqdm import tqdm

if TYPE_CHECKING:
    from byod_cli.key_manager import KeyManager

logger = logging.getLogger(__name__)


class EncryptionManager:
    """
    Manages encryption and decryption operations for BYOD CLI.

    Provides client-side encryption using AES-256-GCM with authenticated
    encryption. Generates unique DEKs for each dataset and wraps them
    with the customer's master key.
    """

    # Encryption constants
    AES_KEY_SIZE = 32  # 256 bits
    NONCE_SIZE = 12  # 96 bits (recommended for GCM)
    TAG_SIZE = 16  # 128 bits authentication tag
    CHUNK_SIZE_BYTES = 64 * 1024 * 1024  # 64 MB default chunk size

    def __init__(self, key_manager: KeyManager, master_key_id: str) -> None:
        """
        Initialize encryption manager.

        Args:
            key_manager: KeyManager instance for master key operations
            master_key_id: Identifier for the master key to use
        """
        self.key_manager = key_manager
        self.master_key_id = master_key_id
        self.master_key = key_manager.get_master_key(master_key_id)

    def generate_dek(self) -> bytes:
        """
        Generate a new Data Encryption Key (DEK).

        Returns:
            32-byte (256-bit) random key suitable for AES-256
        """
        return os.urandom(self.AES_KEY_SIZE)

    def wrap_dek(self, dek: bytes) -> tuple[bytes, bytes]:
        """
        Wrap (encrypt) a DEK with the master key.

        This creates an encrypted version of the DEK that can be safely
        stored or transmitted. Only someone with the master key can unwrap it.

        Args:
            dek: Data Encryption Key to wrap

        Returns:
            Tuple of (nonce, wrapped_dek_with_tag)
        """
        aesgcm = AESGCM(self.master_key)
        nonce = os.urandom(self.NONCE_SIZE)

        # Encrypt DEK with master key
        # associated_data includes key_id to prevent key substitution attacks
        associated_data = self.master_key_id.encode("utf-8")
        wrapped = aesgcm.encrypt(nonce, dek, associated_data)

        return nonce, wrapped

    def unwrap_dek(self, nonce: bytes, wrapped_dek: bytes) -> bytes:
        """
        Unwrap (decrypt) a wrapped DEK using the master key.

        Args:
            nonce: Nonce used during wrapping
            wrapped_dek: Encrypted DEK with authentication tag

        Returns:
            Original DEK

        Raises:
            InvalidTag: If authentication fails (tampering detected)
        """
        aesgcm = AESGCM(self.master_key)
        associated_data = self.master_key_id.encode("utf-8")
        dek = aesgcm.decrypt(nonce, wrapped_dek, associated_data)
        return dek

    def encrypt_file(
        self,
        input_path: Path,
        output_path: Path,
        dek: bytes,
        chunk_size_bytes: int | None = None,
    ) -> dict[str, Any]:
        """
        Encrypt a single file with the provided DEK.

        Args:
            input_path: Path to plaintext file
            output_path: Path for encrypted output
            dek: Data Encryption Key to use
            chunk_size_bytes: Size of chunks for large file processing

        Returns:
            Dict with encryption metadata
        """
        chunk_size = chunk_size_bytes or self.CHUNK_SIZE_BYTES

        # Calculate hash of plaintext for integrity verification
        sha256 = hashlib.sha256()
        original_size = 0

        with open(input_path, "rb") as f:
            while True:
                chunk = f.read(chunk_size)
                if not chunk:
                    break
                sha256.update(chunk)
                original_size += len(chunk)

        plaintext_checksum = sha256.hexdigest()

        # Read and encrypt the file
        with open(input_path, "rb") as f_in:
            plaintext = f_in.read()

        aesgcm = AESGCM(dek)
        nonce = os.urandom(self.NONCE_SIZE)

        # Associated data includes filename to prevent file substitution
        associated_data = input_path.name.encode("utf-8")
        ciphertext_with_tag = aesgcm.encrypt(nonce, plaintext, associated_data)

        # Write encrypted output
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "wb") as f_out:
            f_out.write(nonce)  # Prepend nonce for later decryption
            f_out.write(ciphertext_with_tag)

        encrypted_size = output_path.stat().st_size

        return {
            "original_size": original_size,
            "encrypted_size": encrypted_size,
            "checksum": plaintext_checksum,
            "nonce": nonce.hex(),
        }

    def decrypt_file(
        self,
        input_path: Path,
        output_path: Path,
        dek: bytes,
        expected_checksum: str | None = None,
    ) -> dict[str, Any]:
        """
        Decrypt a single file with the provided DEK.

        Args:
            input_path: Path to encrypted file
            output_path: Path for decrypted output
            dek: Data Encryption Key
            expected_checksum: Optional SHA-256 hash to verify against

        Returns:
            Dict with decryption metadata

        Raises:
            InvalidTag: If authentication fails (tampering detected)
            ValueError: If checksum verification fails
        """
        with open(input_path, "rb") as f_in:
            nonce = f_in.read(self.NONCE_SIZE)
            ciphertext_with_tag = f_in.read()

        aesgcm = AESGCM(dek)
        associated_data = output_path.name.encode("utf-8")
        plaintext = aesgcm.decrypt(nonce, ciphertext_with_tag, associated_data)

        if expected_checksum:
            actual_checksum = hashlib.sha256(plaintext).hexdigest()
            if actual_checksum != expected_checksum:
                raise ValueError(
                    f"Checksum mismatch! Expected: {expected_checksum}, Got: {actual_checksum}"
                )

        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "wb") as f_out:
            f_out.write(plaintext)

        return {
            "decrypted_size": len(plaintext),
            "checksum": hashlib.sha256(plaintext).hexdigest(),
        }

    def encrypt_path(
        self,
        input_path: Path,
        output_path: Path,
        exclude_patterns: list[str] | None = None,
        include_patterns: list[str] | None = None,
        chunk_size_mb: int = 64,
        preserve_structure: bool = False,
    ) -> dict[str, Any]:
        """
        Encrypt a file or directory with a new DEK.

        Creates an encryption manifest with:
        - Wrapped DEK
        - File metadata
        - Encryption parameters

        Args:
            input_path: Path to file or directory
            output_path: Output directory
            exclude_patterns: Glob patterns to exclude
            include_patterns: Glob patterns to include
            chunk_size_mb: Chunk size for large files
            preserve_structure: Maintain directory structure

        Returns:
            Dict with encryption results
        """
        start_time = datetime.now()

        # Generate new DEK for this dataset
        dek = self.generate_dek()
        dek_nonce, wrapped_dek = self.wrap_dek(dek)

        # Collect files to encrypt
        if input_path.is_file():
            files_to_encrypt = [input_path]
        else:
            files_to_encrypt = self._collect_files(
                input_path, exclude_patterns, include_patterns
            )

        if not files_to_encrypt:
            raise ValueError("No files found to encrypt")

        # Encrypt each file
        output_path.mkdir(parents=True, exist_ok=True)
        encrypted_files: list[dict[str, Any]] = []
        total_size = 0

        with tqdm(total=len(files_to_encrypt), desc="Encrypting") as pbar:
            for file_path in files_to_encrypt:
                if preserve_structure and input_path.is_dir():
                    rel_path = file_path.relative_to(input_path)
                    out_file = output_path / rel_path
                else:
                    out_file = output_path / file_path.name

                out_file = out_file.with_suffix(out_file.suffix + ".enc")

                file_metadata = self.encrypt_file(
                    file_path, out_file, dek, chunk_size_mb * 1024 * 1024
                )

                encrypted_files.append(
                    {
                        "original_name": file_path.name,
                        "original_path": str(file_path),
                        "encrypted_name": out_file.name,
                        "encrypted_path": str(out_file),
                        **file_metadata,
                    }
                )

                total_size += file_metadata["original_size"]
                pbar.update(1)

        # Create encryption manifest
        manifest: dict[str, Any] = {
            "version": "1.0",
            "encryption_algorithm": "AES-256-GCM",
            "key_id": self.master_key_id,
            "dek_nonce": dek_nonce.hex(),
            "wrapped_dek": wrapped_dek.hex(),
            "timestamp": start_time.isoformat(),
            "files": encrypted_files,
            "total_files": len(encrypted_files),
            "total_size_bytes": total_size,
        }

        manifest_path = output_path / "encryption-manifest.json"
        with open(manifest_path, "w") as f:
            json.dump(manifest, f, indent=2)

        duration = (datetime.now() - start_time).total_seconds()

        return {
            "files_encrypted": len(encrypted_files),
            "total_size_mb": total_size / (1024 * 1024),
            "duration_seconds": duration,
            "manifest_path": manifest_path,
        }

    def decrypt_path(
        self,
        encrypted_path: Path,
        output_path: Path,
        verify: bool = True,
    ) -> dict[str, Any]:
        """
        Decrypt a directory using its encryption manifest.

        Args:
            encrypted_path: Path containing encrypted files and manifest
            output_path: Output directory for decrypted files
            verify: Verify checksums after decryption

        Returns:
            Dict with decryption results
        """
        start_time = datetime.now()

        manifest_path = encrypted_path / "encryption-manifest.json"
        if not manifest_path.exists():
            raise FileNotFoundError(f"Encryption manifest not found: {manifest_path}")

        with open(manifest_path) as f:
            manifest = json.load(f)

        # Unwrap DEK
        dek_nonce = bytes.fromhex(manifest["dek_nonce"])
        wrapped_dek = bytes.fromhex(manifest["wrapped_dek"])
        dek = self.unwrap_dek(dek_nonce, wrapped_dek)

        # Decrypt each file
        output_path.mkdir(parents=True, exist_ok=True)
        decrypted_files: list[Path] = []

        with tqdm(total=len(manifest["files"]), desc="Decrypting") as pbar:
            for file_info in manifest["files"]:
                enc_file = Path(file_info["encrypted_path"])
                out_file = output_path / file_info["original_name"]

                expected_checksum = file_info["checksum"] if verify else None
                self.decrypt_file(enc_file, out_file, dek, expected_checksum)

                decrypted_files.append(out_file)
                pbar.update(1)

        duration = (datetime.now() - start_time).total_seconds()

        return {
            "files_decrypted": len(decrypted_files),
            "duration_seconds": duration,
        }

    def _collect_files(
        self,
        directory: Path,
        exclude_patterns: list[str] | None,
        include_patterns: list[str] | None,
    ) -> list[Path]:
        """Collect files from directory applying include/exclude patterns."""
        all_files: list[Path] = []
        for item in directory.rglob("*"):
            if item.is_file():
                all_files.append(item)

        # Apply include patterns if specified
        if include_patterns:
            included_files: list[Path] = []
            for pattern in include_patterns:
                for file_path in all_files:
                    if fnmatch.fnmatch(file_path.name, pattern):
                        included_files.append(file_path)
            all_files = included_files

        # Apply exclude patterns
        if exclude_patterns:
            filtered_files: list[Path] = []
            for file_path in all_files:
                excluded = False
                for pattern in exclude_patterns:
                    if fnmatch.fnmatch(file_path.name, pattern):
                        excluded = True
                        break
                if not excluded:
                    filtered_files.append(file_path)
            all_files = filtered_files

        return sorted(set(all_files))
