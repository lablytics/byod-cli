"""
Shared helpers for BYOD CLI commands.

This module contains constants, utility functions, and the shared console
instance used across all command modules.
"""

from __future__ import annotations

import os

import click
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from rich.console import Console
from rich.table import Table

from byod_cli.api_client import APIClient
from byod_cli.config import ConfigManager
from byod_cli.utils import (
    format_bytes,  # noqa: F401 — re-exported, accessed via _helpers.format_bytes
    format_error,  # noqa: F401 — re-exported, accessed via _helpers.format_error
    format_success,  # noqa: F401 — re-exported, accessed via _helpers.format_success
    format_warning,  # noqa: F401 — re-exported, accessed via _helpers.format_warning
    get_console,
)

console = Console()

BANNER = """
[bold blue]
 ____  __   __ ___  ____
| __ )\\ \\ / // _ \\|  _ \\
|  _ \\ \\ V /| | | | | | |
| |_) | | | | |_| | |_| |
|____/  |_|  \\___/|____/
[/bold blue]
[dim]Lablytics Secure Data Processing Platform[/dim]
"""

NONCE_SIZE = 12

# Exit codes
EXIT_OK = 0
EXIT_ERROR = 1
EXIT_AUTH = 2
EXIT_NETWORK = 3
EXIT_NOT_FOUND = 4


def init_console(quiet: bool = False, no_color: bool = False) -> None:
    """Update the shared console instance with user preferences."""
    global console
    console = get_console(quiet=quiet, no_color=no_color)


def _get_api_client(config: ConfigManager) -> APIClient:
    """Create an authenticated API client."""
    api_key = config.get_api_key()
    if not api_key:
        raise click.ClickException(
            "Not authenticated. Run 'byod auth login' with your API key from https://byod.cultivatedcode.co"
        )
    return APIClient(api_url=config.get_api_url(), api_key=api_key)


def _encrypt_data(plaintext: bytes, key: bytes) -> bytes:
    """Encrypt data with AES-256-GCM. Format: [nonce][ciphertext+tag]"""
    nonce = os.urandom(NONCE_SIZE)
    aesgcm = AESGCM(key)
    ciphertext = aesgcm.encrypt(nonce, plaintext, None)
    return nonce + ciphertext


def _decrypt_data(encrypted: bytes, key: bytes) -> bytes:
    """Decrypt data with AES-256-GCM."""
    nonce = encrypted[:NONCE_SIZE]
    ciphertext = encrypted[NONCE_SIZE:]
    aesgcm = AESGCM(key)
    return aesgcm.decrypt(nonce, ciphertext, None)


def _print_status(status_info: dict) -> None:
    """Pretty-print job status information."""
    table = Table(title="Job Status")
    table.add_column("Field", style="cyan")
    table.add_column("Value", style="green")

    job_status = status_info.get("status", "unknown")
    status_styled = {
        "completed": "[bold green]completed[/bold green]",
        "processing": "[bold yellow]processing[/bold yellow]",
        "submitted": "[bold blue]submitted[/bold blue]",
        "failed": "[bold red]failed[/bold red]",
        "cancelled": "[dim]cancelled[/dim]",
    }.get(job_status, job_status)

    table.add_row("Job ID", status_info.get("job_id", "N/A"))
    table.add_row("Status", status_styled)

    if "plugin_name" in status_info:
        table.add_row("Plugin", status_info["plugin_name"])
    if "created_at" in status_info:
        table.add_row("Submitted", status_info["created_at"])
    if "completed_at" in status_info:
        table.add_row("Completed", status_info["completed_at"])
    if "description" in status_info and status_info["description"]:
        table.add_row("Description", status_info["description"])
    if "error" in status_info and status_info["error"]:
        table.add_row("Error", f"[red]{status_info['error']}[/red]")

    console.print(table)

    if job_status == "completed":
        console.print(f"\nGet results: [cyan]byod get {status_info['job_id']} -o ./output/[/cyan]")
