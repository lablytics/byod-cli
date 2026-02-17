"""Setup wizard endpoints."""

import asyncio
import json
import logging

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from byod_cli.ui.routes import sse_event

logger = logging.getLogger(__name__)

router = APIRouter(tags=["setup"])


@router.get("/setup/status")
async def setup_status(request: Request):
    """Check the current setup state, including tenant health."""
    config = request.app.state.config

    result = {
        "authenticated": config.is_authenticated(),
        "aws_configured": False,
        "aws_account_id": None,
        "tenant_valid": False,
        "tenant_id": None,
        "tenant_error": None,
        "kms_key_configured": False,
        "kms_key_arn": None,
        "kms_key_error": None,
        "role_configured": False,
        "role_arn": None,
        "role_error": None,
        "registered": False,
    }

    # Check AWS credentials
    try:
        import boto3

        sts = boto3.client("sts")
        identity = await asyncio.to_thread(sts.get_caller_identity)
        result["aws_configured"] = True
        result["aws_account_id"] = identity.get("Account")
    except Exception:
        pass

    # Check tenant health via API
    if config.is_authenticated():
        try:
            from byod_cli.api_client import APIClient, AuthenticationError

            client = APIClient(api_url=config.get_api_url(), api_key=config.get_api_key())
            auth_info = await asyncio.to_thread(client.verify_auth)

            tenant_id = auth_info.get("tenant_id")
            if tenant_id:
                result["tenant_valid"] = True
                result["tenant_id"] = tenant_id
            else:
                result["tenant_error"] = (
                    "Your account is not associated with a tenant. "
                    "The tenant may have been deleted. Re-run onboarding on the dashboard."
                )
        except AuthenticationError:
            result["tenant_error"] = (
                "API key is invalid or expired. "
                "Run 'byod auth login' to re-authenticate."
            )
        except Exception as e:
            logger.warning("Tenant verification failed: %s", e)
            err = str(e).lower()
            if "connect" in err or "timeout" in err:
                result["tenant_error"] = "Cannot reach API server. Check your network connection."
            else:
                result["tenant_error"] = "Failed to verify tenant. Check your API key and network."

    # Verify KMS key and role actually exist in AWS (not just in local config)
    profile_name = config.get_active_profile_name()
    kms_key_arn = None
    role_arn = None
    region = "us-east-1"

    if profile_name and config.profile_exists(profile_name):
        profile = config.get_profile(profile_name)
        settings = profile.get("settings", {})
        kms_key_arn = settings.get("kms_key_arn")
        role_arn = settings.get("role_arn")
        region = settings.get("region", "us-east-1")
        result["kms_key_arn"] = kms_key_arn
        result["role_arn"] = role_arn

    if result["aws_configured"] and (kms_key_arn or role_arn):
        import boto3
        from botocore.exceptions import ClientError

        if role_arn:
            role_name = role_arn.rsplit("/", 1)[-1] if "/" in role_arn else role_arn
            try:
                iam = boto3.client("iam")
                await asyncio.to_thread(iam.get_role, RoleName=role_name)
                result["role_configured"] = True
            except ClientError as e:
                code = e.response["Error"]["Code"]
                if code == "NoSuchEntity":
                    result["role_error"] = "IAM role no longer exists in AWS"
                else:
                    logger.warning("Cannot verify IAM role: %s", e)
                    result["role_error"] = "Cannot verify role. Check AWS credentials."
            except Exception as e:
                logger.warning("AWS error checking role: %s", e)
                result["role_error"] = "AWS error checking role. Check credentials and network."

        if kms_key_arn:
            try:
                kms = boto3.client("kms", region_name=region)
                key_info = await asyncio.to_thread(kms.describe_key, KeyId=kms_key_arn)
                key_state = key_info["KeyMetadata"].get("KeyState", "")
                if key_state == "Enabled":
                    result["kms_key_configured"] = True
                elif key_state == "PendingDeletion":
                    result["kms_key_error"] = "KMS key is scheduled for deletion"
                elif key_state == "Disabled":
                    result["kms_key_error"] = "KMS key is disabled"
                else:
                    result["kms_key_error"] = f"KMS key state: {key_state}"
            except ClientError as e:
                code = e.response["Error"]["Code"]
                if code == "NotFoundException":
                    result["kms_key_error"] = "KMS key no longer exists in AWS"
                else:
                    logger.warning("Cannot verify KMS key: %s", e)
                    result["kms_key_error"] = "Cannot verify KMS key. Check AWS credentials."
            except Exception as e:
                logger.warning("AWS error checking KMS key: %s", e)
                result["kms_key_error"] = "AWS error checking KMS key. Check credentials and network."

    # Only mark registered if both actually exist
    if result["kms_key_configured"] and result["role_configured"]:
        result["registered"] = True

    return result


