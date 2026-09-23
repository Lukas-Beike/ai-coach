"""Safe static asset projections for the public Coach client."""

from __future__ import annotations

import hashlib
import mimetypes
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from backend.errors import AppError

ASSET_INDEX_HTML = "index.html"
ASSET_API_JS = "api.js"
ASSET_APP_JS = "app.js"
ASSET_NAVIGATION_JS = "navigation.js"
ASSET_STATE_JS = "state.js"
ASSET_VIEWS_JS = "views.js"
ASSET_FORMS_JS = "forms.js"
ASSET_COMPONENTS_JS = "components.js"
ASSET_STYLES_CSS = "styles.css"
ASSET_SERVICE_WORKER_JS = "service-worker.js"
ASSET_MANIFEST = "manifest.webmanifest"
ASSET_LOGO = "logo.png"
ASSET_ICON = "icon.svg"
STATIC_TARGETS = (
    ASSET_INDEX_HTML,
    ASSET_API_JS,
    ASSET_APP_JS,
    ASSET_NAVIGATION_JS,
    ASSET_STATE_JS,
    ASSET_VIEWS_JS,
    ASSET_FORMS_JS,
    ASSET_COMPONENTS_JS,
    ASSET_STYLES_CSS,
    ASSET_SERVICE_WORKER_JS,
    ASSET_MANIFEST,
    ASSET_LOGO,
    ASSET_ICON,
)
VERSIONED_STATIC_ASSETS = frozenset(
    {
        ASSET_API_JS,
        ASSET_NAVIGATION_JS,
        ASSET_STATE_JS,
        ASSET_VIEWS_JS,
        ASSET_FORMS_JS,
        ASSET_COMPONENTS_JS,
        ASSET_APP_JS,
        ASSET_STYLES_CSS,
        ASSET_LOGO,
        ASSET_ICON,
    }
)
STATIC_REVALIDATE_ASSETS = frozenset(
    {ASSET_INDEX_HTML, ASSET_SERVICE_WORKER_JS, ASSET_MANIFEST}
)
STATIC_IMMUTABLE_MAX_AGE = 31536000
OCTET_STREAM_MIME = "application/octet-stream"


@dataclass(frozen=True)
class StaticAssetResponse:
    status: int
    headers: tuple[tuple[str, str], ...]
    body: bytes


class StaticAssetService:
    def __init__(self, public_dir: Path):
        self._targets = {name: public_dir / name for name in STATIC_TARGETS}

    def render(
        self, path: str, request_path: str, if_none_match: str | None
    ) -> StaticAssetResponse:
        asset_name = ASSET_INDEX_HTML if path in {"", "/"} else path.lstrip("/")
        if asset_name.startswith("..") or any(
            marker in asset_name for marker in ("/", "\\", ":")
        ):
            raise AppError(403, "Forbidden.")

        target = self._targets.get(asset_name, self._targets[ASSET_INDEX_HTML])
        if not target.is_file():
            target = self._targets[ASSET_INDEX_HTML]
        data = target.read_bytes()
        mime = mimetypes.guess_type(target.name)[0] or OCTET_STREAM_MIME
        etag = f'"{hashlib.sha256(data).hexdigest()[:24]}"'
        query = parse_qs(urlparse(request_path).query)
        versioned = target.name in VERSIONED_STATIC_ASSETS and bool(
            str(query.get("v", [""])[0]).strip()
        )
        if versioned:
            cache_control = f"public, max-age={STATIC_IMMUTABLE_MAX_AGE}, immutable"
        elif target.name in STATIC_REVALIDATE_ASSETS:
            cache_control = "no-cache"
        else:
            cache_control = "public, max-age=3600"

        if if_none_match == etag:
            return StaticAssetResponse(
                304, (("ETag", etag), ("Cache-Control", cache_control)), b""
            )

        content_type = mime + ("; charset=utf-8" if mime.startswith("text/") else "")
        return StaticAssetResponse(
            200,
            (
                ("Content-Type", content_type),
                ("Content-Length", str(len(data))),
                ("ETag", etag),
                ("Cache-Control", cache_control),
                ("X-Content-Type-Options", "nosniff"),
                ("X-Frame-Options", "DENY"),
                ("Referrer-Policy", "no-referrer"),
                (
                    "Content-Security-Policy",
                    "default-src 'self'; style-src 'self'; script-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'",
                ),
            ),
            data,
        )
