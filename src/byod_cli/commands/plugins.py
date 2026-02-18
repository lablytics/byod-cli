"""
Plugin commands for BYOD CLI.

Contains: plugins — list available pipeline plugins.
"""

from __future__ import annotations

import json
import sys

import click
from rich.table import Table

from byod_cli.api_client import APIError
from byod_cli.commands import _helpers

EXIT_ERROR = _helpers.EXIT_ERROR


@click.command()
@click.option("--format", "output_format", type=click.Choice(["text", "json"]), default="text")
@click.pass_context
def plugins(ctx: click.Context, output_format: str) -> None:
    """
    List available pipeline plugins.

    \b
    Examples:
        byod plugins
        byod plugins --format json
    """
    config = ctx.obj["CONFIG"]
    client = _helpers._get_api_client(config)
    console = _helpers.console

    try:
        with console.status("[bold green]Fetching plugins..."):
            plugin_list = client.list_plugins()

        if output_format == "json":
            click.echo(json.dumps(plugin_list))
            return

        if not plugin_list:
            console.print("\nNo plugins available.\n")
            return

        table = Table(title="Available Plugins")
        table.add_column("Name", style="cyan")
        table.add_column("Description")
        table.add_column("Version", style="dim")

        for p in plugin_list:
            table.add_row(p.get("name", "?"), p.get("description", ""), p.get("version", ""))

        console.print(table)

    except APIError as e:
        console.print(_helpers.format_error(f"Failed to list plugins: {e}"))
        sys.exit(EXIT_ERROR)
