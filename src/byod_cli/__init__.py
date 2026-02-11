"""
BYOD CLI - Lablytics Secure Data Processing Platform

A command-line interface for submitting encrypted biotech data
to Nitro Enclave-based processing pipelines with zero-knowledge guarantees.
"""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("byod-cli")
except PackageNotFoundError:
    __version__ = "0.0.0-dev"

__author__ = "Lablytics"

from byod_cli.api_client import APIClient, APIError, AuthenticationError
from byod_cli.config import ConfigManager
from byod_cli.encryption import EncryptionManager
from byod_cli.key_manager import KeyManager
from byod_cli.s3_client import S3Client

__all__ = [
    "APIClient",
    "APIError",
    "AuthenticationError",
    "ConfigManager",
    "EncryptionManager",
    "KeyManager",
    "S3Client",
    "__version__",
]
