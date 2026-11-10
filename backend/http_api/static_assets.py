"""Safe static asset projections for the public Coach client."""

from __future__ import annotations

import hashlib
import mimetypes
import re
import threading
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from backend.errors import AppError

ASSET_INDEX_HTML = "index.html"
ASSET_API_JS = "api.js"
ASSET_FORMAT_JS = "format.js"
ASSET_APP_JS = "app.js"
ASSET_SHARED_JS = "shared.js"
ASSET_AUTH_JS = "auth.js"
ASSET_SYNC_STATUS_JS = "sync-status.js"
ASSET_VIEW_REFRESH_JS = "view-refresh.js"
ASSET_NOTIFICATIONS_JS = "notifications.js"
ASSET_PERFORMANCE_VIEW_JS = "performance-view.js"
ASSET_DIAGNOSTICS_JS = "diagnostics.js"
ASSET_STATE_LOADER_JS = "state-loader.js"
ASSET_SYNC_ACTIONS_JS = "sync-actions.js"
ASSET_WAHOO_CONNECTION_JS = "wahoo-connection.js"
ASSET_PROVIDER_CONNECTIONS_JS = "provider-connections.js"
ASSET_PROVIDER_CHECKS_JS = "provider-checks.js"
ASSET_SETTINGS_JS = "settings.js"
ASSET_NAVIGATION_JS = "navigation.js"
ASSET_APPEARANCE_JS = "appearance.js"
ASSET_STATE_JS = "state.js"
ASSET_VIEWS_JS = "views.js"
ASSET_PLAN_VIEWS_JS = "plan-views.js"
ASSET_COMPONENTS_JS = "components.js"
ASSET_CONNECTION_STATUS_JS = "connection-status.js"
ASSET_STATUS_STRIP_JS = "status-strip.js"
ASSET_COACH_JS = "coach.js"
ASSET_NUTRITION_JS = "nutrition.js"
ASSET_ANALYSIS_JS = "analysis.js"
ASSET_ACTIVITY_DETAILS_JS = "activity-details.js"
ASSET_ACTIVITY_ANALYSIS_JS = "activity-analysis.js"
ASSET_STYLES_CSS = "styles.css"
ASSET_SERVICE_WORKER_JS = "service-worker.js"
ASSET_MANIFEST = "manifest.webmanifest"
ASSET_LOGO = "logo.png"
ASSET_ICON = "icon.svg"
ASSET_APPLE_TOUCH_ICON = "apple-touch-icon.png"
STATIC_TARGETS = (
    ASSET_INDEX_HTML,
    ASSET_API_JS,
    ASSET_FORMAT_JS,
    ASSET_APP_JS,
    ASSET_SHARED_JS,
    ASSET_AUTH_JS,
    ASSET_SYNC_STATUS_JS,
    ASSET_VIEW_REFRESH_JS,
    ASSET_NOTIFICATIONS_JS,
    ASSET_PERFORMANCE_VIEW_JS,
    ASSET_DIAGNOSTICS_JS,
    ASSET_STATE_LOADER_JS,
    ASSET_SYNC_ACTIONS_JS,
    ASSET_WAHOO_CONNECTION_JS,
    ASSET_PROVIDER_CONNECTIONS_JS,
    ASSET_PROVIDER_CHECKS_JS,
    ASSET_SETTINGS_JS,
    ASSET_NAVIGATION_JS,
    ASSET_APPEARANCE_JS,
    ASSET_STATE_JS,
    ASSET_VIEWS_JS,
    ASSET_PLAN_VIEWS_JS,
    ASSET_COMPONENTS_JS,
    ASSET_CONNECTION_STATUS_JS,
    ASSET_STATUS_STRIP_JS,
    ASSET_COACH_JS,
    ASSET_NUTRITION_JS,
    ASSET_ANALYSIS_JS,
    ASSET_ACTIVITY_DETAILS_JS,
    ASSET_ACTIVITY_ANALYSIS_JS,
    ASSET_STYLES_CSS,
    ASSET_SERVICE_WORKER_JS,
    ASSET_MANIFEST,
    ASSET_LOGO,
    ASSET_ICON,
    ASSET_APPLE_TOUCH_ICON,
)
VERSIONED_STATIC_ASSETS = frozenset(
    {
        ASSET_API_JS,
        ASSET_FORMAT_JS,
        ASSET_NAVIGATION_JS,
        ASSET_APPEARANCE_JS,
        ASSET_STATE_JS,
        ASSET_VIEWS_JS,
        ASSET_PLAN_VIEWS_JS,
        ASSET_COMPONENTS_JS,
        ASSET_CONNECTION_STATUS_JS,
        ASSET_STATUS_STRIP_JS,
        ASSET_COACH_JS,
        ASSET_NUTRITION_JS,
        ASSET_ANALYSIS_JS,
        ASSET_ACTIVITY_DETAILS_JS,
        ASSET_ACTIVITY_ANALYSIS_JS,
        ASSET_APP_JS,
        ASSET_SHARED_JS,
        ASSET_AUTH_JS,
        ASSET_SYNC_STATUS_JS,
        ASSET_VIEW_REFRESH_JS,
        ASSET_NOTIFICATIONS_JS,
        ASSET_PERFORMANCE_VIEW_JS,
        ASSET_DIAGNOSTICS_JS,
        ASSET_STATE_LOADER_JS,
        ASSET_SYNC_ACTIONS_JS,
        ASSET_WAHOO_CONNECTION_JS,
        ASSET_PROVIDER_CONNECTIONS_JS,
        ASSET_PROVIDER_CHECKS_JS,
        ASSET_SETTINGS_JS,
        ASSET_STYLES_CSS,
        ASSET_LOGO,
        ASSET_ICON,
        ASSET_APPLE_TOUCH_ICON,
    }
)
STATIC_REVALIDATE_ASSETS = frozenset(
    {ASSET_INDEX_HTML, ASSET_SERVICE_WORKER_JS, ASSET_MANIFEST}
)
STATIC_IMMUTABLE_MAX_AGE = 31536000
OCTET_STREAM_MIME = "application/octet-stream"
# Source files carry no version numbers: the server stamps them when serving.
CACHE_NAME_TOKEN = "__ASSET_HASH__"
ASSET_HASH_LENGTH = 10
_MARKUP_REF = re.compile(r'((?:src|href)=")(/[^"?#\s]+)(")')
_PRECACHE_LIST = re.compile(r"(const ASSETS = \[)(.*?)(\];)", re.DOTALL)
_QUOTED_PATH = re.compile(r'"(/[^"?\s]*)"')


