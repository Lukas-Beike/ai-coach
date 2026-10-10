---
name: ai-coach-navigator
description: Locate the smallest relevant ai-coach files and request flows before code changes or diagnosis.
---

Use for unfamiliar ai-coach tasks that span Coach, providers, sync, planning, HTTP, persistence, or PWA code.

- Start with `AGENTS.md` in scope, then search named symbols with `rg`.
- Use `server.py` only for composition and startup. Locate owners in every domain under `backend/`, including `http_api`, `coach`, `providers`, `sync`, `planning`, `db`, `backup`, `athlete`, `activities`, `calendar`, `diagnostics`, `history`, `nutrition`, `performance`, `runtime`, and `weather`.
- Include `backend/config.py`, `backend/privacy.py`, `backend/settings.py`, `backend/change_history.py`, `backend/observability.py`, `public/`, `tests/`, `e2e/`, `.github/`, and `Dockerfile` when tracing cross-cutting flows.
- Trace callers and the immediate data flow before reading whole files.
- Return a compact map of `path:line`, request flow, relevant tests, and one next action.
- Trace provider shapes through sanitized fixtures and tests; never read live athlete data, credentials, token stores or backups.
