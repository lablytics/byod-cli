"""
Miscellaneous commands for BYOD CLI.

Contains: completion, ui.
"""

from __future__ import annotations

import sys

import click

from byod_cli.commands import _helpers

EXIT_ERROR = _helpers.EXIT_ERROR


@click.command()
@click.argument("shell", type=click.Choice(["bash", "zsh", "fish"]))
def completion(shell: str) -> None:
    """Generate shell completion script.

    \b
    Usage:
        eval "$(byod completion bash)"
        eval "$(byod completion zsh)"
        byod completion fish > ~/.config/fish/completions/byod.fish
    """
    shell_map = {
        "bash": ("bash_source", "_BYOD_COMPLETE"),
        "zsh": ("zsh_source", "_BYOD_COMPLETE"),
        "fish": ("fish_source", "_BYOD_COMPLETE"),
    }
    source_func, env_var = shell_map[shell]

    import importlib

    try:
        shell_complete = importlib.import_module("click.shell_completion")
        cls = shell_complete.get_completion_class(shell)
        if cls is None:
            raise click.ClickException(f"Completion not supported for {shell}")
        from byod_cli.commands import get_cli_group
        comp = cls(get_cli_group(), {}, f"{env_var}", "byod")
        click.echo(comp.source())
    except (ImportError, AttributeError):
        click.echo(f"# Set {env_var}={source_func} and source this script")
        click.echo("# See Click docs for shell completion setup")


@click.command()
@click.option("--port", type=int, default=8420, help="Port for local UI server")
@click.option("--host", default="127.0.0.1", help="Host to bind to")
@click.option("--no-browser", is_flag=True, help="Don't auto-open browser")
def ui(port: int, host: str, no_browser: bool) -> None:
    """Launch the local web UI for graphical job submission and monitoring.

    \b
    Starts a local server for drag-and-drop file submission,
    visual job tracking, and one-click result retrieval.

    \b
    All encryption happens locally — same security model as the CLI.

    \b
    Examples:
        byod ui                    # Opens http://localhost:8420
        byod ui --port 9000        # Custom port
        byod ui --no-browser       # Don't auto-open browser
    """
    console = _helpers.console
    try:
        from byod_cli.ui import launch_ui
    except ImportError:
        console.print(_helpers.format_error(
            "UI dependencies not installed. Run: pip install 'byod-cli[ui]'"
        ))
        sys.exit(EXIT_ERROR)

    console.print(
        "\n[bold]BYOD Local UI[/bold] — "
        "[dim]All encryption happens on your machine[/dim]\n"
    )
    launch_ui(host=host, port=port, open_browser=not no_browser)
