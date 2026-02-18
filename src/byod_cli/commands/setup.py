"""
Setup commands for BYOD CLI.

Contains: setup, update-policy, teardown — all AWS resource management.
"""

from __future__ import annotations

import json
import sys

import click

from byod_cli.api_client import APIError
from byod_cli.commands import _helpers

EXIT_ERROR = _helpers.EXIT_ERROR


@click.command()
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
    client = _helpers._get_api_client(config)
    console = _helpers.console

    console.print("\n[bold blue]Setting up AWS resources for BYOD...[/bold blue]\n")

    # Step 1: Get enclave info from Lablytics
    console.print("[dim]Fetching enclave configuration...[/dim]")
    try:
        enclave_info = client.get_enclave_info()
        pcr0_values = enclave_info.get("pcr0_values") or [enclave_info["pcr0"]]
        lablytics_account_id = enclave_info["account_id"]
        tenant_id = enclave_info["tenant_id"]
    except APIError as e:
        console.print(_helpers.format_error(f"Failed to get enclave info: {e}"))
        sys.exit(EXIT_ERROR)

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
        console.print(_helpers.format_error(
            "AWS credentials not found. Run 'aws configure' or set "
            "AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY environment variables."
        ))
        if ctx.obj.get("DEBUG"):
            console.print(f"\n  [dim]{e}[/dim]")
        sys.exit(EXIT_ERROR)

    role_name = f"BYODEnclaveRole-{tenant_id[:16]}"
    alias_name = f"alias/byod-{tenant_id[:16]}"

    # Step 2.5: If --new flag, delete existing resources first
    if force_new:
        _delete_existing_resources(console, region, role_name, alias_name)

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

        console.print("  [dim]Waiting for IAM role to propagate...[/dim]")
        import time
        time.sleep(10)
    except ClientError as e:
        if e.response["Error"]["Code"] == "EntityAlreadyExists":
            role_arn = f"arn:aws:iam::{customer_account_id}:role/{role_name}"
            console.print(f"  Role already exists: {role_arn}")
        else:
            console.print(_helpers.format_error(f"Failed to create IAM role: {e}"))
            sys.exit(EXIT_ERROR)

    # Step 4: Create KMS key with attestation policy
    console.print("\n[dim]Creating KMS key with attestation policy...[/dim]")

    key_policy = _build_kms_key_policy(customer_account_id, role_arn, pcr0_values)

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

        try:
            kms.create_alias(AliasName=alias_name, TargetKeyId=key_id)
            console.print(f"  Alias: {alias_name}")
        except ClientError:
            pass
    except ClientError as e:
        console.print(_helpers.format_error(f"KMS operation failed: {e}"))
        console.print("\n  Check that your AWS user has kms:CreateKey and kms:PutKeyPolicy permissions.")
        sys.exit(EXIT_ERROR)

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
        console.print(_helpers.format_error(f"Failed to attach policy: {e}"))
        sys.exit(EXIT_ERROR)

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
        console.print(_helpers.format_error(f"Failed to register with Lablytics: {e}"))
        console.print("\n[yellow]AWS resources were created but not registered.[/yellow]")
        console.print("You may need to manually configure KMS in the dashboard settings.")
        sys.exit(EXIT_ERROR)

    active_profile = config.get_active_profile_name()
    if active_profile:
        config.update_profile_setting(active_profile, "kms_key_arn", key_arn)
        config.update_profile_setting(active_profile, "role_arn", role_arn)
        config.update_profile_setting(active_profile, "aws_account_id", customer_account_id)

    console.print("\n" + "=" * 60)
    console.print(_helpers.format_success("Setup complete!"))
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


