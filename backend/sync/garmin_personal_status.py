"""Operating state of the Garmin Personal API key and the optional SDK login.

The Personal API key is renewed by hand in Garmin Connect Web, and Garmin does
not report its expiry, so the athlete enters the date with the key. The card
warns ahead of that date. With a key configured, a failed SDK login only drops
the SDK-only families; the last such skip is kept so the card can ask for a new
Garmin login. No projection here carries the key, a token or an error text.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Final

# Days before the entered expiry date from which the card warns.
PERSONAL_KEY_WARNING_DAYS: Final = 14
SDK_SKIPPED_KEY: Final = "garmin_sdk_skipped"
SDK_SKIP_REASONS: Final = frozenset({"login_failed", "mfa_required"})

KEY_VALID: Final = "valid"
KEY_EXPIRING: Final = "expiring"
KEY_EXPIRED: Final = "expired"
KEY_EXPIRY_MISSING: Final = "expiry_missing"
# Garmin refused the last key exchange; wins over every expiry state.
KEY_REJECTED: Final = "rejected"


def _expiry_date(value: object) -> date | None:
    try:
        return date.fromisoformat(str(value or "").strip())
    except ValueError:
        return None


def personal_key_state(
    config: Any, today: date, *, rejected: bool = False
) -> dict[str, Any]:
    """Project the key's configured flag and expiry without the key itself."""
    if not str(getattr(config, "garmin_personal_api_key", "") or "").strip():
        return {"configured": False}
    expires = _expiry_date(getattr(config, "garmin_personal_api_key_expires", ""))
    if expires is None:
        return {
            "configured": True,
            "state": KEY_REJECTED if rejected else KEY_EXPIRY_MISSING,
            "expires_on": None,
            "days_left": None,
        }
    days_left = (expires - today).days
    if rejected:
        state = KEY_REJECTED
    elif days_left < 0:
        state = KEY_EXPIRED
    elif days_left <= PERSONAL_KEY_WARNING_DAYS:
        state = KEY_EXPIRING
    else:
        state = KEY_VALID
    return {
        "configured": True,
        "state": state,
        "expires_on": expires.isoformat(),
        "days_left": days_left,
    }


def sdk_skipped_view(raw: object) -> dict[str, str] | None:
    """Decode the stored SDK skip, keeping only the known reason and time."""
    if not isinstance(raw, dict):
        return None
    reason = raw.get("reason")
    at = raw.get("at")
    if reason not in SDK_SKIP_REASONS or not isinstance(at, str):
        return None
    return {"reason": str(reason), "at": at}
