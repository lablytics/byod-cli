"""Settings and profile management endpoints."""

from fastapi import APIRouter, HTTPException, Request

router = APIRouter(tags=["settings"])


@router.get("/settings/profiles")
async def list_profiles(request: Request):
    """List all profiles with their details."""
    config = request.app.state.config
    active = config.get_active_profile_name()
    profiles = []

    for name in config.list_profiles():
        profile = config.get_profile(name)
        settings = profile.get("settings", {})
        profiles.append({
            "name": name,
            "active": name == active,
            "api_url": config.get_api_url(),
            "has_api_key": config.get_api_key() is not None,
            "settings": {k: str(v) for k, v in settings.items()},
        })

    return profiles


@router.post("/settings/profiles/{name}/activate")
async def activate_profile(request: Request, name: str):
    """Switch to a different profile."""
    config = request.app.state.config
    if not config.profile_exists(name):
        raise HTTPException(status_code=404, detail=f"Profile '{name}' not found")
    config.set_active_profile(name)
    return {"active": name}


@router.get("/settings/config")
async def get_config(request: Request):
    """Get the current configuration (sanitized — API key masked)."""
    config = request.app.state.config

    return {
        "config_path": str(config.config_file),
        "active_profile": config.get_active_profile_name(),
        "api_url": config.get_api_url(),
        "api_key_set": config.get_api_key() is not None,
    }
