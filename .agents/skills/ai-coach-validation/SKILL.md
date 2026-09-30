---
name: ai-coach-validation
description: Choose focused ai-coach backend, browser, PWA, and Docker checks for a change.
---

Use after changes or when validating a suspected regression.

- Backend: run focused tests first, then `python tests/run_tests.py` or `python -m unittest discover -s tests -v`. Run `python -m compileall -q server.py backend tests` for syntax checks.
- Changed backend files: mirror CI with `ruff check <files>`, `ruff format --check <files>`, and `mypy --ignore-missing-imports --follow-imports=skip <files>`.
- Browser: follow `ai-coach-pwa-e2e/references/browser-validation.md` for the disposable fixture runtime; preserve timing, viewports, accessibility, login, and streaming assertions. Never run against a connected installation.
- PWA assets: when `public/index.html`, any asset listed in `service-worker.js`, or `service-worker.js` changes, verify matching asset query and cache versions.
- Docker or startup changes: run `docker build -t ai-coach:local .`.
- Use temporary data and mocked providers. Never use real `.env`, `/data`, credentials, or athlete data.
- Report each check as passed, failed, blocked, or not run, including the shortest decisive evidence and the reason for skipped checks.
