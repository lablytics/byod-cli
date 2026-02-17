"""
BYOD CLI Main Entry Point

This module defines the top-level CLI group and entry point.
All commands are registered from the commands/ package.

Security Note:
All encryption operations happen client-side. Keys are never transmitted to the platform.
Lablytics manages all S3 buckets and provides presigned URLs for secure upload/download.
"""

from __future__ import annotations

import sys

import click

from byod_cli import __version__
from byod_cli.commands._helpers import EXIT_ERROR, init_console
from byod_cli.utils import format_error, setup_logging


@click.group()
@click.version_option(version=__version__, prog_name="byod")
@click.option("--debug", is_flag=True, help="Enable debug logging", envvar="BYOD_DEBUG")
@click.option("--quiet", "-q", is_flag=True, help="Suppress progress output (for CI/CD)")
@click.option("--no-color", is_flag=True, help="Disable colored output", envvar="NO_COLOR")
@click.pass_context
def cli(ctx: click.Context, debug: bool, quiet: bool, no_color: bool) -> None:
    """
    BYOD - Bring Your Own Data Platform CLI

    Secure biotech data processing with zero-knowledge encryption.
    Your data stays encrypted except during processing in an attested Nitro Enclave.

    \b
    Quick Start:
        1. Authenticate: byod auth login
        2. Submit:       byod submit genomic-qc ./data.fastq
        3. Status:       byod status <job-id>
        4. Get results:  byod get <job-id> -o ./output/

    For detailed help on any command: byod COMMAND --help
    """
    # Initialize shared console with user preferences
    init_console(quiet=quiet, no_color=no_color)

    log_level = "DEBUG" if debug else "INFO"
    setup_logging(log_level)

    ctx.ensure_object(dict)
    ctx.obj["DEBUG"] = debug
    ctx.obj["QUIET"] = quiet
    ctx.obj["NO_COLOR"] = no_color

    try:
        from byod_cli.config import ConfigManager
        config_manager = ConfigManager()
        ctx.obj["CONFIG"] = config_manager
    except Exception as e:
        if ctx.invoked_subcommand not in ["auth"]:
            from byod_cli.commands._helpers import console
            console.print(format_error(f"Configuration error: {e}"))
            sys.exit(EXIT_ERROR)


# Register all commands from the commands/ package
from byod_cli.commands import register_commands  # noqa: E402

register_commands(cli)


def main() -> None:
    """Main entry point for the CLI."""
    try:
        cli(obj={})
    except KeyboardInterrupt:
        from byod_cli.commands._helpers import console
        console.print("\n[yellow]Interrupted by user[/yellow]")
        sys.exit(130)
    except Exception as e:
        from byod_cli.commands._helpers import console
        console.print(format_error(f"Unexpected error: {e}"))
        sys.exit(EXIT_ERROR)


if __name__ == "__main__":
    main()
