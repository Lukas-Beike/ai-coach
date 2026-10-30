---
name: pr
description: "Run the complete PR lifecycle for the standalone `pr` command or the authorized PR phase of deliver-issue: rebase onto develop, validate, review, create the PR, enable squash auto-merge, and monitor through merge. Do not use for ordinary PR questions or unrelated longer requests."
---

# Pull request workflow

Use when the user's message is the standalone command `pr`, or when
[deliver-issue](../deliver-issue/SKILL.md) runs its PR phase. Either entry
authorizes the steps below: committing the task changes, rewriting and pushing
the feature branch, creating the PR, enabling squash auto-merge, and fixing
conflicts, CI failures, and review feedback through the merge.

## 1. Prepare

- Work in this session's task worktree (`git rev-parse --show-toplevel`). If it
  or its feature branch is ambiguous, stop and say so. Never use the primary
  checkout, and never rebase or push `develop`, `main`, or another protected
  branch.
- `gh` must be authenticated. Never print credentials or tokens.
- Commit only this task's changes with Conventional Commit subjects; leave
  unrelated user changes alone and stop if they block the rebase.
- Fetch `develop` and rebase onto it. Resolve conflicts by understanding both
  sides; ask the user for product decisions you cannot infer.
- Check every subject in `develop..HEAD` against the Conventional Commit types
  in root `AGENTS.md`; reword invalid ones.
- Run the required validation from `AGENTS.md` and fix real failures. Never
  weaken tests, security, or required checks.
- **OpenSpec:** list `git diff --name-only --no-renames origin/develop...HEAD --
  openspec/changes`. Each `openspec/changes/<name>/` path outside `archive/`
  names a change that must be archived on this branch: its active directory is
  gone at `HEAD`, an `archive/<date>-<name>/` exists, and
  `npm run openspec -- validate --all --strict --no-interactive` passes.
  Archive it under deliver-issue's rules if all tasks are done; otherwise stop
  and report the open tasks.

## 2. Review

Run exactly one fresh-context review of `origin/develop...HEAD`: the host's
`/code-review` at `high` when available, otherwise the repository
[code-review skill](../code-review/SKILL.md) with `depth=high` and
`report-only`. Sonar and Gitar review every head in CI, so there is no local
re-check and no further local review round.

Fix valid findings with new commits and rerun the affected checks, then push. A
finding you consider invalid needs concrete evidence (file and line, or the
same code on `develop`); not fixing a P0-P2 finding requires the user's
confirmation. List every unfixed finding with its reason in the PR body.

## 3. Publish

- Push with `git -c core.hooksPath=.githooks push`, using `--force-with-lease`
  after a rewrite. The pre-push hook scans outgoing commits for secrets; never
  bypass it with `--no-verify`.
- Create one non-draft PR against `develop` (or reuse the open one for this
  branch) with an English Conventional Commit title and a body covering the
  change, validation, and review results. Pass bodies with `--body-file`.
  Link the PR with the host's PR-linking tool when available.
- Enable `gh pr merge <number> --auto --squash` only when the base is `develop`
  and no feedback is open.

## 4. Monitor to merge

Watch with the host's PR watcher when available (`watch_pull_request`), and
yield; otherwise poll about every 30 seconds. On each wake:

- Read the current head. Fetch review threads through GraphQL `reviewThreads`
  (with `isResolved`) and top-level comments. For each open item: fix it if
  valid, run the affected checks, reply with the result, then resolve the
  thread; if not actionable, reply with the concrete reason before resolving.
  Disable auto-merge while repairs are in progress, and re-enable it once the
  current head has no open feedback.
- Later changes (feedback fixes, CI fixes, conflict resolutions, rebases) need
  validation, not another local review; CI reviews the new head.
- If the branch falls behind or conflicts, rebase (never a merge-style "Update
  branch") and push with `--force-with-lease`.
- If checks fail, read the logs, fix the cause, and push. The `Gitar` check is
  required (see `.github/AGENTS.md`); no bypass.
- Stop and report if GitHub requires something you cannot satisfy, or if the PR
  is closed without merging.

Finish only when GitHub reports the PR merged (`mergedAt` set), required checks
passed, and every thread and comment is handled. Enabled auto-merge is not a
merge. Call `unwatch_pull_request` before the final report. An open PR handed
back unmonitored must have auto-merge disabled. Report the PR URL, merge state,
validation, and fixes made.
