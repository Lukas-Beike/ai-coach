---
name: pacecraft-image-verify
description: Base skill. Compare the GHCR digests of a release tag and latest, and optionally the running container's digest, read-only. Use in the release workflow before and after updating the container.
---

# Verify the published image

```powershell
python scripts/image_verify.py --tag <release tag> [--running <sha256 digest of the running container>]
```

It reads `ghcr.io/lukas-beike/pacecraft` with an anonymous pull token and
prints the digest of the tag and of `latest`. Exit 0 the tag exists and
`latest` (and the running digest, when given) equal it; 1 a mismatch or a
missing tag: do not update the container; 2 the registry could not be read.

Run it immediately before the container update, and again with `--running`
after it, taking the running digest from the Unraid MCP's container details:
the repository digest (`ghcr.io/...@sha256:...`), not the local image ID.
