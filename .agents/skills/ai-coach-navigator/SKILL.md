---
name: ai-coach-navigator
description: Locate the smallest relevant ai-coach files and request flows before code changes or diagnosis.
---

Use for unfamiliar ai-coach tasks that span Coach, providers, sync, planning, HTTP, persistence, or PWA code.

- Start with `AGENTS.md` in scope, then search named symbols with `rg`.
- Use the root AGENTS domain map to find the cohesive `backend/` owner. Inspect `server.py` for wiring and affected legacy callers without treating legacy ownership as a precedent for new logic.
- Include `backend/config.py`, `backend/privacy.py`, `backend/settings.py`, `backend/change_history.py`, `backend/observability.py`, `public/`, `tests/`, `e2e/`, `.github/`, and `Dockerfile` when tracing cross-cutting flows.
- Trace callers and the immediate data flow before reading whole files.
- Verify the actual code and tests before trusting documentation, remembered paths, defaults, or tool capabilities. If the first path is stale, search the symbol rather than widening to a whole-repository read.
- Return a compact map of `path:line`, request flow, relevant tests, and one next action.
- Trace provider shapes through sanitized fixtures and tests; never read live athlete data, credentials, token stores or backups.
- For a repository-wide symbol or dependency map, optionally use the local structural graph described in [ai-coach-graphify](../ai-coach-graphify/SKILL.md). Treat it as navigation only and verify candidates in current source.
