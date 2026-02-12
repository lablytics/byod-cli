"""FastAPI server for the BYOD Local UI."""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from byod_cli.ui.routes import jobs, plugins, settings, setup, status, submit


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize shared state on startup."""
    from byod_cli.config import ConfigManager

    app.state.config = ConfigManager()
    yield


app = FastAPI(title="BYOD Local UI", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register API routes
app.include_router(status.router, prefix="/api")
app.include_router(jobs.router, prefix="/api")
app.include_router(plugins.router, prefix="/api")
app.include_router(submit.router, prefix="/api")
app.include_router(setup.router, prefix="/api")
app.include_router(settings.router, prefix="/api")

# Serve React SPA from static/ directory
static_dir = Path(__file__).parent / "static"
if static_dir.exists():
    assets_dir = static_dir / "assets"
    if assets_dir.exists():
        app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="assets")

    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str):
        """Serve the React SPA — return index.html for client-side routes."""
        file_path = static_dir / full_path
        if file_path.exists() and file_path.is_file():
            return FileResponse(str(file_path))
        return FileResponse(str(static_dir / "index.html"))