def content_hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:ASSET_HASH_LENGTH]


@dataclass(frozen=True)
class StaticAssetResponse:
    status: int
    headers: tuple[tuple[str, str], ...]
    body: bytes


class StaticAssetService:
    def __init__(self, public_dir: Path):
        self._targets = {name: public_dir / name for name in STATIC_TARGETS}
        self._stamp_lock = threading.Lock()
        self._stamp_signature: tuple | None = None
        self._stamped: dict[str, bytes] = {}

    def stamped(self, name: str) -> bytes:
        """index.html or service-worker.js with content-hash versions applied.

        Recomputed only when a target file changes (mtime and size).
        """
        with self._stamp_lock:
            signature = tuple(
                (name, stat.st_mtime_ns, stat.st_size)
                for name, path in self._targets.items()
                if path.is_file()
                for stat in (path.stat(),)
            )
            if signature != self._stamp_signature:
                self._stamped = self._build_stamped()
                self._stamp_signature = signature
            return self._stamped[name]

    def _build_stamped(self) -> dict[str, bytes]:
        sources = {
            name: path.read_bytes()
            for name, path in self._targets.items()
            if path.is_file()
        }
        hashes = {
            name: content_hash(sources[name])
            for name in VERSIONED_STATIC_ASSETS
            if name in sources
        }

        def versioned(path: str) -> str:
            name = path.lstrip("/")
            return f"{path}?v={hashes[name]}" if name in hashes else path

        def source_of(path: str) -> bytes:
            name = ASSET_INDEX_HTML if path == "/" else path.lstrip("/")
            if name not in sources:
                raise ValueError(f"service worker caches unknown asset {path}")
            return sources[name]

        index = _MARKUP_REF.sub(
            lambda m: m[1] + versioned(m[2]) + m[3],
            sources[ASSET_INDEX_HTML].decode("utf-8"),
        )
        worker = sources[ASSET_SERVICE_WORKER_JS].decode("utf-8")
        precache = _PRECACHE_LIST.search(worker)
        if precache is None or CACHE_NAME_TOKEN not in worker:
            raise ValueError("service worker lacks its asset list or cache name token")
        cached = _QUOTED_PATH.findall(precache[2])
        # The cache name changes with any cached asset or the worker itself.
        cache_hash = content_hash(
            "\n".join(
                [content_hash(sources[ASSET_SERVICE_WORKER_JS])]
                + [f"{path}:{content_hash(source_of(path))}" for path in cached]
            ).encode()
        )
        worker = (
            worker[: precache.start(2)]
            + _QUOTED_PATH.sub(lambda m: f'"{versioned(m[1])}"', precache[2])
            + worker[precache.end(2) :]
        ).replace(CACHE_NAME_TOKEN, cache_hash)
        return {
            ASSET_INDEX_HTML: index.encode("utf-8"),
            ASSET_SERVICE_WORKER_JS: worker.encode("utf-8"),
        }

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
        if target.name in {ASSET_INDEX_HTML, ASSET_SERVICE_WORKER_JS}:
            data = self.stamped(target.name)
        else:
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
