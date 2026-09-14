---
name: ai-coach-navigator
description: Locate the smallest relevant ai-coach files and request flows before code changes or diagnosis.
---

Use for unfamiliar ai-coach tasks that span Coach, providers, sync, planning, or PWA code.

- Start with `AGENTS.md` in scope, then search named symbols with `rg`.
- Use these anchors: `server.py`, `backend/coach/`, `backend/providers/`, `backend/sync/`, `public/`, `tests/`, `e2e/`.
- Trace callers and the immediate data flow before reading whole files.
- Return a compact map of `path:line`, request flow, relevant tests, and one next action.
- Read raw provider and athlete data only when the task requires it; never print secrets or live data.
