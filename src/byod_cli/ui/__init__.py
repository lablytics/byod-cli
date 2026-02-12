"""BYOD Local Web UI — graphical companion for the CLI."""

import threading
import webbrowser


def launch_ui(host: str = "127.0.0.1", port: int = 8420, open_browser: bool = True) -> None:
    """Launch the local web UI server."""
    import uvicorn

    from byod_cli.ui.server import app

    url = f"http://{host}:{port}"

    if open_browser:

        def _open():
            import time

            time.sleep(1.5)
            webbrowser.open(url)

        threading.Thread(target=_open, daemon=True).start()

    print(f"\n  BYOD Local UI: {url}")
    print("  Press Ctrl+C to stop\n")
    uvicorn.run(app, host=host, port=port, log_level="warning")