@click.command("update-policy")
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
    client = _helpers._get_api_client(config)
    console = _helpers.console

    console.print("\n[bold blue]Updating KMS key policy with latest PCR0 values...[/bold blue]\n")

    active_profile = config.get_active_profile_name()
    if not active_profile:
        console.print(_helpers.format_error("No active profile. Run 'byod setup' first."))
        sys.exit(EXIT_ERROR)

    profile = config.get_profile(active_profile)
    kms_key_arn = profile.get("settings", {}).get("kms_key_arn")
    role_arn = profile.get("settings", {}).get("role_arn")

    if not kms_key_arn:
        console.print(_helpers.format_error(
            "No KMS key ARN found in config. Run 'byod setup' first, "
            "or re-run with --new to recreate resources."
        ))
        sys.exit(EXIT_ERROR)

    console.print(f"  KMS Key: {kms_key_arn}")
    console.print(f"  Role:    {role_arn}")

    console.print("\n[dim]Fetching latest PCR0 values...[/dim]")
    try:
        enclave_info = client.get_enclave_info()
        pcr0_values = enclave_info.get("pcr0_values") or [enclave_info["pcr0"]]
    except APIError as e:
        console.print(_helpers.format_error(f"Failed to get enclave info: {e}"))
        sys.exit(EXIT_ERROR)

    console.print(f"  Active PCR0 values: {len(pcr0_values)}")
    for i, v in enumerate(pcr0_values):
        console.print(f"    [{i+1}] {v[:16]}...")

    console.print("\n[dim]Reading current key policy...[/dim]")
    try:
        kms = boto3.client("kms", region_name=region)
        policy_response = kms.get_key_policy(KeyId=kms_key_arn, PolicyName="default")
        current_policy = json.loads(policy_response["Policy"])
    except ClientError as e:
        console.print(_helpers.format_error(f"Failed to read key policy: {e}"))
        sys.exit(EXIT_ERROR)

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
        console.print(_helpers.format_error(
            "Could not find RoleDecryptWithAttestation statement in key policy. "
            "The key policy may have been modified manually."
        ))
        sys.exit(EXIT_ERROR)

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
        console.print(_helpers.format_success("\nKey policy updated successfully!"))
    except ClientError as e:
        console.print(_helpers.format_error(f"Failed to update key policy: {e}"))
        sys.exit(EXIT_ERROR)

    console.print(f"\n  Your KMS key now allows decryption from {len(pcr0_values)} enclave(s).")
    console.print("  You can verify by running: [cyan]byod update-policy[/cyan] again.\n")


@click.command()
@click.option("--region", default="us-east-1", help="AWS region where resources were created")
@click.option("--keep-days", default=7, type=click.IntRange(7, 30),
              help="Days before KMS key is permanently deleted (7-30)")
