---
name: ai-coach-validation
description: Choose focused ai-coach backend, browser, PWA, and Docker checks for a change.
---

Use after changes or when validating a suspected regression.

- Backend: run `python -m unittest discover -s tests -v` and `python -m py_compile server.py tests/test_server.py` when affected.
- Browser: use `npm run test:e2e`; preserve fixture timing, observed viewport resize, accessibility, login, and streaming assertions.
- PWA assets: when `public/index.html`, `app.js`, `styles.css`, or `service-worker.js` changes, verify matching asset query and cache versions.
- Docker or startup changes: run `docker build -t ai-coach:local .`.
- Use temporary data and mocked providers. Never use real `.env`, `/data`, credentials, or athlete data.
- Report only commands run, pass/fail, and the shortest decisive failure line.
