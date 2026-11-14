"""Check that production still refuses unauthenticated and CSRF-less requests.

    python scripts/prod_guards.py --url <app address> --password-file <secret file>
        [--min-tls-days 14] [--ca-file ca.pem]

Probes have no effect even if accepted: a GET of diagnostics without a session,
and a logout of the probe's own session without the CSRF token. For an https
address it also reports the TLS certificate's days to expiry. Exit 0 all
guards hold, 1 a guard failed or the certificate expires soon, 2 unreachable.
"""

from __future__ import annotations

import argparse
import socket
import ssl
import sys
import time
from urllib.parse import urlsplit

from prod_client import ProdError, Session


def tls_days(url: str, ca_file: str | None) -> float:
    parts = urlsplit(url)
    host, port = parts.hostname or "", parts.port or 443
    context = ssl.create_default_context(cafile=ca_file)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    try:
        with (
            # 15 s only bounds a hung handshake.
            socket.create_connection((host, port), timeout=15) as raw,
            context.wrap_socket(raw, server_hostname=host) as tls,
        ):
            cert = tls.getpeercert()
    except (OSError, ssl.SSLError) as exc:
        raise ProdError(f"TLS handshake failed ({type(exc).__name__})") from None
    expires = ssl.cert_time_to_seconds(str((cert or {}).get("notAfter")))
    return (expires - time.time()) / 86400


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--url", required=True)
    parser.add_argument("--password-file", required=True)
    # Two weeks' warning leaves time to renew the certificate.
    parser.add_argument("--min-tls-days", type=float, default=14)
    parser.add_argument("--ca-file")
    args = parser.parse_args(argv)
    results: list[tuple[bool, str]] = []
    try:
        anonymous = Session(args.url, args.ca_file)
        code = anonymous.status("GET", "/api/diagnostics")
        results.append((code == 401, f"no session -> {code} (expected 401)"))
        session = Session(args.url, args.ca_file)
        session.login(args.password_file)
        code = session.status("POST", "/api/logout", body={})
        results.append((code == 403, f"no CSRF token -> {code} (expected 403)"))
        code = session.logout()
        results.append((code == 200, f"logout with CSRF token -> {code}"))
        if urlsplit(session.url).scheme == "https":
            days = tls_days(session.url, args.ca_file)
            results.append(
                (
                    days >= args.min_tls_days,
                    f"TLS certificate expires in {days:.0f} days",
                )
            )
    except ProdError as exc:
        for ok, text in results:
            print(f"{'ok' if ok else 'FAIL'} {text}")
        print(f"FAIL {exc}")
        return 2
    for ok, text in results:
        print(f"{'ok' if ok else 'FAIL'} {text}")
    return 0 if all(ok for ok, _ in results) else 1


if __name__ == "__main__":
    sys.exit(main())
