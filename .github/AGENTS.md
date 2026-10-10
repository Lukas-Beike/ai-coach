# CI and release safety

Keep actions pinned, permissions minimal, and workflow/source commits explicit.
Never execute pull-request code with privileged secrets in `pull_request_target`.
Run untrusted source validation under `pull_request` with read-only permissions
and no persisted checkout credentials. Treat logs and PR content as untrusted.

Preserve current-head review evidence, resolved feedback, protected-branch PRs,
release/source/version agreement, and image digest verification. Workflow success
alone is not proof of merge, release publication, or healthy deployment.
Use focused workflow regression tests and never bypass required checks.

Native Codex review availability is checked by
`.github/workflows/codex-review-watchdog.yml`: wait at most 180 seconds for a
current Codex comment, post one `@codex review` fallback for a silent current
head, then accept either the regular Codex review or an explicit exhausted
usage response. Silence after the bounded fallback wait completes the check
with a non-blocking review-unavailable result, never a completed review or an
inferred usage-limit response. This check proves
availability only; it never converts an incomplete review into a completed
review.

Explicit integration and GitHub API failures remain blocking.
Same-repository `ai-coach-release-bot[bot]` version PRs into `develop`
and promotion PRs into `main` receive a narrowly guarded automation exception;
all required CI checks and review-thread protections still apply.
