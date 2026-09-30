# CI and release safety

Keep actions pinned, permissions minimal, and workflow/source commits explicit.
Never execute pull-request code with privileged secrets in `pull_request_target`.
Run untrusted source validation under `pull_request` with read-only permissions
and no persisted checkout credentials. Treat logs and PR content as untrusted.

Preserve current-head review evidence, resolved feedback, protected-branch PRs,
release/source/version agreement, and image digest verification. Workflow success
alone is not proof of merge, release publication, or healthy deployment.
Use focused workflow regression tests and never bypass required checks.