@click.confirmation_option(prompt="This will delete your BYOD KMS key and IAM role. Continue?")
@click.pass_context
def teardown(ctx: click.Context, region: str, keep_days: int) -> None:
    """
    Remove AWS resources created by `byod setup`.

    \b
    This command deletes from YOUR AWS account:
    1. The cross-account IAM role (immediate)
    2. The KMS key alias (immediate)
    3. Schedules the KMS key for deletion (7-30 day waiting period)

    \b
    The KMS key deletion has a mandatory waiting period (default 7 days).
    During this window you can cancel deletion via the AWS Console.

    \b
    Example:
        byod teardown
        byod teardown --region us-west-2
        byod teardown --keep-days 30   # 30-day safety window
    """
    import boto3
    from botocore.exceptions import ClientError

    config = ctx.obj["CONFIG"]
    client = _helpers._get_api_client(config)
    console = _helpers.console

    console.print("\n[bold red]Tearing down BYOD AWS resources...[/bold red]\n")

    console.print("[dim]Fetching tenant info...[/dim]")
    try:
        enclave_info = client.get_enclave_info()
        tenant_id = enclave_info["tenant_id"]
    except APIError as e:
        console.print(_helpers.format_error(f"Failed to get tenant info: {e}"))
        sys.exit(EXIT_ERROR)

    role_name = f"BYODEnclaveRole-{tenant_id[:16]}"
    alias_name = f"alias/byod-{tenant_id[:16]}"

    try:
        sts = boto3.client("sts", region_name=region)
        identity = sts.get_caller_identity()
        console.print(f"  AWS Account: {identity['Account']}")
        console.print(f"  Region: {region}")
    except ClientError:
        console.print(_helpers.format_error(
            "AWS credentials not found. Run 'aws configure' or set "
            "AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY environment variables."
        ))
        sys.exit(EXIT_ERROR)

    iam = boto3.client("iam", region_name=region)
    kms = boto3.client("kms", region_name=region)
    deleted_role = False
    deleted_key = False

    console.print(f"\n[dim]Deleting IAM role: {role_name}[/dim]")
    try:
        policies = iam.list_role_policies(RoleName=role_name)
        for policy_name in policies.get("PolicyNames", []):
            console.print(f"  Removing inline policy: {policy_name}")
            iam.delete_role_policy(RoleName=role_name, PolicyName=policy_name)
        attached = iam.list_attached_role_policies(RoleName=role_name)
        for policy in attached.get("AttachedPolicies", []):
            console.print(f"  Detaching policy: {policy['PolicyArn']}")
            iam.detach_role_policy(RoleName=role_name, PolicyArn=policy["PolicyArn"])
        iam.delete_role(RoleName=role_name)
        console.print(_helpers.format_success(f"  IAM role deleted: {role_name}"))
        deleted_role = True
    except ClientError as e:
        if e.response["Error"]["Code"] == "NoSuchEntity":
            console.print(f"  IAM role {role_name} does not exist (already deleted)")
            deleted_role = True
        else:
            console.print(_helpers.format_error(f"  Failed to delete IAM role: {e}"))

    console.print("\n[dim]Scheduling KMS key for deletion...[/dim]")
    try:
        alias_response = kms.describe_key(KeyId=alias_name)
        key_id = alias_response["KeyMetadata"]["KeyId"]
        key_arn = alias_response["KeyMetadata"]["Arn"]
        key_state = alias_response["KeyMetadata"]["KeyState"]
        if key_state == "PendingDeletion":
            console.print(f"  KMS key already pending deletion: {key_arn}")
            deleted_key = True
        else:
            console.print(f"  Deleting alias: {alias_name}")
            kms.delete_alias(AliasName=alias_name)
            kms.schedule_key_deletion(KeyId=key_id, PendingWindowInDays=keep_days)
            console.print(_helpers.format_success(
                f"  KMS key scheduled for deletion in {keep_days} days: {key_arn}"
            ))
            console.print(f"  [yellow]To cancel: aws kms cancel-key-deletion --key-id {key_id}[/yellow]")
            deleted_key = True
    except ClientError as e:
        if e.response["Error"]["Code"] == "NotFoundException":
            console.print(f"  KMS key with alias {alias_name} does not exist (already deleted)")
            deleted_key = True
        else:
            console.print(_helpers.format_error(f"  Failed to schedule KMS key deletion: {e}"))

    active_profile = config.get_active_profile_name()
    if active_profile:
        for setting in ("kms_key_arn", "role_arn", "aws_account_id"):
            try:
                config.update_profile_setting(active_profile, setting, None)
            except Exception:
                pass
        console.print("\n  Local config cleared.")

    console.print("\n" + "=" * 60)
    if deleted_role and deleted_key:
        console.print(_helpers.format_success("Teardown complete!"))
        console.print("=" * 60)
        console.print("\n  IAM role: deleted")
        console.print(f"  KMS key: pending deletion ({keep_days} day waiting period)")
        console.print("\n  To re-setup later: [cyan]byod setup[/cyan]")
    else:
        console.print(_helpers.format_warning("Teardown partially completed. Check errors above."))
        console.print("=" * 60)
    console.print("")


