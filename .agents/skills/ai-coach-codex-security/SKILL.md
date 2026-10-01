---
name: ai-coach-codex-security
description: Run a requested local Codex Security review with ChatGPT authentication and triage its findings against Intervals Coach security boundaries.
---

Use for an explicitly requested Codex Security scan or security review of a code change. This is a local workflow; do not add GitHub Actions integration or require an API key.

- Use the installed Codex Security plugin when available. For the CLI, authenticate with the ChatGPT account using `npx @openai/codex-security login`, then pass `--auth chatgpt` to every scan. Never fall back to `OPENAI_API_KEY` or `CODEX_API_KEY`; report the scan as blocked if ChatGPT authentication is unavailable.
- For a CLI scan, use `npx @openai/codex-security scan <safe-path> --auth chatgpt --mode standard --effort high --output-dir <outside-repo-path>`. Use `--working-tree` for staged and unstaged local changes, or `--diff <base-ref>` for a committed change set.
- Before scanning, inspect the Git status and choose the smallest relevant source scope. Keep `.env`, `/data`, SQLCipher databases, backups, Garmin tokens, credentials, and live athlete data out of the scan. Follow the repository's secret-scanning protocol before reading or scanning source files. If ignored or untracked runtime files could enter a whole-repository scan, use a clean source-only worktree or explicit safe paths.
- Keep scan output outside the repository. Prefer a changed-file or committed-diff scan for a focused change; run a full scan only when requested.
- Prioritize authentication and CSRF, provider trust boundaries, privacy and secret handling, SQLite transactions, durable coach effects, and explicit approval for remote workout synchronization.
- Treat model findings as hypotheses. Verify each reported path against the source and tests before recommending a fix; do not apply automated patches or change live data as part of triage.
- Report confirmed findings with priority, file and line, impact, and a concrete remediation. Separate confirmed defects from unverified hypotheses, false positives, and scan blockers.
