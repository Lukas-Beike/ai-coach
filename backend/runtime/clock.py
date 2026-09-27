"""System clock helpers shared by application assemblies."""

from datetime import datetime, timezone


def utc_now() -> str:
    """Return the current UTC time as an ISO 8601 timestamp."""
    return datetime.now(timezone.utc).isoformat()