class SetupRequest(BaseModel):
    region: str = "us-east-1"
    force_new: bool = False


@router.post("/setup/run")
async def run_setup(request: Request, body: SetupRequest):
    """Run the full setup flow. Returns SSE progress stream.

    Mirrors the CLI `byod setup` command logic including:
    - Multi-PCR0 support for rolling enclave updates
    - force_new to tear down and recreate resources
    - Proper KMS attestation policy (4 statements)
    - IAM propagation wait
    """
    config = request.app.state.config

    if not config.is_authenticated():
        raise HTTPException(status_code=401, detail="Not authenticated. Run 'byod auth login' first.")

    async def _stream():
        try:
            yield sse_event("progress", {"stage": "checking", "percent": 5, "message": "Checking prerequisites..."})

            # Verify auth and get tenant info
            from byod_cli.api_client import APIClient

            api_key = config.get_api_key()
            client = APIClient(api_url=config.get_api_url(), api_key=api_key)

            auth_info = await asyncio.to_thread(client.verify_auth)
            tenant_id = auth_info.get("tenant_id")
            if not tenant_id:
                yield sse_event("error", {
                    "message": "Your account is not associated with a tenant. "
                    "Please complete onboarding on the dashboard first.",
                })
                return

            yield sse_event("progress", {"stage": "aws", "percent": 10, "message": "Verifying AWS credentials..."})

            import boto3
            from botocore.exceptions import ClientError

            sts = boto3.client("sts", region_name=body.region)
            identity = await asyncio.to_thread(sts.get_caller_identity)
            aws_account_id = identity["Account"]

            yield sse_event("progress", {"stage": "enclave", "percent": 18, "message": "Getting enclave information..."})

            enclave_info = await asyncio.to_thread(client.get_enclave_info)
            # Support multi-PCR0: prefer pcr0_values array, fall back to single pcr0
            pcr0_values = enclave_info.get("pcr0_values") or [enclave_info["pcr0"]]
            lablytics_account_id = enclave_info["account_id"]

            iam_role_name = f"BYODEnclaveRole-{tenant_id[:16]}"
            alias_name = f"alias/byod-{tenant_id[:16]}"

            iam = boto3.client("iam", region_name=body.region)
            kms = boto3.client("kms", region_name=body.region)

            # Force-new: tear down existing resources first
            if body.force_new:
                yield sse_event("progress", {"stage": "cleanup", "percent": 22, "message": "Deleting existing resources..."})

                # Delete IAM role (must remove policies first)
                try:
                    policies = await asyncio.to_thread(
                        iam.list_role_policies, RoleName=iam_role_name,
                    )
                    for policy_name in policies.get("PolicyNames", []):
                        await asyncio.to_thread(
                            iam.delete_role_policy,
                            RoleName=iam_role_name,
                            PolicyName=policy_name,
                        )
                    attached = await asyncio.to_thread(
                        iam.list_attached_role_policies, RoleName=iam_role_name,
                    )
                    for policy in attached.get("AttachedPolicies", []):
                        await asyncio.to_thread(
                            iam.detach_role_policy,
                            RoleName=iam_role_name,
                            PolicyArn=policy["PolicyArn"],
                        )
                    await asyncio.to_thread(iam.delete_role, RoleName=iam_role_name)
                except ClientError as e:
                    if e.response["Error"]["Code"] != "NoSuchEntity":
                        logger.warning("Could not delete IAM role during cleanup: %s", e)
                        yield sse_event("progress", {
                            "stage": "cleanup",
                            "percent": 24,
                            "message": "Warning: could not delete existing IAM role",
                        })

                # Schedule KMS key for deletion via alias
                try:
                    alias_resp = await asyncio.to_thread(kms.describe_key, KeyId=alias_name)
                    key_id = alias_resp["KeyMetadata"]["KeyId"]
                    await asyncio.to_thread(kms.delete_alias, AliasName=alias_name)
                    await asyncio.to_thread(
                        kms.schedule_key_deletion,
                        KeyId=key_id,
                        PendingWindowInDays=7,
                    )
                except ClientError as e:
                    if e.response["Error"]["Code"] != "NotFoundException":
                        logger.warning("Could not delete KMS key during cleanup: %s", e)
                        yield sse_event("progress", {
                            "stage": "cleanup",
                            "percent": 26,
                            "message": "Warning: could not delete existing KMS key",
                        })

                yield sse_event("progress", {"stage": "cleanup_done", "percent": 28, "message": "Existing resources cleaned up"})

            # Create cross-account IAM role
            yield sse_event("progress", {"stage": "iam_role", "percent": 35, "message": "Creating cross-account IAM role..."})

            trust_policy = {
                "Version": "2012-10-17",
                "Statement": [{
                    "Effect": "Allow",
                    "Principal": {"AWS": f"arn:aws:iam::{lablytics_account_id}:root"},
                    "Action": "sts:AssumeRole",
                    "Condition": {"StringEquals": {"sts:ExternalId": tenant_id}},
                }],
            }

            try:
                role_resp = await asyncio.to_thread(
                    iam.create_role,
                    RoleName=iam_role_name,
                    AssumeRolePolicyDocument=json.dumps(trust_policy),
                    Description=f"Allows BYOD enclave to access KMS key (tenant: {tenant_id})",
                    Tags=[
                        {"Key": "Purpose", "Value": "BYOD-CrossAccountAccess"},
                        {"Key": "TenantId", "Value": tenant_id},
                    ],
                )
                role_arn = role_resp["Role"]["Arn"]

                # Wait for IAM role to propagate (eventual consistency)
                yield sse_event("progress", {"stage": "iam_propagation", "percent": 42, "message": "Waiting for IAM role to propagate..."})
                await asyncio.sleep(10)
            except ClientError as e:
                if e.response["Error"]["Code"] == "EntityAlreadyExists":
                    role_arn = f"arn:aws:iam::{aws_account_id}:role/{iam_role_name}"
                    # Update trust policy on existing role
                    await asyncio.to_thread(
                        iam.update_assume_role_policy,
                        RoleName=iam_role_name,
                        PolicyDocument=json.dumps(trust_policy),
                    )
                else:
                    logger.exception("Failed to create IAM role")
                    yield sse_event("error", {"message": "Failed to create IAM role. Check your AWS permissions."})
                    return

            # Create KMS key with attestation policy (4 statements, matching CLI)
            yield sse_event("progress", {"stage": "kms_key", "percent": 50, "message": "Creating KMS key with attestation policy..."})

            key_policy = {
                "Version": "2012-10-17",
                "Statement": [
                    # Customer admin — all management actions EXCEPT Decrypt
                    {
                        "Sid": "CustomerAdmin",
                        "Effect": "Allow",
                        "Principal": {"AWS": f"arn:aws:iam::{aws_account_id}:root"},
                        "Action": [
                            "kms:Create*", "kms:Describe*", "kms:Enable*", "kms:List*",
                            "kms:Put*", "kms:Update*", "kms:Revoke*", "kms:Disable*",
                            "kms:Get*", "kms:Delete*", "kms:TagResource", "kms:UntagResource",
                            "kms:ScheduleKeyDeletion", "kms:CancelKeyDeletion",
                            "kms:Encrypt", "kms:GenerateDataKey",
                            "kms:GenerateDataKeyWithoutPlaintext",
                        ],
                        "Resource": "*",
                    },
                    # Customer can decrypt — but NOT the cross-account role
                    {
                        "Sid": "CustomerDecrypt",
                        "Effect": "Allow",
                        "Principal": {"AWS": f"arn:aws:iam::{aws_account_id}:root"},
                        "Action": "kms:Decrypt",
                        "Resource": "*",
                        "Condition": {"ArnNotEquals": {"aws:PrincipalArn": role_arn}},
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
                    {
                        "Sid": "RoleDecryptWithAttestation",
                        "Effect": "Allow",
                        "Principal": {"AWS": role_arn},
                        "Action": "kms:Decrypt",
                        "Resource": "*",
                        "Condition": {
                            "StringEqualsIgnoreCase": {
                                "kms:RecipientAttestation:PCR0": pcr0_values,
                            },
                        },
                    },
                ],
            }

            try:
                key_resp = await asyncio.to_thread(
                    kms.create_key,
                    Policy=json.dumps(key_policy),
                    Description=f"BYOD encryption key (tenant: {tenant_id})",
                    KeyUsage="ENCRYPT_DECRYPT",
                    Tags=[
                        {"TagKey": "Purpose", "TagValue": "BYOD-DataEncryption"},
                        {"TagKey": "TenantId", "TagValue": tenant_id},
                    ],
                )
                kms_key_arn = key_resp["KeyMetadata"]["Arn"]
                key_id = key_resp["KeyMetadata"]["KeyId"]

                # Create alias for easier identification
                try:
                    await asyncio.to_thread(
                        kms.create_alias, AliasName=alias_name, TargetKeyId=key_id,
                    )
                except ClientError:
                    pass  # Alias might already exist
            except ClientError:
                logger.exception("KMS key creation failed")
                yield sse_event("error", {"message": "Failed to create KMS key. Check your AWS permissions."})
                return

            # Attach KMS permissions to the IAM role
            yield sse_event("progress", {"stage": "iam_policy", "percent": 68, "message": "Attaching KMS permissions to role..."})

            role_policy = {
                "Version": "2012-10-17",
                "Statement": [{
                    "Effect": "Allow",
                    "Action": ["kms:GenerateDataKey", "kms:Decrypt", "kms:DescribeKey"],
                    "Resource": kms_key_arn,
                }],
            }
            try:
                await asyncio.to_thread(
                    iam.put_role_policy,
                    RoleName=iam_role_name,
                    PolicyName="BYODKMSAccess",
                    PolicyDocument=json.dumps(role_policy),
                )
            except ClientError:
                logger.exception("Failed to attach KMS policy to IAM role")
                yield sse_event("error", {"message": "Failed to attach KMS permissions to role. Check your AWS permissions."})
                return

            # Register with Lablytics
            yield sse_event("progress", {"stage": "registering", "percent": 82, "message": "Registering with Lablytics..."})

            try:
                await asyncio.to_thread(
                    client.register_kms_setup,
                    kms_key_arn=kms_key_arn,
                    role_arn=role_arn,
                    aws_account_id=aws_account_id,
                    region=body.region,
                )
            except Exception:
                logger.exception("Registration with Lablytics failed")
                yield sse_event("error", {
                    "message": "Registration failed. "
                    "AWS resources were created but not registered with Lablytics. "
                    "Check the CLI logs for details.",
                })
                return

            # Save to local config
            yield sse_event("progress", {"stage": "saving", "percent": 93, "message": "Saving configuration..."})

            profile_name = config.get_active_profile_name()
            if profile_name:
                config.update_profile_setting(profile_name, "kms_key_arn", kms_key_arn)
                config.update_profile_setting(profile_name, "role_arn", role_arn)
                config.update_profile_setting(profile_name, "aws_account_id", aws_account_id)
                config.update_profile_setting(profile_name, "region", body.region)

            yield sse_event("progress", {"stage": "done", "percent": 100, "message": "Setup complete!"})
            yield sse_event("complete", {
                "kms_key_arn": kms_key_arn,
                "role_arn": role_arn,
                "aws_account_id": aws_account_id,
                "region": body.region,
            })
        except Exception:
            logger.exception("Setup failed unexpectedly")
            yield sse_event("error", {"message": "An unexpected error occurred during setup. Check the CLI logs for details."})

    return StreamingResponse(_stream(), media_type="text/event-stream")


