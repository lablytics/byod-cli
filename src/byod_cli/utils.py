"""
Utility Functions for BYOD CLI

Common utilities for logging, formatting, and error handling.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from rich.console import Console
from rich.logging import RichHandler

if TYPE_CHECKING:
    pass

console = Console()


def setup_logging(level: str = "INFO") -> None:
    """
    Configure logging with rich handler.

    Args:
        level: Log level (DEBUG, INFO, WARNING, ERROR)
    """
    logging.basicConfig(
        level=level,
        format="%(message)s",
        datefmt="[%X]",
        handlers=[RichHandler(console=console, rich_tracebacks=True)],
    )


def format_error(message: str) -> str:
    """Format an error message with styling."""
    return f"[bold red]Error:[/bold red] {message}"


def format_success(message: str) -> str:
    """Format a success message with styling."""
    return f"[bold green]OK:[/bold green] {message}"


def format_warning(message: str) -> str:
    """Format a warning message with styling."""
    return f"[bold yellow]Warning:[/bold yellow] {message}"


def format_info(message: str) -> str:
    """Format an info message with styling."""
    return f"[bold blue]Info:[/bold blue] {message}"


def confirm_action(prompt: str, default: bool = False) -> bool:
    """
    Ask user for confirmation.

    Args:
        prompt: Prompt message
        default: Default value if user just presses Enter

    Returns:
        True if confirmed, False otherwise
    """
    from rich.prompt import Confirm

    return Confirm.ask(prompt, default=default)


def format_bytes(size_bytes: int) -> str:
    """
    Format bytes to human-readable string.

    Args:
        size_bytes: Size in bytes

    Returns:
        Formatted string (e.g., "1.5 MB")
    """
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if size_bytes < 1024.0:
            return f"{size_bytes:.2f} {unit}"
        size_bytes /= 1024.0
    return f"{size_bytes:.2f} PB"


def format_duration(seconds: float) -> str:
    """
    Format duration to human-readable string.

    Args:
        seconds: Duration in seconds

    Returns:
        Formatted string (e.g., "2m 30s")
    """
    if seconds < 60:
        return f"{seconds:.1f}s"
    elif seconds < 3600:
        minutes = int(seconds // 60)
        secs = int(seconds % 60)
        return f"{minutes}m {secs}s"
    else:
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        return f"{hours}h {minutes}m"
