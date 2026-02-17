"""
CLI UI route modules.

Shared utilities are in this package init to avoid circular imports.
"""

import json


def sse_event(event: str, data: dict) -> str:
    """Format a Server-Sent Event message.

    Used by submit, jobs, and setup routes for streaming progress updates.
    """
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"
