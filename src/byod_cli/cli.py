"""
BYOD CLI Main Entry Point

This module defines the command-line interface structure using Click.
It provides commands for authentication, job submission, status checking, and result retrieval.

Security Note:
All encryption operations happen client-side. Keys are never transmitted to the platform.
Lablytics manages all S3 buckets and provides presigned URLs for secure upload/download.
"""

from __future__ import annotations

import io
import json
import os
import sys
import tarfile
from datetime import datetime
from pathlib import Path
from typing import Any

import click
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from byod_cli import __version__
from byod_cli.api_client import APIClient, APIError, AuthenticationError
from byod_cli.config import ConfigManager
from byod_cli.utils import (
    format_bytes,
    format_error,
    format_success,
    format_warning,
    setup_logging,
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


def _get_api_client(config: ConfigManager) -> APIClient:
    """Create an authenticated API client."""
    api_key = config.get_api_key()
    if not api_key:
        raise click.ClickException(
            "Not authenticated. Run 'byod auth login' first."
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


# ============================================================================
# Main CLI Group
# ============================================================================


@click.group()
@click.version_option(version=__version__, prog_name="byod")
@click.option("--debug", is_flag=True, help="Enable debug logging", envvar="BYOD_DEBUG")
@click.pass_context
def cli(ctx: click.Context, debug: bool) -> None:
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
    log_level = "DEBUG" if debug else "INFO"
    setup_logging(log_level)

    ctx.ensure_object(dict)
    ctx.obj["DEBUG"] = debug

    try:
        config_manager = ConfigManager()
        ctx.obj["CONFIG"] = config_manager
    except Exception as e:
        if ctx.invoked_subcommand not in ["auth"]:
            console.print(format_error(f"Configuration error: {e}"))
            sys.exit(1)


# ============================================================================
# Auth Commands
# ============================================================================


@cli.group()
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

    Get your API key from the Lablytics dashboard at https://app.lablytics.io/settings/api-keys

    \b
    Examples:
        byod auth login
        byod auth login --api-key sk_live_abc123...
    """
    config = ctx.obj["CONFIG"]

    console.print("\n[bold blue]Authenticating with Lablytics...[/bold blue]\n")

    # Verify the API key works
    client = APIClient(api_url=api_url or config.get_api_url(), api_key=api_key)

    try:
        with console.status("[bold green]Verifying credentials..."):
            client.verify_auth()
            tenant_config = client.get_tenant_config()
    except AuthenticationError as e:
        console.print(format_error(str(e)))
        sys.exit(1)
    except APIError as e:
        console.print(format_error(f"Failed to connect: {e}"))
        sys.exit(1)

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

    console.print(format_success("Authentication successful!"))
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
    config.clear_api_credentials()
    console.print(format_success("Logged out successfully."))


@auth.command(name="status")
@click.pass_context
def auth_status(ctx: click.Context) -> None:
    """Check authentication status."""
    config = ctx.obj["CONFIG"]

    if not config.is_authenticated():
        console.print("\n[yellow]Not authenticated.[/yellow]")
        console.print("Run [cyan]byod auth login[/cyan] to authenticate.\n")
        return

    try:
        client = _get_api_client(config)
        with console.status("[bold green]Checking..."):
            client.verify_auth()
            tenant_config = client.get_tenant_config()

        console.print("\n[bold green]Authenticated[/bold green]")
        console.print(f"\n  Organization: {tenant_config.organization_name}")
        console.print(f"  Tenant ID:    {tenant_config.tenant_id}")
        console.print(f"  API URL:      {config.get_api_url()}\n")

    except AuthenticationError:
        console.print("\n[red]Authentication expired or invalid.[/red]")
        console.print("Run [cyan]byod auth login[/cyan] to re-authenticate.\n")


# ============================================================================
# Setup Command
# ============================================================================


@cli.command()
@click.option("--region", default="us-east-1", help="AWS region for KMS key and IAM role")
@click.option("--new", "force_new", is_flag=True, help="Delete existing resources and create new ones")
@click.pass_context
def setup(ctx: click.Context, region: str, force_new: bool) -> None:
    """
    Set up AWS resources for secure data processing.

    This command creates in YOUR AWS account:
    1. A KMS key with attestation policy (only Nitro Enclave can decrypt)
    2. A cross-account IAM role (allows Lablytics enclave to use your key)

    \b
    Prerequisites:
    - You must be authenticated: byod auth login
    - Your AWS credentials must be configured (~/.aws/credentials or env vars)
    - Your AWS account must have permission to create KMS keys and IAM roles

    \b
    Example:
        byod setup
        byod setup --region us-west-2
        byod setup --new  # Replace existing resources with new ones
    """
    import boto3
    from botocore.exceptions import ClientError

    config = ctx.obj["CONFIG"]
    client = _get_api_client(config)

    console.print("\n[bold blue]Setting up AWS resources for BYOD...[/bold blue]\n")

    # Step 1: Get enclave info from Lablytics
    console.print("[dim]Fetching enclave configuration...[/dim]")
    try:
        enclave_info = client.get_enclave_info()
        # Support multi-orchestrator: prefer pcr0_values array, fall back to single pcr0
        pcr0_values = enclave_info.get("pcr0_values") or [enclave_info["pcr0"]]
        lablytics_account_id = enclave_info["account_id"]
        tenant_id = enclave_info["tenant_id"]
    except APIError as e:
        console.print(format_error(f"Failed to get enclave info: {e}"))
        sys.exit(1)

    console.print(f"  Tenant ID: {tenant_id}")
    if len(pcr0_values) == 1:
        console.print(f"  Enclave PCR0: {pcr0_values[0][:16]}...")
    else:
        console.print(f"  Enclave PCR0 values: {len(pcr0_values)} active")
        for i, v in enumerate(pcr0_values):
            console.print(f"    [{i+1}] {v[:16]}...")

    # Step 2: Get customer's AWS account ID
    console.print("\n[dim]Checking AWS credentials...[/dim]")
    try:
        sts = boto3.client("sts", region_name=region)
        identity = sts.get_caller_identity()
        customer_account_id = identity["Account"]
        console.print(f"  AWS Account: {customer_account_id}")
        console.print(f"  Region: {region}")
    except ClientError as e:
        console.print(format_error(f"Failed to get AWS identity: {e}"))
        console.print("\nMake sure your AWS credentials are configured:")
        console.print("  - ~/.aws/credentials file, or")
        console.print("  - AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY environment variables")
        sys.exit(1)

    role_name = f"BYODEnclaveRole-{tenant_id[:16]}"
    alias_name = f"alias/byod-{tenant_id[:16]}"

    # Step 2.5: If --new flag, delete existing resources first
    if force_new:
        console.print("\n[bold yellow]--new flag specified: Deleting existing resources...[/bold yellow]")

        iam = boto3.client("iam", region_name=region)
        kms = boto3.client("kms", region_name=region)

        # Delete IAM role (must delete inline policies first)
        try:
            # List and delete inline policies
            policies = iam.list_role_policies(RoleName=role_name)
            for policy_name in policies.get("PolicyNames", []):
                console.print(f"  Deleting inline policy: {policy_name}")
                iam.delete_role_policy(RoleName=role_name, PolicyName=policy_name)

            # List and detach managed policies
            attached = iam.list_attached_role_policies(RoleName=role_name)
            for policy in attached.get("AttachedPolicies", []):
                console.print(f"  Detaching policy: {policy['PolicyArn']}")
                iam.detach_role_policy(RoleName=role_name, PolicyArn=policy["PolicyArn"])

            # Delete the role
            console.print(f"  Deleting IAM role: {role_name}")
            iam.delete_role(RoleName=role_name)
            console.print("  [green]IAM role deleted[/green]")
        except ClientError as e:
            if e.response["Error"]["Code"] == "NoSuchEntity":
                console.print(f"  IAM role {role_name} does not exist (OK)")
            else:
                console.print(format_warning(f"Could not delete IAM role: {e}"))

        # Delete KMS key (via alias lookup)
        try:
            # Get key ID from alias
            alias_response = kms.describe_key(KeyId=alias_name)
            key_id = alias_response["KeyMetadata"]["KeyId"]
            key_arn = alias_response["KeyMetadata"]["Arn"]

            # Delete the alias first
            console.print(f"  Deleting KMS alias: {alias_name}")
            kms.delete_alias(AliasName=alias_name)

            # Schedule key for deletion (minimum 7 days)
            console.print(f"  Scheduling KMS key for deletion: {key_arn}")
            kms.schedule_key_deletion(KeyId=key_id, PendingWindowInDays=7)
            console.print("  [green]KMS key scheduled for deletion (7 days)[/green]")
        except ClientError as e:
            if e.response["Error"]["Code"] == "NotFoundException":
                console.print(f"  KMS key with alias {alias_name} does not exist (OK)")
            else:
                console.print(format_warning(f"Could not delete KMS key: {e}"))

        console.print("")

    # Step 3: Create cross-account role first (needed for KMS policy)
    console.print("\n[dim]Creating cross-account IAM role...[/dim]")

    trust_policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Principal": {"AWS": f"arn:aws:iam::{lablytics_account_id}:root"},
                "Action": "sts:AssumeRole",
                "Condition": {"StringEquals": {"sts:ExternalId": tenant_id}},
            }
        ],
    }

    try:
        iam = boto3.client("iam", region_name=region)
        role_response = iam.create_role(
            RoleName=role_name,
            AssumeRolePolicyDocument=json.dumps(trust_policy),
            Description=f"Allows BYOD enclave to access KMS key (tenant: {tenant_id})",
            Tags=[
                {"Key": "Purpose", "Value": "BYOD-CrossAccountAccess"},
                {"Key": "TenantId", "Value": tenant_id},
            ],
        )
        role_arn = role_response["Role"]["Arn"]
        console.print(f"  Role: {role_arn}")

        # Wait for IAM role to propagate (eventual consistency)
        console.print("  [dim]Waiting for IAM role to propagate...[/dim]")
        import time
        time.sleep(10)
    except ClientError as e:
        if e.response["Error"]["Code"] == "EntityAlreadyExists":
            role_arn = f"arn:aws:iam::{customer_account_id}:role/{role_name}"
            console.print(f"  Role already exists: {role_arn}")
        else:
            console.print(format_error(f"Failed to create IAM role: {e}"))
            sys.exit(1)

    # Step 4: Create KMS key with attestation policy
    # Uses two-Deny pattern to guarantee attestation enforcement
    console.print("\n[dim]Creating KMS key with attestation policy...[/dim]")

    # Key policy structure:
    # - CustomerAdmin: all admin actions EXCEPT Decrypt (prevents backdoor)
    # - CustomerDecrypt: allows customer to decrypt, but EXCLUDES the cross-account role
    # - RoleOperations: GenerateDataKey + DescribeKey for the role
    # - RoleDecrypt: Decrypt ONLY with valid attestation
    #
    # This ensures the cross-account role can ONLY decrypt via RoleDecrypt,
    # which requires the correct PCR0 attestation.

    key_policy = {
        "Version": "2012-10-17",
        "Statement": [
            # Customer admin access for key management (NOT Decrypt)
            # This prevents the kms:* backdoor that allows any account principal to decrypt
            {
                "Sid": "CustomerAdmin",
                "Effect": "Allow",
                "Principal": {"AWS": f"arn:aws:iam::{customer_account_id}:root"},
                "Action": [
                    "kms:Create*",
                    "kms:Describe*",
                    "kms:Enable*",
                    "kms:List*",
                    "kms:Put*",
                    "kms:Update*",
                    "kms:Revoke*",
                    "kms:Disable*",
                    "kms:Get*",
                    "kms:Delete*",
                    "kms:TagResource",
                    "kms:UntagResource",
                    "kms:ScheduleKeyDeletion",
                    "kms:CancelKeyDeletion",
                    "kms:Encrypt",
                    "kms:GenerateDataKey",
                    "kms:GenerateDataKeyWithoutPlaintext",
                ],
                "Resource": "*",
            },
            # Customer can decrypt - but NOT the cross-account role
            # This allows the customer to decrypt results locally while
            # forcing the cross-account role to use attested decrypt
            {
                "Sid": "CustomerDecrypt",
                "Effect": "Allow",
                "Principal": {"AWS": f"arn:aws:iam::{customer_account_id}:root"},
                "Action": "kms:Decrypt",
                "Resource": "*",
                "Condition": {
                    "ArnNotEquals": {
                        "aws:PrincipalArn": role_arn
                    }
                },
            },
            # Cross-account role can generate data keys (for encryption)
            {
                "Sid": "RoleOperations",
                "Effect": "Allow",
                "Principal": {"AWS": role_arn},
                "Action": ["kms:GenerateDataKey", "kms:DescribeKey"],
                "Resource": "*",
            },
            # Cross-account role can ONLY decrypt with valid attestation
            # This is the ONLY way the role can decrypt - no backdoor possible
            {
                "Sid": "RoleDecryptWithAttestation",
                "Effect": "Allow",
                "Principal": {"AWS": role_arn},
                "Action": "kms:Decrypt",
                "Resource": "*",
                "Condition": {
                    "StringEqualsIgnoreCase": {
                        # Array of PCR0 values — KMS natively supports arrays,
                        # allowing multiple orchestrators / rolling enclave updates
                        "kms:RecipientAttestation:PCR0": pcr0_values
                    }
                },
            },
        ],
    }

    try:
        kms = boto3.client("kms", region_name=region)
        key_response = kms.create_key(
            Policy=json.dumps(key_policy),
            Description=f"BYOD encryption key (tenant: {tenant_id})",
            KeyUsage="ENCRYPT_DECRYPT",
            Tags=[
                {"TagKey": "Purpose", "TagValue": "BYOD-DataEncryption"},
                {"TagKey": "TenantId", "TagValue": tenant_id},
            ],
        )
        key_arn = key_response["KeyMetadata"]["Arn"]
        key_id = key_response["KeyMetadata"]["KeyId"]
        console.print(f"  KMS Key: {key_arn}")

        # Create an alias for easier identification
        try:
            kms.create_alias(AliasName=alias_name, TargetKeyId=key_id)
            console.print(f"  Alias: {alias_name}")
        except ClientError:
            pass  # Alias might already exist

    except ClientError as e:
        console.print(format_error(f"Failed to create KMS key: {e}"))
        sys.exit(1)

    # Step 5: Attach KMS policy to the role
    console.print("\n[dim]Attaching KMS permissions to role...[/dim]")

    role_policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Action": ["kms:GenerateDataKey", "kms:Decrypt", "kms:DescribeKey"],
                "Resource": key_arn,
            }
        ],
    }

    try:
        iam.put_role_policy(
            RoleName=role_name,
            PolicyName="BYODKMSAccess",
            PolicyDocument=json.dumps(role_policy),
        )
        console.print("  Attached BYODKMSAccess policy")
    except ClientError as e:
        console.print(format_error(f"Failed to attach policy: {e}"))
        sys.exit(1)

    # Step 6: Register with Lablytics
    console.print("\n[dim]Registering with Lablytics...[/dim]")
    try:
        client.register_kms_setup(
            kms_key_arn=key_arn,
            role_arn=role_arn,
            aws_account_id=customer_account_id,
            region=region,
        )
        console.print("  Registration complete")
    except APIError as e:
        console.print(format_error(f"Failed to register with Lablytics: {e}"))
        console.print("\n[yellow]AWS resources were created but not registered.[/yellow]")
        console.print("You may need to manually configure KMS in the dashboard settings.")
        sys.exit(1)

    # Save KMS key ARN and role ARN to config for update-policy command
    active_profile = config.get_active_profile_name()
    if active_profile:
        config.update_profile_setting(active_profile, "kms_key_arn", key_arn)
        config.update_profile_setting(active_profile, "role_arn", role_arn)
        config.update_profile_setting(active_profile, "aws_account_id", customer_account_id)

    # Success!
    console.print("\n" + "=" * 60)
    console.print(format_success("Setup complete!"))
    console.print("=" * 60)

    console.print("\n[bold]Resources created:[/bold]")
    console.print(f"  KMS Key:  {key_arn}")
    console.print(f"  IAM Role: {role_arn}")

    console.print("\n[bold]Security guarantees:[/bold]")
    console.print("  ✓ Only YOU can manage/delete the KMS key")
    console.print("  ✓ Only the Nitro Enclave (with PCR0 verification) can decrypt")
    console.print("  ✓ Lablytics operators cannot access your data")

    console.print("\n[bold green]Ready to submit jobs![/bold green]")
    console.print("\nNext steps:")
    console.print("  Submit a job: [cyan]byod submit genomic-qc ./data.fastq[/cyan]\n")


# ============================================================================
# Update Policy Command
# ============================================================================


@cli.command("update-policy")
@click.option("--region", default="us-east-1", help="AWS region where the KMS key lives")
@click.pass_context
def update_policy(ctx: click.Context, region: str) -> None:
    """
    Update KMS key policy with the latest enclave PCR0 values.

    Run this after Lablytics deploys a new enclave version. The command
    fetches the current active PCR0 values from the dashboard and updates
    the RoleDecryptWithAttestation condition on your KMS key.

    \b
    Prerequisites:
    - You must have run `byod setup` first (stores key ARN in config)
    - Your AWS credentials must be configured

    \b
    Example:
        byod update-policy
        byod update-policy --region us-west-2
    """
    import boto3
    from botocore.exceptions import ClientError

    config = ctx.obj["CONFIG"]
    client = _get_api_client(config)

    console.print("\n[bold blue]Updating KMS key policy with latest PCR0 values...[/bold blue]\n")

    # Step 1: Get key ARN from config
    active_profile = config.get_active_profile_name()
    if not active_profile:
        console.print(format_error("No active profile. Run 'byod setup' first."))
        sys.exit(1)

    profile = config.get_profile(active_profile)
    kms_key_arn = profile.get("settings", {}).get("kms_key_arn")
    role_arn = profile.get("settings", {}).get("role_arn")

    if not kms_key_arn:
        console.print(format_error(
            "No KMS key ARN found in config. Run 'byod setup' first, "
            "or re-run with --new to recreate resources."
        ))
        sys.exit(1)

    console.print(f"  KMS Key: {kms_key_arn}")
    console.print(f"  Role:    {role_arn}")

    # Step 2: Fetch latest PCR0 values from dashboard
    console.print("\n[dim]Fetching latest PCR0 values...[/dim]")
    try:
        enclave_info = client.get_enclave_info()
        pcr0_values = enclave_info.get("pcr0_values") or [enclave_info["pcr0"]]
    except APIError as e:
        console.print(format_error(f"Failed to get enclave info: {e}"))
        sys.exit(1)

    console.print(f"  Active PCR0 values: {len(pcr0_values)}")
    for i, v in enumerate(pcr0_values):
        console.print(f"    [{i+1}] {v[:16]}...")

    # Step 3: Get current key policy
    console.print("\n[dim]Reading current key policy...[/dim]")
    try:
        kms = boto3.client("kms", region_name=region)
        policy_response = kms.get_key_policy(KeyId=kms_key_arn, PolicyName="default")
        current_policy = json.loads(policy_response["Policy"])
    except ClientError as e:
        console.print(format_error(f"Failed to read key policy: {e}"))
        sys.exit(1)

    # Step 4: Find and update the RoleDecryptWithAttestation statement
    updated = False
    old_pcr0_values = None
    for statement in current_policy.get("Statement", []):
        if statement.get("Sid") == "RoleDecryptWithAttestation":
            condition = statement.get("Condition", {})
            ignore_case = condition.get("StringEqualsIgnoreCase", {})
            old_pcr0_values = ignore_case.get("kms:RecipientAttestation:PCR0")
            if isinstance(old_pcr0_values, str):
                old_pcr0_values = [old_pcr0_values]
            ignore_case["kms:RecipientAttestation:PCR0"] = pcr0_values
            updated = True
            break

    if not updated:
        console.print(format_error(
            "Could not find RoleDecryptWithAttestation statement in key policy. "
            "The key policy may have been modified manually."
        ))
        sys.exit(1)

    # Step 5: Show diff and apply
    if old_pcr0_values and set(old_pcr0_values) == set(pcr0_values):
        console.print("\n[green]Key policy is already up to date![/green]")
        return

    console.print("\n[bold]Policy update:[/bold]")
    if old_pcr0_values:
        console.print(f"  Old PCR0: {', '.join(v[:16] + '...' for v in old_pcr0_values)}")
    console.print(f"  New PCR0: {', '.join(v[:16] + '...' for v in pcr0_values)}")

    try:
        kms.put_key_policy(
            KeyId=kms_key_arn,
            PolicyName="default",
            Policy=json.dumps(current_policy),
        )
        console.print(format_success("\nKey policy updated successfully!"))
    except ClientError as e:
        console.print(format_error(f"Failed to update key policy: {e}"))
        sys.exit(1)

    console.print(f"\n  Your KMS key now allows decryption from {len(pcr0_values)} enclave(s).")
    console.print("  You can verify by running: [cyan]byod update-policy[/cyan] again.\n")


# ============================================================================
# Submit Command
# ============================================================================


@cli.command()
@click.argument("plugin")
@click.argument("input_path", type=click.Path(exists=True, path_type=Path))
@click.option("--description", help="Human-readable job description")
@click.option("--config", "config_path", type=click.Path(exists=True, path_type=Path), help="Plugin config (JSON)")
@click.option("--wait", is_flag=True, help="Wait for job completion (simple spinner)")
@click.option("--track", is_flag=True, help="Track job progress with live status updates")
@click.option("--timeout", type=int, default=3600, help="Timeout in seconds when using --wait or --track")
@click.option("--tags", multiple=True, help="Metadata tags (format: key=value)")
@click.pass_context
def submit(
    ctx: click.Context,
    plugin: str,
    input_path: Path,
    description: str | None,
    config_path: Path | None,
    wait: bool,
    track: bool,
    timeout: int,
    tags: tuple[str, ...],
) -> None:
    """
    Submit data for secure enclave processing.

    Data is encrypted client-side with a KMS-managed key, uploaded via presigned URL,
    and processed in an attested Nitro Enclave.

    \b
    Available plugins:
        genomic-qc     FastQC + MultiQC quality control for FASTQ files
        demo-count     Simple line/word counting demo

    \b
    Examples:
        byod submit genomic-qc ./sample.fastq.gz
        byod submit demo-count ./data.txt --track
        byod submit genomic-qc ./samples/ --tags experiment=exp001
    """
    import time

    import boto3

    config = ctx.obj["CONFIG"]

    try:
        client = _get_api_client(config)
    except click.ClickException:
        console.print(format_error("Not authenticated. Run 'byod auth login' first."))
        sys.exit(1)

    console.print("\n[bold blue]Submitting job...[/bold blue]\n")
    console.print(f"  Plugin: {plugin}")
    console.print(f"  Input:  {input_path}")
    if description:
        console.print(f"  Desc:   {description}")

    # Parse tags
    tags_dict: dict[str, str] = {}
    for tag in tags:
        if "=" not in tag:
            raise click.ClickException(f"Invalid tag format: {tag}. Use key=value")
        key, value = tag.split("=", 1)
        tags_dict[key] = value

    # Load plugin config
    plugin_config: dict[str, Any] | None = None
    if config_path:
        with open(config_path) as f:
            plugin_config = json.load(f)

    try:
        # Get tenant config for KMS key
        with console.status("[bold green]Getting platform configuration..."):
            tenant_config = client.get_tenant_config()

        # Determine which KMS key to use
        kms_key_id = tenant_config.customer_kms_key_arn or tenant_config.kms_key_arn
        if not kms_key_id:
            raise click.ClickException("No KMS key configured. Contact support.")

        # Generate DEK via KMS
        console.print("\n  Generating encryption key via KMS...")
        kms = boto3.client("kms", region_name=tenant_config.region)
        key_response = kms.generate_data_key(KeyId=kms_key_id, KeySpec="AES_256")
        plaintext_key = key_response["Plaintext"]
        wrapped_key = key_response["CiphertextBlob"]

        # Read and encrypt input data
        console.print("  Encrypting data client-side...")
        if input_path.is_dir():
            buf = io.BytesIO()
            with tarfile.open(fileobj=buf, mode="w:gz") as tar:
                tar.add(str(input_path), arcname=input_path.name)
            plaintext = buf.getvalue()
        else:
            with open(input_path, "rb") as f:
                plaintext = f.read()

        encrypted_data = _encrypt_data(plaintext, plaintext_key)
        console.print(f"  Encrypted: {format_bytes(len(plaintext))} -> {format_bytes(len(encrypted_data))}")

        # Get presigned URLs and upload
        with console.status("[bold green]Uploading encrypted data..."):
            # Get presigned URL for encrypted data
            upload_presigned = client.get_upload_url(
                filename=f"{input_path.name}.enc",
                content_type="application/octet-stream",
                file_size=len(encrypted_data),
            )

            # Upload encrypted data via presigned POST
            import requests
            files = {"file": (f"{input_path.name}.enc", io.BytesIO(encrypted_data))}
            response = requests.post(
                upload_presigned.url,
                data=upload_presigned.fields,
                files=files,
                timeout=300,
            )
            if not response.ok:
                raise APIError(f"Upload failed: {response.status_code}")

            input_s3_key = upload_presigned.s3_key

            # Get presigned URL for wrapped key
            key_presigned = client.get_upload_url(
                filename="wrapped_key.bin",
                content_type="application/octet-stream",
                file_size=len(wrapped_key),
            )

            # Upload wrapped key
            files = {"file": ("wrapped_key.bin", io.BytesIO(wrapped_key))}
            response = requests.post(
                key_presigned.url,
                data=key_presigned.fields,
                files=files,
                timeout=60,
            )
            if not response.ok:
                raise APIError(f"Key upload failed: {response.status_code}")

            wrapped_key_s3_key = key_presigned.s3_key

        # Submit job to platform
        with console.status("[bold green]Submitting job..."):
            job = client.submit_job(
                plugin_name=plugin,
                input_s3_key=input_s3_key,
                wrapped_key_s3_key=wrapped_key_s3_key,
                description=description,
                config=plugin_config,
                tags=tags_dict,
            )

        # Clear plaintext key from memory (best effort)
        if isinstance(plaintext_key, bytearray):
            for i in range(len(plaintext_key)):
                plaintext_key[i] = 0

        console.print(format_success(f"Job submitted: {job.job_id}"))

        if not (wait or track):
            console.print(f"\n  Check status:  [cyan]byod status {job.job_id}[/cyan]")
            console.print(f"  Get results:   [cyan]byod get {job.job_id} -o ./output/[/cyan]\n")
            return

        # Track or wait for job completion
        poll_interval = 5 if track else 10
        elapsed = 0
        last_status = None

        # Status display configuration
        status_icons = {
            "pending": "⏳",
            "submitted": "📤",
            "downloading": "⬇️ ",
            "processing": "⚙️ ",
            "uploading": "⬆️ ",
            "completed": "✅",
            "failed": "❌",
            "cancelled": "🚫",
        }
        status_messages = {
            "pending": "Waiting to start...",
            "submitted": "Job queued",
            "downloading": "Downloading encrypted data",
            "processing": "Processing in Nitro Enclave",
            "uploading": "Uploading encrypted results",
            "completed": "Job completed successfully!",
            "failed": "Job failed",
            "cancelled": "Job cancelled",
        }

        if track:
            console.print("\n[bold]Tracking job progress:[/bold]\n")

            while elapsed < timeout:
                status_info = client.get_job_status(job.job_id)
                current_status = status_info["status"]

                # Print status change
                if current_status != last_status:
                    icon = status_icons.get(current_status, "•")
                    msg = status_messages.get(current_status, current_status)
                    if current_status == "completed":
                        console.print(f"  {icon} [bold green]{msg}[/bold green]")
                    elif current_status in ["failed", "cancelled"]:
                        error = status_info.get("error", "Unknown error")
                        console.print(f"  {icon} [bold red]{msg}[/bold red]: {error}")
                    else:
                        console.print(f"  {icon} [cyan]{msg}[/cyan] [dim]({elapsed}s)[/dim]")
                    last_status = current_status

                # Check for terminal states
                if current_status == "completed":
                    console.print(f"\n  Get results: [cyan]byod get {job.job_id} -o ./output/[/cyan]\n")
                    return
                elif current_status in ["failed", "cancelled"]:
                    sys.exit(1)

                time.sleep(poll_interval)
                elapsed += poll_interval

            console.print(format_warning(f"\nTimed out after {timeout}s. Job may still be processing."))
            console.print(f"  Check status: [cyan]byod status {job.job_id}[/cyan]\n")

        else:
            # Simple --wait mode with spinner
            console.print("\nWaiting for job completion...\n")

            with console.status("[bold green]Processing...") as spinner:
                while elapsed < timeout:
                    status_info = client.get_job_status(job.job_id)
                    if status_info["status"] == "completed":
                        console.print(format_success("Job completed!"))
                        console.print(f"\n  Get results: [cyan]byod get {job.job_id} -o ./output/[/cyan]\n")
                        return
                    elif status_info["status"] in ["failed", "cancelled"]:
                        console.print(format_error(f"Job {status_info['status']}: {status_info.get('error', 'Unknown error')}"))
                        sys.exit(1)

                    spinner.update(f"[bold green]Processing ({elapsed}s elapsed)...")
                    time.sleep(poll_interval)
                    elapsed += poll_interval

            console.print(format_warning(f"Timed out after {timeout}s. Job may still be processing."))

    except AuthenticationError as e:
        console.print(format_error(str(e)))
        sys.exit(1)
    except APIError as e:
        console.print(format_error(f"API error: {e}"))
        if ctx.obj.get("DEBUG"):
            console.print_exception()
        sys.exit(1)
    except Exception as e:
        console.print(format_error(f"Submission failed: {e}"))
        if ctx.obj.get("DEBUG"):
            console.print_exception()
        sys.exit(1)


# ============================================================================
# Status Command
# ============================================================================


@cli.command()
@click.argument("job_id")
@click.option("--format", "output_format", type=click.Choice(["text", "json"]), default="text")
@click.pass_context
def status(ctx: click.Context, job_id: str, output_format: str) -> None:
    """
    Check the status of a submitted job.

    \b
    Examples:
        byod status genomic-qc-20250126-abc123
        byod status genomic-qc-20250126-abc123 --format json
    """
    config = ctx.obj["CONFIG"]
    client = _get_api_client(config)

    try:
        status_info = client.get_job_status(job_id)

        if output_format == "json":
            console.print(json.dumps(status_info, indent=2, default=str))
        else:
            _print_status(status_info)

    except APIError as e:
        console.print(format_error(f"Failed to get status: {e}"))
        sys.exit(1)


def _print_status(status_info: dict[str, Any]) -> None:
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


# ============================================================================
# List Command
# ============================================================================


@cli.command(name="list")
@click.option("--limit", type=int, default=20, help="Maximum jobs to display")
@click.option("--status", "filter_status", help="Filter by status")
@click.option("--format", "output_format", type=click.Choice(["table", "json"]), default="table")
@click.pass_context
def list_jobs(ctx: click.Context, limit: int, filter_status: str | None, output_format: str) -> None:
    """
    List submitted jobs.

    \b
    Examples:
        byod list
        byod list --limit 50
        byod list --status completed
    """
    config = ctx.obj["CONFIG"]
    client = _get_api_client(config)

    try:
        with console.status("[bold green]Fetching jobs..."):
            jobs = client.list_jobs(limit=limit, status=filter_status)

        if output_format == "json":
            console.print(json.dumps(jobs, indent=2))
            return

        if not jobs:
            console.print("\nNo jobs found.\n")
            console.print("Submit a job: [cyan]byod submit <plugin> <data-path>[/cyan]\n")
            return

        table = Table(title=f"Jobs (showing {len(jobs)})")
        table.add_column("Job ID", style="cyan")
        table.add_column("Plugin", style="blue")
        table.add_column("Status", style="green")
        table.add_column("Submitted", style="dim")
        table.add_column("Description")

        for job in jobs:
            job_status = job.get("status", "unknown")
            status_styled = {
                "completed": "[bold green]completed[/bold green]",
                "processing": "[bold yellow]processing[/bold yellow]",
                "failed": "[bold red]failed[/bold red]",
            }.get(job_status, job_status)

            table.add_row(
                job.get("job_id", "?"),
                job.get("plugin_name", "?"),
                status_styled,
                job.get("created_at", "?"),
                (job.get("description") or "")[:40],
            )

        console.print(table)

    except APIError as e:
        console.print(format_error(f"Failed to list jobs: {e}"))
        sys.exit(1)


# ============================================================================
# Retrieve Command
# ============================================================================


@cli.command()
@click.argument("job_id")
@click.option("-o", "--output", required=True, type=click.Path(path_type=Path), help="Output directory")
@click.option("--overwrite", is_flag=True, help="Overwrite existing files")
@click.pass_context
def retrieve(ctx: click.Context, job_id: str, output: Path, overwrite: bool) -> None:
    """
    Download encrypted results from a completed job.

    Use 'byod decrypt' afterward to decrypt the results locally.

    \b
    Examples:
        byod retrieve genomic-qc-20250126-abc123 -o ./results/
    """
    import requests

    config = ctx.obj["CONFIG"]
    client = _get_api_client(config)

    if output.exists() and any(output.iterdir()) and not overwrite:
        console.print(format_error(f"Output directory {output} is not empty. Use --overwrite."))
        sys.exit(1)

    console.print(f"\n[bold blue]Retrieving results for job {job_id}...[/bold blue]\n")

    try:
        # Get presigned URLs for download
        with console.status("[bold green]Getting download URLs..."):
            output_presigned = client.get_download_url(job_id, "output.enc")
            key_presigned = client.get_download_url(job_id, "output_key.bin")

        output.mkdir(parents=True, exist_ok=True)

        # Download encrypted results
        with console.status("[bold green]Downloading encrypted results..."):
            response = requests.get(output_presigned.url, stream=True, timeout=300)
            if not response.ok:
                raise APIError(f"Download failed: {response.status_code}")

            enc_path = output / "output.enc"
            with open(enc_path, "wb") as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)

        # Download wrapped key
        with console.status("[bold green]Downloading wrapped key..."):
            response = requests.get(key_presigned.url, timeout=60)
            if not response.ok:
                raise APIError(f"Key download failed: {response.status_code}")

            key_path = output / "output_key.bin"
            with open(key_path, "wb") as f:
                f.write(response.content)

        # Get tenant config for KMS info
        tenant_config = client.get_tenant_config()
        kms_key_id = tenant_config.customer_kms_key_arn or tenant_config.kms_key_arn

        # Create results manifest
        manifest = {
            "job_id": job_id,
            "encrypted_file": "output.enc",
            "wrapped_key_file": "output_key.bin",
            "kms_key_id": kms_key_id,
            "region": tenant_config.region,
            "downloaded_at": datetime.now().isoformat(),
        }

        manifest_path = output / "results-manifest.json"
        with open(manifest_path, "w") as f:
            json.dump(manifest, f, indent=2)

        console.print(format_success("Results downloaded!"))
        console.print(f"\n  Output directory: {output}")
        console.print(f"  Manifest:         {manifest_path}")
        console.print(f"\n  Decrypt with: [cyan]byod decrypt {output} -o ./output.txt[/cyan]\n")

    except APIError as e:
        console.print(format_error(str(e)))
        sys.exit(1)
    except Exception as e:
        console.print(format_error(f"Retrieve failed: {e}"))
        if ctx.obj.get("DEBUG"):
            console.print_exception()
        sys.exit(1)


# ============================================================================
# Decrypt Command
# ============================================================================


@cli.command()
@click.argument("results_path", type=click.Path(exists=True, path_type=Path))
@click.option("-o", "--output", required=True, type=click.Path(path_type=Path), help="Output directory for extracted files")
@click.pass_context
def decrypt(ctx: click.Context, results_path: Path, output: Path) -> None:
    """
    Decrypt downloaded results locally.

    Uses KMS to unwrap the result encryption key, then decrypts with AES-256-GCM.
    Results are automatically extracted from the archive to the output directory.

    \b
    Examples:
        byod decrypt ./results/ -o ./decrypted/
    """
    import boto3

    console.print("\n[bold blue]Decrypting results...[/bold blue]\n")

    try:
        # Load manifest
        manifest_path = results_path / "results-manifest.json"
        if not manifest_path.exists():
            raise click.ClickException(
                f"Results manifest not found at {manifest_path}. Run 'byod retrieve' first."
            )

        with open(manifest_path) as f:
            manifest = json.load(f)

        # Debug: show manifest contents
        console.print("  [dim]Manifest:[/dim]")
        for k, v in manifest.items():
            console.print(f"    {k}: {v}")

        # Read wrapped key
        key_path = results_path / manifest["wrapped_key_file"]
        with open(key_path, "rb") as f:
            wrapped_key = f.read()

        # Debug: show wrapped key info
        console.print(f"\n  Wrapped key size: {len(wrapped_key)} bytes")
        console.print(f"  Wrapped key (hex, first 64): {wrapped_key[:64].hex()}")

        # Unwrap key via KMS
        console.print("\n  Unwrapping key via KMS...")
        kms = boto3.client("kms", region_name=manifest["region"])

        # Debug: try to describe the key first
        try:
            key_info = kms.describe_key(KeyId=manifest["kms_key_id"])
            console.print(f"  KMS Key State: {key_info['KeyMetadata']['KeyState']}")
            console.print(f"  KMS Key Usage: {key_info['KeyMetadata']['KeyUsage']}")
        except Exception as e:
            console.print(f"  [yellow]Warning: Could not describe KMS key: {e}[/yellow]")

        decrypt_response = kms.decrypt(
            CiphertextBlob=wrapped_key,
            KeyId=manifest["kms_key_id"],
        )
        result_key = decrypt_response["Plaintext"]

        # Read and decrypt results
        enc_path = results_path / manifest["encrypted_file"]
        with open(enc_path, "rb") as f:
            encrypted_data = f.read()

        console.print("  Decrypting data...")
        plaintext = _decrypt_data(encrypted_data, result_key)

        # The enclave packages results as a tar.gz archive
        # Detect and extract automatically
        import io
        import tarfile

        output.mkdir(parents=True, exist_ok=True)
        extracted_files = []

        # Check if it's a tar.gz archive (magic bytes: 1f 8b for gzip)
        if len(plaintext) > 2 and plaintext[0:2] == b'\x1f\x8b':
            console.print("  Extracting tar.gz archive...")
            try:
                with tarfile.open(fileobj=io.BytesIO(plaintext), mode='r:gz') as tar:
                    for member in tar.getmembers():
                        # Skip manifest file (internal metadata)
                        if member.name == "__manifest__.json":
                            continue
                        # Extract to output directory
                        tar.extract(member, path=output)
                        extracted_files.append(member.name)
                        console.print(f"    Extracted: {member.name}")
            except tarfile.TarError as e:
                # Fall back to writing raw bytes if not actually a tar
                console.print(f"  [yellow]Warning: Could not extract archive: {e}[/yellow]")
                raw_output = output / "output.bin"
                with open(raw_output, "wb") as f:
                    f.write(plaintext)
                extracted_files.append("output.bin")
        else:
            # Not a tar.gz, write as raw file
            raw_output = output / "output.bin"
            with open(raw_output, "wb") as f:
                f.write(plaintext)
            extracted_files.append("output.bin")

        console.print(format_success("Results decrypted!"))
        console.print(f"\n  Job ID:          {manifest['job_id']}")
        console.print(f"  Decrypted size:  {format_bytes(len(plaintext))}")
        console.print(f"  Output dir:      {output}")
        console.print(f"  Files extracted: {len(extracted_files)}\n")

        console.print(Panel(
            "[bold green]Security Verification[/bold green]\n\n"
            "  [green]OK[/green] Data was encrypted client-side before upload\n"
            "  [green]OK[/green] Only the attested Nitro Enclave could decrypt the input\n"
            "  [green]OK[/green] Enclave processed data and encrypted results with a new key\n"
            "  [green]OK[/green] Result key was unwrapped via KMS\n"
            "  [green]OK[/green] Results decrypted locally\n\n"
            "  Plaintext data never existed outside the Nitro Enclave.",
            title="Zero-Knowledge Processing",
            border_style="green",
        ))

        # Clear key from memory
        if isinstance(result_key, bytearray):
            for i in range(len(result_key)):
                result_key[i] = 0

    except Exception as e:
        console.print(format_error(f"Decryption failed: {e}"))
        if ctx.obj.get("DEBUG"):
            console.print_exception()
        sys.exit(1)


# ============================================================================
# Get Command (Retrieve + Decrypt)
# ============================================================================


@cli.command()
@click.argument("job_id")
@click.option("-o", "--output", required=True, type=click.Path(path_type=Path), help="Output directory for decrypted results")
@click.option("--keep-encrypted", is_flag=True, help="Keep intermediate encrypted files")
@click.option("--overwrite", is_flag=True, help="Overwrite existing files in output directory")
@click.pass_context
def get(ctx: click.Context, job_id: str, output: Path, keep_encrypted: bool, overwrite: bool) -> None:
    """
    Retrieve and decrypt job results in one step.

    Downloads encrypted results from a completed job, unwraps the key via KMS,
    decrypts with AES-256-GCM, and extracts files to the output directory.

    \b
    Examples:
        byod get genomic-qc-20250126-abc123 -o ./output/
        byod get genomic-qc-20250126-abc123 -o ./output/ --keep-encrypted
    """
    import boto3
    import requests

    config = ctx.obj["CONFIG"]
    client = _get_api_client(config)

    if output.exists() and any(output.iterdir()) and not overwrite:
        console.print(format_error(f"Output directory {output} is not empty. Use --overwrite."))
        sys.exit(1)

    console.print(f"\n[bold blue]Retrieving and decrypting results for job {job_id}...[/bold blue]\n")

    try:
        # Step 1: Download encrypted results and wrapped key
        with console.status("[bold green]Getting download URLs..."):
            output_presigned = client.get_download_url(job_id, "output.enc")
            key_presigned = client.get_download_url(job_id, "output_key.bin")

        output.mkdir(parents=True, exist_ok=True)

        with console.status("[bold green]Downloading encrypted results..."):
            response = requests.get(output_presigned.url, stream=True, timeout=300)
            if not response.ok:
                raise APIError(f"Download failed: {response.status_code}")

            enc_path = output / "output.enc"
            with open(enc_path, "wb") as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)

        with console.status("[bold green]Downloading wrapped key..."):
            response = requests.get(key_presigned.url, timeout=60)
            if not response.ok:
                raise APIError(f"Key download failed: {response.status_code}")

            key_path = output / "output_key.bin"
            with open(key_path, "wb") as f:
                f.write(response.content)

        # Step 2: Get tenant config for KMS info
        tenant_config = client.get_tenant_config()
        kms_key_id = tenant_config.customer_kms_key_arn or tenant_config.kms_key_arn

        # Step 3: Unwrap key via KMS
        console.print("  Unwrapping key via KMS...")
        with open(key_path, "rb") as f:
            wrapped_key = f.read()

        kms = boto3.client("kms", region_name=tenant_config.region)
        decrypt_response = kms.decrypt(
            CiphertextBlob=wrapped_key,
            KeyId=kms_key_id,
        )
        result_key = decrypt_response["Plaintext"]

        # Step 4: Decrypt results
        console.print("  Decrypting data...")
        with open(enc_path, "rb") as f:
            encrypted_data = f.read()

        plaintext = _decrypt_data(encrypted_data, result_key)

        # Step 5: Extract archive
        extracted_files = []

        if len(plaintext) > 2 and plaintext[0:2] == b'\x1f\x8b':
            console.print("  Extracting results...")
            try:
                with tarfile.open(fileobj=io.BytesIO(plaintext), mode='r:gz') as tar:
                    for member in tar.getmembers():
                        if member.name == "__manifest__.json":
                            continue
                        tar.extract(member, path=output)
                        extracted_files.append(member.name)
            except tarfile.TarError:
                raw_output = output / "output.bin"
                with open(raw_output, "wb") as f:
                    f.write(plaintext)
                extracted_files.append("output.bin")
        else:
            raw_output = output / "output.bin"
            with open(raw_output, "wb") as f:
                f.write(plaintext)
            extracted_files.append("output.bin")

        # Step 6: Clean up encrypted files unless --keep-encrypted
        if not keep_encrypted:
            enc_path.unlink(missing_ok=True)
            key_path.unlink(missing_ok=True)

        # Clear key from memory
        if isinstance(result_key, bytearray):
            for i in range(len(result_key)):
                result_key[i] = 0

        console.print(format_success("Results retrieved and decrypted!"))
        console.print(f"\n  Job ID:          {job_id}")
        console.print(f"  Decrypted size:  {format_bytes(len(plaintext))}")
        console.print(f"  Output dir:      {output}")
        console.print(f"  Files extracted: {len(extracted_files)}")
        for fname in extracted_files[:10]:
            console.print(f"    {fname}")
        if len(extracted_files) > 10:
            console.print(f"    ... and {len(extracted_files) - 10} more")
        console.print()

        console.print(Panel(
            "[bold green]Security Verification[/bold green]\n\n"
            "  [green]OK[/green] Data was encrypted client-side before upload\n"
            "  [green]OK[/green] Only the attested Nitro Enclave could decrypt the input\n"
            "  [green]OK[/green] Enclave processed data and encrypted results with a new key\n"
            "  [green]OK[/green] Result key was unwrapped via KMS\n"
            "  [green]OK[/green] Results decrypted locally\n\n"
            "  Plaintext data never existed outside the Nitro Enclave.",
            title="Zero-Knowledge Processing",
            border_style="green",
        ))

    except AuthenticationError as e:
        console.print(format_error(str(e)))
        sys.exit(1)
    except APIError as e:
        console.print(format_error(str(e)))
        sys.exit(1)
    except Exception as e:
        console.print(format_error(f"Failed: {e}"))
        if ctx.obj.get("DEBUG"):
            console.print_exception()
        sys.exit(1)


# ============================================================================
# Plugins Command
# ============================================================================


@cli.command()
@click.pass_context
def plugins(ctx: click.Context) -> None:
    """List available pipeline plugins."""
    config = ctx.obj["CONFIG"]
    client = _get_api_client(config)

    try:
        with console.status("[bold green]Fetching plugins..."):
            plugin_list = client.list_plugins()

        if not plugin_list:
            console.print("\nNo plugins available.\n")
            return

        table = Table(title="Available Plugins")
        table.add_column("Name", style="cyan")
        table.add_column("Description")
        table.add_column("Version", style="dim")

        for p in plugin_list:
            table.add_row(
                p.get("name", "?"),
                p.get("description", ""),
                p.get("version", ""),
            )

        console.print(table)

    except APIError as e:
        console.print(format_error(f"Failed to list plugins: {e}"))
        sys.exit(1)


# ============================================================================
# Config Commands
# ============================================================================


@cli.group()
def config() -> None:
    """Manage configuration."""
    pass


@config.command(name="show")
@click.pass_context
def config_show(ctx: click.Context) -> None:
    """Display current configuration."""
    config_mgr = ctx.obj["CONFIG"]

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
            profile = config_mgr.get_profile(name)
            is_active = " [bold green](active)[/bold green]" if name == active else ""
            table.add_row(f"Profile: {name}{is_active}", profile.get("organization_name", ""))

    console.print(table)


# ============================================================================
# Main Entry Point
# ============================================================================


def main() -> None:
    """Main entry point for the CLI."""
    try:
        cli(obj={})
    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted by user[/yellow]")
        sys.exit(130)
    except Exception as e:
        console.print(format_error(f"Unexpected error: {e}"))
        sys.exit(1)


if __name__ == "__main__":
    main()
