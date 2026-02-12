"""Status and auth endpoints."""

import asyncio

from fastapi import APIRouter, Request

from byod_cli import __version__

router = APIRouter(tags=["status"])


def _get_config(request: Request):
    return request.app.state.config


@router.get("/status")
async def get_status(request: Request):
    """Return auth status, profile info, tenant health, and API connectivity."""
    config = _get_config(request)

    profile_name = config.get_active_profile_name()
    profile_settings = {}
    if profile_name and config.profile_exists(profile_name):
        profile = config.get_profile(profile_name)
        profile_settings = profile.get("settings", {})

    result = {
        "authenticated": config.is_authenticated(),
        "profile": profile_name,
        "api_url": config.get_api_url(),
        "api_reachable": False,
        "version": __version__,
        # Tenant health fields
        "tenant_valid": False,
        "tenant_id": None,
        "tenant_error": None,
        # Resource state — validated against AWS, not just local config
        "kms_key_configured": False,
        "role_configured": False,
        "kms_key_error": None,
        "role_error": None,
    }

    # Verify AWS resources actually exist (not just saved in config)
    kms_key_arn = profile_settings.get("kms_key_arn")
    role_arn = profile_settings.get("role_arn")
    region = profile_settings.get("region", "us-east-1")

    if kms_key_arn or role_arn:
        try:
            import boto3
            from botocore.exceptions import ClientError

            if role_arn:
                # Extract role name from ARN: arn:aws:iam::123456:role/RoleName
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
                        result["role_error"] = f"Cannot verify role: {e}"
                except Exception as e:
                    result["role_error"] = f"AWS error: {e}"

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
                        result["kms_key_error"] = f"Cannot verify key: {e}"
                except Exception as e:
                    result["kms_key_error"] = f"AWS error: {e}"
        except ImportError:
            # boto3 not available — fall back to config check
            result["kms_key_configured"] = bool(kms_key_arn)
            result["role_configured"] = bool(role_arn)

    # Check API connectivity and tenant validity
    if config.is_authenticated():
        try:
            from byod_cli.api_client import APIClient, AuthenticationError

            client = APIClient(api_url=config.get_api_url(), api_key=config.get_api_key())
            auth_info = await asyncio.to_thread(client.verify_auth)
            result["api_reachable"] = True

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
            result["api_reachable"] = True  # Server responded, just auth failed
            result["tenant_error"] = (
                "API key is invalid or expired. "
                "Run 'byod auth login' to re-authenticate."
            )
        except Exception as e:
            err = str(e)
            if "connect" in err.lower() or "timeout" in err.lower():
                result["tenant_error"] = f"Cannot reach API server at {config.get_api_url()}"
            else:
                result["tenant_error"] = f"API error: {err}"

    return result


@router.get("/status/aws")
async def get_aws_status():
    """Check if AWS credentials are configured and validate them."""
    try:
        import boto3

        sts = boto3.client("sts")
        identity = await asyncio.to_thread(sts.get_caller_identity)
        return {
            "configured": True,
            "account": identity.get("Account"),
            "arn": identity.get("Arn"),
        }
    except Exception as e:
        return {
            "configured": False,
            "error": str(e),
        }
