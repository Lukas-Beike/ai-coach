"""Read-only transport for one Wahoo workout FIT file.

The summary ``file`` object of a workout carries a signed download URL. The URL
is a secret-like value: it is used for one plain GET on an allowlisted HTTPS host,
is never sent with an Authorization header, and never appears in an exception,
a log or a return value. Nothing is written to Wahoo.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any, Final
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import Request

from backend.providers.http import (
    ProviderResponseTooLarge,
    read_bounded_response,
    urlopen,
)

WAHOO_FIT_HOSTS: Final = frozenset({"cdn.wahooligan.com"})
MAX_WAHOO_FIT_BYTES: Final = 16 * 1024 * 1024
FIT_DOWNLOAD_TIMEOUT_SECONDS: Final = 30
WAHOO_FIT_REASONS: Final = frozenset(
    {"untrusted_url", "rate_limited", "rejected", "too_large", "unavailable"}
)
_UNAVAILABLE_MESSAGE: Final = "The Wahoo FIT file could not be downloaded."
_ACCEPT: Final = "application/octet-stream"
_USER_AGENT: Final = "IntervalsCoach"


class WahooFitUnavailable(Exception):
    """A FIT file could not be downloaded; ``reason`` names the class of failure."""

    def __init__(self, reason: str) -> None:
        super().__init__(_UNAVAILABLE_MESSAGE)
        self.reason = reason


def wahoo_fit_url(summary: object) -> str | None:
    """Return the download URL of a workout summary, or None when it has none."""
    if not isinstance(summary, Mapping):
        return None
    file = summary.get("file")
    if not isinstance(file, Mapping):
        return None
    url = file.get("url")
    return url if isinstance(url, str) else None


def _trusted_url(url: str) -> bool:
    if any(char.isspace() or not char.isprintable() for char in url):
        return False
    try:
        parsed = urlsplit(url)
        port = parsed.port
        hostname = (parsed.hostname or "").rstrip(".").casefold()
    except ValueError:
        return False
    return (
        parsed.scheme.casefold() == "https"
        and port in {None, 443}
        and "@" not in parsed.netloc
        and not parsed.fragment
        and hostname in WAHOO_FIT_HOSTS
    )


def _http_reason(status: int) -> str:
    if status == 429:
        return "rate_limited"
    if status >= 500:
        return "unavailable"
    return "rejected"


def download_wahoo_fit(
    url: str, *, opener: Callable[[Any, float], Any] = urlopen
) -> bytes:
    """Download one FIT file read-only; raise ``WahooFitUnavailable`` on failure.

    Failures are raised outside the handler that caught them, so no transport
    exception (and no URL it might carry) is chained to the raised error.
    """
    if not isinstance(url, str) or not _trusted_url(url):
        raise WahooFitUnavailable("untrusted_url")
    request = Request(
        url, headers={"Accept": _ACCEPT, "User-Agent": _USER_AGENT}, method="GET"
    )
    try:
        response = opener(request, FIT_DOWNLOAD_TIMEOUT_SECONDS)
    except HTTPError as error:
        error.close()
        reason = _http_reason(error.code)
    except OSError:
        reason = "unavailable"
    else:
        try:
            return read_bounded_response(response, MAX_WAHOO_FIT_BYTES)
        except ProviderResponseTooLarge:
            reason = "too_large"
        except OSError:
            reason = "unavailable"
        finally:
            response.close()
    raise WahooFitUnavailable(reason)
