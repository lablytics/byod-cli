"""Shared test fixtures for BYOD CLI tests."""

import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

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


# ---------------------------------------------------------------------------
# UI Route Testing Fixtures
# ---------------------------------------------------------------------------


def _make_mock_config(
    authenticated=False,
    api_url="http://localhost:8000",
    api_key=None,
    active_profile="default",
    profile_settings=None,
):
    """Build a MagicMock ConfigManager with configurable state."""
    config = MagicMock()
    config.is_authenticated.return_value = authenticated
    config.get_api_url.return_value = api_url
    config.get_api_key.return_value = api_key
    config.get_active_profile_name.return_value = active_profile

    settings = profile_settings or {}
    profile_data = {"settings": settings}

    config.profile_exists.return_value = True
    config.get_profile.return_value = profile_data
    config.get_active_profile_config.return_value = profile_data
    config.list_profiles.return_value = [active_profile]
    config.config_file = Path("/tmp/byod/config.yaml")
    return config


@pytest.fixture
def mock_config():
    """A mock ConfigManager that is unauthenticated by default."""
    return _make_mock_config()


@pytest.fixture
def mock_config_authed():
    """A mock ConfigManager that is authenticated with an API key."""
    return _make_mock_config(
        authenticated=True,
        api_key="test-api-key-123",
        profile_settings={
            "kms_key_arn": "arn:aws:kms:us-east-1:123456789:key/test-key-id",
            "role_arn": "arn:aws:iam::123456789:role/BYODEnclaveRole-test",
            "region": "us-east-1",
        },
    )


def _create_test_app(mock_cfg):
    """Create a FastAPI app with mocked config for testing.

    Sets app.state.config directly (no lifespan) so TestClient can access it.
    """
    from fastapi import FastAPI

    from byod_cli.ui.routes import jobs, plugins, settings, setup, status, submit

    app = FastAPI()
    app.state.config = mock_cfg
    app.include_router(status.router, prefix="/api")
    app.include_router(jobs.router, prefix="/api")
    app.include_router(plugins.router, prefix="/api")
    app.include_router(submit.router, prefix="/api")
    app.include_router(setup.router, prefix="/api")
    app.include_router(settings.router, prefix="/api")
    return app


@pytest.fixture
def ui_client(mock_config):
    """TestClient for unauthenticated UI testing."""
    app = _create_test_app(mock_config)
    return TestClient(app)


@pytest.fixture
def ui_client_authed(mock_config_authed):
    """TestClient for authenticated UI testing."""
    app = _create_test_app(mock_config_authed)
    return TestClient(app)
