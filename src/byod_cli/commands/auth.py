"""
Auth commands for BYOD CLI.

Contains the `auth` group and its subcommands: login, logout, status.
"""

from __future__ import annotations

import json
import sys

import click

from byod_cli.api_client import APIClient, APIError, AuthenticationError
from byod_cli.commands import _helpers

EXIT_AUTH = _helpers.EXIT_AUTH
EXIT_NETWORK = _helpers.EXIT_NETWORK


@click.group()
def auth() -> None:
    """Manage authentication with Lablytics platform."""
    pass


@auth.command(name="login")
@click.option("--api-key", prompt=True, hide_input=True, help="Your Lablytics API key")
@click.option("--api-url", default=None, help="Custom API URL (for self-hosted)")
@click.pass_context
def auth_login(ctx: click.Context, api_key: str, api_url: str | None) -> None:
    """
    Authenticate with the Lablytics platform.

    Get your API key from https://byod.cultivatedcode.co (Settings > API Keys)

    \b
    Examples:
        byod auth login
        byod auth login --api-key sk_live_abc123...
    """
    config = ctx.obj["CONFIG"]
    console = _helpers.console

    console.print("\n[bold blue]Authenticating with Lablytics...[/bold blue]\n")

    # Verify the API key works
    client = APIClient(api_url=api_url or config.get_api_url(), api_key=api_key)

    try:
        with console.status("[bold green]Verifying credentials..."):
            client.verify_auth()
            tenant_config = client.get_tenant_config()
    except AuthenticationError as e:
        console.print(_helpers.format_error(str(e)))
        sys.exit(EXIT_AUTH)
    except APIError as e:
        console.print(_helpers.format_error(f"Failed to connect: {e}"))
        console.print("  Check your network connection or try again.")
        sys.exit(EXIT_NETWORK)

    # Save credentials
    config.set_api_credentials(api_key, api_url)

    # Create/update profile from tenant config
    profile_name = tenant_config.tenant_id
    if config.profile_exists(profile_name):
        config.delete_profile(profile_name)

    config.create_profile(
        name=profile_name,
        tenant_id=tenant_config.tenant_id,
        organization_name=tenant_config.organization_name,
        region=tenant_config.region,
    )

    console.print(_helpers.format_success("Authentication successful!"))
    console.print(f"\n  Organization: {tenant_config.organization_name}")
    console.print(f"  Tenant ID:    {tenant_config.tenant_id}")
    console.print(f"  Region:       {tenant_config.region}")

    if tenant_config.customer_kms_key_arn:
        console.print(f"  KMS Key:      {tenant_config.customer_kms_key_arn} [dim](your key)[/dim]")
    else:
        console.print("  KMS Key:      Lablytics-managed")

    console.print("\n[bold green]Ready to submit jobs![/bold green]")
    console.print("\nNext steps:")
    console.print("  Submit a job: [cyan]byod submit genomic-qc ./data.fastq[/cyan]\n")


@auth.command(name="logout")
@click.pass_context
def auth_logout(ctx: click.Context) -> None:
    """Log out and clear stored credentials."""
    config = ctx.obj["CONFIG"]
    _helpers.console.print(_helpers.format_success("Logged out successfully."))
    config.clear_api_credentials()


@auth.command(name="status")
@click.option("--format", "output_format", type=click.Choice(["text", "json"]), default="text")
@click.pass_context
def auth_status(ctx: click.Context, output_format: str) -> None:
    """Check authentication status."""
    config = ctx.obj["CONFIG"]
    console = _helpers.console

    if not config.is_authenticated():
        if output_format == "json":
            click.echo(json.dumps({"authenticated": False}))
        else:
            console.print("\n[yellow]Not authenticated.[/yellow]")
            console.print("Run [cyan]byod auth login[/cyan] to authenticate.\n")
        return

    try:
        client = _helpers._get_api_client(config)
        with console.status("[bold green]Checking..."):
            client.verify_auth()
            tenant_config = client.get_tenant_config()

        if output_format == "json":
            click.echo(json.dumps({
                "authenticated": True,
                "organization": tenant_config.organization_name,
                "tenant_id": tenant_config.tenant_id,
                "api_url": config.get_api_url(),
            }))
        else:
            console.print("\n[bold green]Authenticated[/bold green]")
            console.print(f"\n  Organization: {tenant_config.organization_name}")
            console.print(f"  Tenant ID:    {tenant_config.tenant_id}")
            console.print(f"  API URL:      {config.get_api_url()}\n")

    except AuthenticationError:
        if output_format == "json":
            click.echo(json.dumps({"authenticated": False, "error": "expired_or_invalid"}))
        else:
            console.print("\n[red]Authentication expired or invalid.[/red]")
            console.print("Run [cyan]byod auth login[/cyan] to re-authenticate.\n")
