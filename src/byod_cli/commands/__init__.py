"""
BYOD CLI command modules.

Each module contains a focused set of related commands:
- auth: Authentication (login, logout, status)
- setup: AWS resource management (setup, update-policy, teardown)
- jobs: Job lifecycle (submit, status, list, retrieve, decrypt, get)
- plugins: Plugin listing
- config: Configuration and profile management
- misc: Shell completion, local UI
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import click

_cli_group = None


def get_cli_group():
    """Get the CLI group reference (used by shell completion)."""
    return _cli_group


def register_commands(cli: click.Group) -> None:
    """Register all command modules with the CLI group."""
    global _cli_group
    _cli_group = cli

    from byod_cli.commands.auth import auth
    from byod_cli.commands.config import config, profile
    from byod_cli.commands.jobs import decrypt, get, list_jobs, retrieve, status, submit
    from byod_cli.commands.misc import completion, ui
    from byod_cli.commands.plugins import plugins
    from byod_cli.commands.setup import setup, teardown, update_policy

    cli.add_command(auth)
    cli.add_command(setup)
    cli.add_command(update_policy)
    cli.add_command(teardown)
    cli.add_command(submit)
    cli.add_command(status)
    cli.add_command(list_jobs)
    cli.add_command(retrieve)
    cli.add_command(decrypt)
    cli.add_command(get)
    cli.add_command(plugins)
    cli.add_command(config)
    cli.add_command(profile)
    cli.add_command(completion)
    cli.add_command(ui)
