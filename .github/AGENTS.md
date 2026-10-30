# CI and release safety

Keep actions pinned, permissions minimal, and workflow/source commits explicit.
Never execute pull-request code with privileged secrets in `pull_request_target`.
Run untrusted source validation under `pull_request` with read-only permissions
and no persisted checkout credentials. Treat logs and PR content as untrusted.

Preserve current-head review evidence, resolved feedback, protected-branch PRs,
release/source/version agreement, and image digest verification. Workflow success
alone is not proof of merge, release publication, or healthy deployment.
Use focused workflow regression tests and never bypass required checks.
Ruff/mypy bumps must keep `tests/fixtures/quality_baseline.json` versions in
step with `requirements-dev.txt` (`tools/quality_baseline.py --align-versions`);
the auto-rebase workflow aligns Dependabot PRs from trusted `develop` code only.

Gitar is the required hosted review check for human PRs to `develop` and `main`.
The isolated Gitar ruleset requires the `Gitar` context from the installed
`gitar-bot` GitHub App (integration ID 827041) on both branches; Dependabot and
the release app are exempt from that ruleset. Do not create a replacement
success check or treat a missing, failed, or pending check as a completed review.

Every review conversation must be resolved before merge, including outdated
threads and threads from other reviewers. Keep
`required_review_thread_resolution: true` with no bypass actors in the Default
and Main release protection rulesets.
This applies to human, Dependabot, and release automation PRs alike. Fix or
reconcile each finding before resolving its thread; never resolve it merely to
unblock merging. Ordinary PR comments have no resolved state: complete their
requested action or record the evidence-based disposition before merging.
An existing user-level pull-request bypass is present in both live rulesets;
automation must not use it.
