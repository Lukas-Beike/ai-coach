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
usage response. Silence after the fallback fails the check. This check proves
availability only; it never converts an incomplete review into a completed
review.
