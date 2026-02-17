"""
Config and profile commands for BYOD CLI.

Contains: config group (show) and profile group (list, switch, delete, show).
"""

from __future__ import annotations

import sys

import click
from rich.table import Table

from byod_cli.commands import _helpers

EXIT_ERROR = _helpers.EXIT_ERROR


@click.group()
def config() -> None:
    """Manage configuration."""
    pass


@config.command(name="show")
@click.pass_context
def config_show(ctx: click.Context) -> None:
    """
    Display current configuration.

    \b
    Examples:
        byod config show
    """
    config_mgr = ctx.obj["CONFIG"]
    console = _helpers.console

    table = Table(title="BYOD Configuration")
    table.add_column("Setting", style="cyan")
    table.add_column("Value", style="green")

    table.add_row("Config file", str(config_mgr.config_file))
    table.add_row("API URL", config_mgr.get_api_url())
    table.add_row("Authenticated", "[green]Yes[/green]" if config_mgr.is_authenticated() else "[red]No[/red]")

    profiles = config_mgr.list_profiles()
    if profiles:
        active = config_mgr.get_active_profile_name()
        for name in profiles:
            p = config_mgr.get_profile(name)
            is_active = " [bold green](active)[/bold green]" if name == active else ""
            table.add_row(f"Profile: {name}{is_active}", p.get("organization_name", ""))

    console.print(table)


@click.group()
def profile() -> None:
    """Manage profiles for multiple tenants."""
    pass


@profile.command(name="list")
@click.pass_context
def profile_list(ctx: click.Context) -> None:
    """List all profiles."""
    config_mgr = ctx.obj["CONFIG"]
    console = _helpers.console
    profiles = config_mgr.list_profiles()

    if not profiles:
        console.print("\nNo profiles configured.")
        console.print("Run [cyan]byod auth login[/cyan] to create one.\n")
        return

    active = config_mgr.get_active_profile_name()
    table = Table(title="Profiles")
    table.add_column("Name", style="cyan")
    table.add_column("Organization")
    table.add_column("Region", style="dim")
    table.add_column("Active", style="green")

    for name in profiles:
        p = config_mgr.get_profile(name)
        table.add_row(
            name, p.get("organization_name", ""),
            p.get("region", ""), "✓" if name == active else "",
        )

    console.print(table)


@profile.command(name="switch")
@click.argument("name")
@click.pass_context
def profile_switch(ctx: click.Context, name: str) -> None:
    """Switch the active profile."""
    config_mgr = ctx.obj["CONFIG"]
    console = _helpers.console
    try:
        config_mgr.set_active_profile(name)
        console.print(_helpers.format_success(f"Switched to profile '{name}'."))
    except ValueError as e:
        console.print(_helpers.format_error(str(e)))
        console.print("\nAvailable profiles:")
        for p in config_mgr.list_profiles():
            console.print(f"  - {p}")
        sys.exit(EXIT_ERROR)


@profile.command(name="delete")
@click.argument("name")
@click.pass_context
def profile_delete(ctx: click.Context, name: str) -> None:
    """Delete a profile."""
    config_mgr = ctx.obj["CONFIG"]
    console = _helpers.console
    try:
        config_mgr.delete_profile(name)
        console.print(_helpers.format_success(f"Deleted profile '{name}'."))
    except ValueError as e:
        console.print(_helpers.format_error(str(e)))
        sys.exit(EXIT_ERROR)


@profile.command(name="show")
@click.pass_context
def profile_show(ctx: click.Context) -> None:
    """Show current profile details."""
    config_mgr = ctx.obj["CONFIG"]
    console = _helpers.console
    active = config_mgr.get_active_profile_name()

    if not active:
        console.print("\nNo active profile.")
        console.print("Run [cyan]byod auth login[/cyan] to create one.\n")
        return

    p = config_mgr.get_profile(active)
    table = Table(title=f"Profile: {active}")
    table.add_column("Setting", style="cyan")
    table.add_column("Value", style="green")

    table.add_row("Tenant ID", p.get("tenant_id", ""))
    table.add_row("Organization", p.get("organization_name", ""))
    table.add_row("Region", p.get("region", ""))
    table.add_row("Created", p.get("created_at", ""))

    settings = p.get("settings", {})
    if settings.get("kms_key_arn"):
        table.add_row("KMS Key", settings["kms_key_arn"])
    if settings.get("role_arn"):
        table.add_row("IAM Role", settings["role_arn"])

    console.print(table)