def _delete_existing_resources(console, region: str, role_name: str, alias_name: str) -> None:
    """Delete existing AWS resources when --new flag is used."""
    import boto3
    from botocore.exceptions import ClientError

    console.print("\n[bold yellow]--new flag specified: Deleting existing resources...[/bold yellow]")
    iam = boto3.client("iam", region_name=region)
    kms = boto3.client("kms", region_name=region)

    try:
        policies = iam.list_role_policies(RoleName=role_name)
        for policy_name in policies.get("PolicyNames", []):
            console.print(f"  Deleting inline policy: {policy_name}")
            iam.delete_role_policy(RoleName=role_name, PolicyName=policy_name)
        attached = iam.list_attached_role_policies(RoleName=role_name)
        for policy in attached.get("AttachedPolicies", []):
            console.print(f"  Detaching policy: {policy['PolicyArn']}")
            iam.detach_role_policy(RoleName=role_name, PolicyArn=policy["PolicyArn"])
        console.print(f"  Deleting IAM role: {role_name}")
        iam.delete_role(RoleName=role_name)
        console.print("  [green]IAM role deleted[/green]")
    except ClientError as e:
        if e.response["Error"]["Code"] == "NoSuchEntity":
            console.print(f"  IAM role {role_name} does not exist (OK)")
        else:
            console.print(_helpers.format_warning(f"Could not delete IAM role: {e}"))

    try:
        alias_response = kms.describe_key(KeyId=alias_name)
        key_id = alias_response["KeyMetadata"]["KeyId"]
        key_arn = alias_response["KeyMetadata"]["Arn"]
        console.print(f"  Deleting KMS alias: {alias_name}")
        kms.delete_alias(AliasName=alias_name)
        console.print(f"  Scheduling KMS key for deletion: {key_arn}")
        kms.schedule_key_deletion(KeyId=key_id, PendingWindowInDays=7)
        console.print("  [green]KMS key scheduled for deletion (7 days)[/green]")
    except ClientError as e:
        if e.response["Error"]["Code"] == "NotFoundException":
            console.print(f"  KMS key with alias {alias_name} does not exist (OK)")
        else:
            console.print(_helpers.format_warning(f"Could not delete KMS key: {e}"))
    console.print("")


def _build_kms_key_policy(customer_account_id: str, role_arn: str, pcr0_values: list[str]) -> dict:
    """Build the KMS key policy with attestation enforcement."""
    return {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "CustomerAdmin",
                "Effect": "Allow",
                "Principal": {"AWS": f"arn:aws:iam::{customer_account_id}:root"},
                "Action": [
                    "kms:Create*", "kms:Describe*", "kms:Enable*", "kms:List*",
                    "kms:Put*", "kms:Update*", "kms:Revoke*", "kms:Disable*",
                    "kms:Get*", "kms:Delete*", "kms:TagResource", "kms:UntagResource",
                    "kms:ScheduleKeyDeletion", "kms:CancelKeyDeletion",
                    "kms:Encrypt", "kms:GenerateDataKey", "kms:GenerateDataKeyWithoutPlaintext",
                ],
                "Resource": "*",
            },
            {
                "Sid": "CustomerDecrypt",
                "Effect": "Allow",
                "Principal": {"AWS": f"arn:aws:iam::{customer_account_id}:root"},
                "Action": "kms:Decrypt",
                "Resource": "*",
                "Condition": {"ArnNotEquals": {"aws:PrincipalArn": role_arn}},
            },
            {
                "Sid": "RoleOperations",
                "Effect": "Allow",
                "Principal": {"AWS": role_arn},
                "Action": ["kms:GenerateDataKey", "kms:DescribeKey"],
                "Resource": "*",
            },
            {
                "Sid": "RoleDecryptWithAttestation",
                "Effect": "Allow",
                "Principal": {"AWS": role_arn},
                "Action": "kms:Decrypt",
                "Resource": "*",
                "Condition": {
                    "StringEqualsIgnoreCase": {
                        "kms:RecipientAttestation:PCR0": pcr0_values
                    }
                },
            },
        ],
    }
