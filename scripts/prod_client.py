"""Read-only HTTP session for the post-release base skills.

The app address and the secret-file path come from arguments; neither is
stored here. The password is read from the file, sent only in the login body,
and never printed. Response bodies, cookies and error text are never printed:
callers print named fields and counts only.
"""

from __future__ import annotations

import http.cookiejar
import json
import ssl
import tempfile
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
# Where T3's request_secret file delivery stores the password file.
T3_SECRETS = Path.home() / ".t3" / "userdata" / "secrets"
CSRF_COOKIE = "ic_csrf"
TIMEOUT = 30


class ProdError(RuntimeError):
    """A failed request or refused input; the message holds no secret or body text."""


def base_url(text: str) -> str:
    parts = urlsplit(text)
    if parts.scheme not in {"http", "https"} or not parts.netloc:
        raise ProdError("the app address must be an http(s) URL")
    return f"{parts.scheme}://{parts.netloc}"


def scratch_path(path: str) -> Path:
    """Result and log files live in the system temp directory (the session
    scratchpad), never in the repository or anywhere else a path could reach."""
    target = Path(path).resolve()
    scratch = Path(tempfile.gettempdir()).resolve()
    if not target.is_relative_to(scratch) or target.is_relative_to(ROOT):
        raise ProdError("result and log files must be in the system temp directory")
    return target


def secret_path(path: str) -> Path:
    """The password file is only read: the system temp directory or the folder
    where a T3 secret request delivers files, never the repository (#2527)."""
    target = Path(path).resolve()
    roots = (Path(tempfile.gettempdir()).resolve(), T3_SECRETS.resolve())
    if target.is_relative_to(ROOT) or not any(target.is_relative_to(r) for r in roots):
        raise ProdError(
            "the password file must be in the system temp directory or the T3 secret folder"
        )
    return target


def write_result(path: str | None, result: dict[str, Any]) -> None:
    if path:
        scratch_path(path).write_text(json.dumps(result, indent=2), encoding="utf-8")


def read_result(path: str | None) -> dict[str, Any] | None:
    if not path:
        return None
    try:
        return json.loads(scratch_path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ProdError(f"cannot read the previous result file {path}") from exc


class Session:
    """Cookie-holding client; `status` never raises on an HTTP error status."""

    def __init__(self, url: str, ca_file: str | None = None) -> None:
        self.url = base_url(url)
        self.jar = http.cookiejar.CookieJar()
        context = ssl.create_default_context(cafile=ca_file)
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.jar),
            urllib.request.HTTPSHandler(context=context),
        )

    def request(
        self,
        method: str,
        path: str,
        body: dict[str, Any] | None = None,
        csrf: bool = False,
    ) -> tuple[int, bytes]:
        data = None if body is None else json.dumps(body).encode()
        request = urllib.request.Request(self.url + path, data=data, method=method)
        request.add_header("Accept", "application/json")
        if data is not None:
            request.add_header("Content-Type", "application/json")
        if csrf:
            request.add_header("X-CSRF-Token", self.cookie(CSRF_COOKIE) or "")
        try:
            with self.opener.open(request, timeout=TIMEOUT) as response:
                return response.status, response.read()
        except urllib.error.HTTPError as exc:
            exc.close()  # the error body is never read
            return exc.code, b""
        except (urllib.error.URLError, OSError) as exc:
            reason = type(getattr(exc, "reason", exc)).__name__
            raise ProdError(f"{method} {path} unreachable ({reason})") from None

    def status(self, method: str, path: str, **kwargs: Any) -> int:
        return self.request(method, path, **kwargs)[0]

    def get_json(self, path: str) -> Any:
        code, raw = self.request("GET", path)
        if code != 200:
            raise ProdError(f"GET {path} answered {code}")
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            raise ProdError(f"GET {path} returned no JSON") from None

    def cookie(self, name: str) -> str | None:
        return next((c.value for c in self.jar if c.name == name), None)

    def login(self, password_file: str) -> None:
        try:
            password = secret_path(password_file).read_text(encoding="utf-8").strip()
        except OSError:
            raise ProdError("cannot read the secret file") from None
        if not password:
            raise ProdError("the secret file is empty")
        code = self.status("POST", "/api/login", body={"password": password})
        del password
        if code != 200 or not self.cookie(CSRF_COOKIE):
            raise ProdError(f"login answered {code}")

    def logout(self) -> int:
        return self.status("POST", "/api/logout", body={}, csrf=True)
