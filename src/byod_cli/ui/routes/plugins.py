"""Plugin listing endpoint."""

import asyncio

from fastapi import APIRouter, HTTPException, Request

router = APIRouter(tags=["plugins"])


@router.get("/plugins")
async def list_plugins(request: Request):
    """List available processing plugins."""
    from byod_cli.api_client import APIClient

    config = request.app.state.config
    api_key = config.get_api_key()
    if not api_key:
        raise HTTPException(status_code=401, detail="Not authenticated")

    client = APIClient(api_url=config.get_api_url(), api_key=api_key)
    try:
        plugins = await asyncio.to_thread(client.list_plugins)
        return plugins
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e)) from e
