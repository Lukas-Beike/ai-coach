"""Compare the GHCR digests of a release tag and `latest`, read-only.

    python scripts/image_verify.py --tag 2.1.2 [--running sha256:...]

Prints both digests (and, with --running, whether the running container's
digest matches). Exit 0 the tag exists and `latest` (and the running digest)
equal it, 1 a mismatch or missing tag, 2 the registry could not be read.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.error
import urllib.request
from urllib.parse import quote

# Only this repository is ever read: no host or name comes from arguments.
REGISTRY = "https://ghcr.io"
REPOSITORY = "lukas-beike/pacecraft"
ACCEPT = (
    "application/vnd.oci.image.index.v1+json, "
    "application/vnd.docker.distribution.manifest.list.v2+json, "
    "application/vnd.oci.image.manifest.v1+json, "
    "application/vnd.docker.distribution.manifest.v2+json"
)
DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
TAG = re.compile(r"^\w[\w.-]{0,127}$")


class RegistryError(RuntimeError):
    pass


def fetch(request: urllib.request.Request) -> tuple[int, dict, bytes]:
    try:
        # 30 s only bounds a hung registry request.
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.status, dict(response.headers), response.read()
    except urllib.error.HTTPError as exc:
        exc.close()
        return exc.code, {}, b""
    except (urllib.error.URLError, OSError) as exc:
        raise RegistryError(f"registry unreachable ({type(exc).__name__})") from None


def anonymous_token() -> str:
    url = f"{REGISTRY}/token?scope=repository:{REPOSITORY}:pull"
    code, _, body = fetch(urllib.request.Request(url))
    if code != 200:
        raise RegistryError(f"anonymous pull token refused ({code})")
    return str(json.loads(body).get("token") or "")


def digest(tag: str, token: str) -> str | None:
    if not TAG.match(tag):
        raise RegistryError("bad tag")
    request = urllib.request.Request(
        f"{REGISTRY}/v2/{REPOSITORY}/manifests/{quote(tag, safe='')}", method="HEAD"
    )
    request.add_header("Accept", ACCEPT)
    request.add_header("Authorization", f"Bearer {token}")
    code, headers, _ = fetch(request)
    if code == 404:
        return None
    if code != 200:
        raise RegistryError(f"manifest {tag} answered {code}")
    value = {k.lower(): v for k, v in headers.items()}.get("docker-content-digest", "")
    if not DIGEST.match(value):
        raise RegistryError(f"manifest {tag} has no digest header")
    return value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--tag", required=True)
    parser.add_argument("--running")
    args = parser.parse_args(argv)
    if not TAG.match(args.tag) or (args.running and not DIGEST.match(args.running)):
        parser.error("bad --tag or --running digest")
    try:
        token = anonymous_token()
        release = digest(args.tag, token)
        latest = digest("latest", token)
    except RegistryError as exc:
        print(f"FAIL {exc}")
        return 2
    print(f"{'ok' if release else 'FAIL'} {args.tag} {release or 'missing'}")
    print(f"{'ok' if latest == release else 'FAIL'} latest {latest or 'missing'}")
    ok = bool(release) and latest == release
    if args.running:
        same = args.running == release
        print(f"{'ok' if same else 'FAIL'} running {args.running}")
        ok = ok and same
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
