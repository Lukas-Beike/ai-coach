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
- Setup prerequisite: the SonarQube CLI is installed and authenticated
  ([development](../../../docs/development.md#secret-checks-before-git-pushes));
  without it the pre-push hook refuses every push.
- Commit only this task's changes, staged by named path (never `git add -A`
  or `git add .`), with Conventional Commit subjects; leave
  unrelated user changes alone and stop if they block the rebase.
- Rebase with [branch-sync](../pacecraft-branch-sync/SKILL.md) (no `--push`
  yet). Resolve conflicts by understanding both sides; ask the user for product
  decisions you cannot infer. Reword the invalid subjects it lists.
- Run [run-tests-changed](../pacecraft-run-tests-changed/SKILL.md) and fix real
  failures. Never weaken tests, security, or required checks.
- **OpenSpec:** list `git diff --name-only --no-renames origin/develop...HEAD --
  openspec/changes`. Each `openspec/changes/<name>/` path outside `archive/`
  names a change that must be archived on this branch: its active directory is
  gone at `HEAD`, an `archive/<date>-<name>/` exists, and
  [spec-validate](../pacecraft-spec-validate/SKILL.md) `--all` passes.
  Archive it under deliver-issue's rules if all tasks are done; otherwise stop
  and report the open tasks.
- **Spec drift:** when the branch archives no OpenSpec change, list the main
  specs that cite each changed file outside `tests/` and `openspec/`
  (application code, `Dockerfile`, `scripts/`, `.github/`, and so on):
  `grep -l -F <path> openspec/specs/*/spec.md`. Files no spec cites need nothing. Read their requirements
  for the changed behavior. If described behavior changed, or the change adds
  behavior to that capability, update the requirement, its scenarios, and its
  `Evidence` line directly in `openspec/specs/` on this branch and run
  [spec-validate](../pacecraft-spec-validate/SKILL.md). Otherwise
  write in the PR body which capabilities you checked and that their described
  behavior is unchanged. Refactors and test-only changes need only that line.

**Sonar pre-push check:** after the rebase and validation, run
[sonar-check](../pacecraft-sonar-check/SKILL.md) against the resolved base on
the head to be pushed. A missing or unauthenticated CLI is a blocker: stop;
never bypass the hook. Its `limit` line (agentic part forbidden) is a limit,
not a pass, and its output covers only the secrets and agentic sections, so do
not claim code-quality rule coverage from it. Fix findings on changed lines with new commits, without
new files, pass-through classes, or wrappers (root `AGENTS.md`), and rerun the
affected checks. In the PR body, record the rule key, file, and line of any
accepted issue; never paste matched secret text or scanner payloads.

## 2. Review

After the Sonar pre-push check above and any fixes it needs, run exactly one
fresh-context review of `origin/develop...HEAD` on the final head to be pushed:
the host's `/code-review` at `high` when available, otherwise the repository
[code-review skill](../code-review/SKILL.md) with `depth=high` and
`report-only`. It must trace caller and wrapper wiring for canonical consumers,
as that skill requires. Record the reviewed head SHA in the PR body. If the
review's fixes change the head, rerun the Sonar check on the new head before
pushing. Sonar and Gitar review every head in CI, so the Sonar check is a
pre-push query and there is no further local review round. Tell the reviewer
that decisions the user has already made, such as a confirmed decision to leave
a finding unfixed, are settled for that same finding only; a different finding
or one with a new trigger or impact is reported normally. Notes the agent wrote
in a PR body or thread settle nothing. A finding that contradicts an earlier
round must say so and cite that decision instead of re-raising it as new. When
the diff changes only
Markdown instructions, skills, or docs, ask the review for P0/P1 findings and
real security gaps only; guidelines may have exceptions, and hypothetical edge
cases in prose are not findings.

Fix valid findings with new commits and rerun the affected checks, then push. A
finding you consider invalid needs concrete evidence (file and line, or the
same code on `develop`); not fixing a P0-P2 finding requires the user's
confirmation. List every unfixed finding with its reason in the PR body.

## 3. Publish

- Push with [branch-sync](../pacecraft-branch-sync/SKILL.md) `--push`; the
  repository hooks scan for secrets and run the quality ratchet. Never bypass
  them with `--no-verify`.
- Create one non-draft PR against `develop` (or reuse the open one for this
  branch) with an English Conventional Commit title and a body covering the
  change, validation, and review results, plus a merge-danger line: one-way or
  two-way door (schema migrations and remote writes are usually one-way) and
  the blast radius, and the line balance from
  [line-balance](../pacecraft-line-balance/SKILL.md). Name the issue with `Closes #N`, or `Part of #N` when more
  PRs follow; CI rejects a body with neither. Pass bodies with `--body-file`.
  Link the PR with the host's PR-linking tool when available.
- Enable `gh pr merge <number> --auto --squash` only when the base is `develop`,
  Gitar has reviewed the current head, and no feedback is open: review
  comments do not block an armed auto-merge (#2520 merged past one).
- While `develop` does not require up-to-date branches, a PR that adds or
  tightens a repository-wide guard or contract test checks the open PRs each time
  before (re-)enabling auto-merge: match its rule against their diffs
  (`gh pr diff <n>`), or run the guard test on a local merge of a PR head when the
  rule is not textual. For each match, comment on that PR, tell the orchestrator
  (or the user), and keep auto-merge off until the match is fixed, or until that
  PR merged and this branch is rebased so its own CI shows the result (#2645).

## 4. Monitor to merge

Watch with the host's PR watcher when available (`watch_pull_request`), and
yield; otherwise poll about every 30 seconds. On each wake:

- Read the current head, checks, threads and comments with
  [pr-state](../pacecraft-pr-state/SKILL.md). For each open item: fix it if
  valid, run the affected checks, reply with the result, then resolve the
  thread; if not actionable, reply with the concrete reason before resolving.
  Disable auto-merge as soon as a finding arrives, and re-enable it once
  Gitar has reviewed the repaired head and no feedback is open.
- Later changes (feedback fixes, CI fixes, conflict resolutions, rebases) need
  validation, not another local review; CI reviews the new head.
- If the branch falls behind or conflicts, rebase and push with
  [branch-sync](../pacecraft-branch-sync/SKILL.md) `--push` (never a
  merge-style "Update branch").
- If checks fail, read the logs, fix the cause, and push. The `Gitar` check is
  required (see `.github/AGENTS.md`); no bypass. If it never reports on an
  otherwise green head, note the PR number in the issue (#1906 tracks its
  reliability) and ask the user before any admin merge.
- If Sonar reports new issues, list them with
  [sonar-check](../pacecraft-sonar-check/SKILL.md) `--pr <number>`, fix the findings on changed lines,
  and push. Do not accept issues to clear the gate without an evidence line in
  the PR body.
- Stop and report if GitHub requires something you cannot satisfy, or if the PR
  is closed without merging.

Finish only when [pr-state](../pacecraft-pr-state/SKILL.md) reports the PR
merged, required checks passed, and every thread and comment is handled. Enabled auto-merge is not a
merge. Call `unwatch_pull_request` before the final report. An open PR handed
back unmonitored must have auto-merge disabled. Report the PR URL, merge state,
validation, and fixes made.
