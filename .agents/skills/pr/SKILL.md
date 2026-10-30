---
name: pr
description: "Run the complete PR lifecycle for the standalone `pr` command or the authorized PR phase of deliver-issue: rebase onto develop, validate, review, create the PR, enable squash auto-merge, and monitor through merge. Do not use for ordinary PR questions or unrelated longer requests."
---

# Pull Request Workflow

Use this skill when the user's message consists of the standalone command `pr` (ignoring
surrounding whitespace), or when [deliver-issue](../deliver-issue/SKILL.md) invokes its PR
phase under the user's explicit complete-delivery request. Treat either entry as authorization for the complete workflow below,
including rewriting the current feature branch, pushing it, creating a pull request, enabling
squash auto-merge, and fixing branch conflicts or failed CI tests. Keep the user updated at
meaningful state changes.

## Preconditions

1. Resolve the repository and worktree from the session's recorded implementation worktree, not
   from the directory in which the `pr` command happens to be issued. The command may be started
   from another checkout, but all PR work must use the worktree where this session created or
   modified the feature. Confirm that path with `git rev-parse --show-toplevel`, then read the
   applicable `AGENTS.md` files there and follow its test, branch, and security rules.
2. If the session worktree cannot be identified unambiguously, or if its feature branch and
   changes do not match the work performed in this session, stop and report the exact blocker.
   Never fall back to the primary checkout, use the command's current directory, or infer the
   feature branch from another worktree. Once identified, complete the entire PR workflow from
   the session worktree, including rebase, fixes, validation, pushes, PR operations, and merge
   verification.
3. Verify that Git and an authenticated GitHub CLI (`gh`) or an equivalent configured GitHub
   integration are available. Do not print credentials, tokens, environment files, database
   contents, or provider payloads.
4. Identify the current branch, its upstream remote, and the `develop` branch. The current
   branch must be a feature/topic branch; never rebase or push `develop`, `main`, or another
   protected branch.
5. Read the repository-local [code-review skill](../code-review/SKILL.md). It supports
   direct Markdown invocation by any agent; no host slash command is required. If the file is
   missing or unreadable, report that exact blocker.
6. Inspect staged, unstaged, and untracked changes against this session's task. The `pr` command
   includes preparing and committing the authorized task changes with Conventional Commits
   before rebasing. Review the complete diff and validate the relevant changes; stage only
   explicit task paths. Do not include, stash, reset, discard, or overwrite unrelated user work.
   If unrelated edits overlap the task or prevent a clean rebase, report that exact blocker.
   Require a clean tree after committing task changes; branch ambiguity, missing authentication,
   or a missing `develop` remain blockers.

## Rebase and commit validation

1. Fetch the latest `develop` from the selected remote, then rebase the current feature branch
   onto it. Preserve the user's commits and file changes; do not use destructive reset or
   checkout commands.
2. Resolve conflicts by understanding both sides and applying the repository's intended
   behavior. Inspect conflict markers, the surrounding code, and relevant tests. After each
   resolution, stage only the intended files and continue the rebase. Run the relevant tests
   after the rebase. If a conflict concerns an ambiguous product decision, secrets, durable
   data, or an unsafe change that cannot be inferred, stop and ask the user rather than
   guessing.
3. Inspect every commit in the feature range (`develop..HEAD`). Each commit subject must use the
   repository's allowed Conventional Commits syntax, normally:

   `type(optional-scope): description`

   An optional `!` may precede the colon. In this repository, use one of `build`, `chore`, `ci`,
   `docs`, `feat`, `fix`, `perf`, `refactor`, `revert`, `style`, or `test`, followed by a
   non-empty imperative description. Preserve authorship and commit content. Rewrite invalid
   subjects with a focused interactive rebase or equivalent non-destructive amend operation,
   then re-run the validation. If the rebase changed published history, push only with
   `--force-with-lease` to the feature branch's configured remote, and only after the code
   review gate below has passed or its rebase rule exempts the push.
4. Run the repository's required validation commands before opening the PR. Fix genuine failures
   in the branch, adding only Conventional Commits-compliant commits (or amending an unpushed
   fix), and rerun the affected checks. Do not weaken security, remove tests, skip required
   checks, or mask an environmental/provider failure as a code fix.
5. OpenSpec archive check, before the review gate and again before every push: list
   `git diff --name-only --no-renames <remote>/develop...HEAD -- openspec/changes` and take each
   `openspec/changes/<name>/` path whose `<name>` is not `archive`. Every such change must be
   archived on this branch: its `openspec/changes/<name>/` directory no longer exists at `HEAD`,
   a matching `openspec/changes/archive/<date>-<name>/` exists, and
   `npm run openspec -- validate --all --strict --no-interactive` passes. If one is still
   active, archive it under [deliver-issue](../deliver-issue/SKILL.md)'s task and archive rules
   when all its tasks are complete; otherwise stop before pushing and report the change and its
   open tasks. Branches that touch no OpenSpec change skip this check.

## Outgoing secret check

Use `git -c core.hooksPath=.githooks push` for every push, including force-with-lease.
The repository pre-push hook scans outgoing committed blobs and blocks on missing
Sonar, findings or scan errors. Never bypass it with `--no-verify`.

## Code review gate

1. Before pushing or creating the pull request, read the repository-local [code-review
   skill](../code-review/SKILL.md) and execute it from the session worktree on the rebased
   branch's complete diff. Name the base and range explicitly as `<remote>/develop...HEAD`, with
   the same freshly fetched remote-qualified `develop` used for the rebase. Request `depth=max`,
   `max-findings=all`, and `report-only`: complete its five review perspectives without editing
   files or posting PR comments. These parameters describe the local review workflow, not host
   CLI flags. This review is mandatory; do not create the PR without it. A round counts only
   when its report records the reviewed range and base/head SHAs, depth `max`, findings cap
   `none`, completed status, and findings count. Missing, interrupted, partial, truncated,
   capped, lower-depth, or stale reports are not clean rounds. Each review invocation counts
   toward the three-round limit below. Direct reading of the local skill is sufficient; do not
   block on a missing host slash command or claim that copying Markdown installs host tooling.
2. Resolve every finding before creating the PR, using the severity and scope rules of
   `REVIEW.md`. Fix valid findings in the branch with Conventional Commits-compliant commits,
   add or adjust focused tests, and rerun the affected validation. A finding is resolved without
   a code change only on one of the following grounds, each with concrete evidence:
   - Not actionable: a false positive, disproved by the cited file and line, code, test, or
     `<remote>/develop` behavior.
   - Omitted by `REVIEW.md`: a point in a category that `REVIEW.md` lists as omitted in its
     "Severity and noise budget" section (for example cosmetic preferences, speculative future
     needs, or a P3 nit beyond the budget); cite the section and category. A point that alleges
     a concrete defect with an established trigger, or that reports missing schema-upgrade
     evidence under its "Persistence, migrations, and recovery" section, is never omitted on
     this ground. Every ground, including out of scope, is a waiver: waiving a finding of P2 or
     higher needs the user's explicit confirmation, and all waivers are listed in the chat
     before auto-merge is enabled for each reviewed head.
   - Out of scope: the freshly fetched `<remote>/develop` already shows the same defect at the
     same code, and the branch neither adds, modifies, nor newly exposes it (no new caller,
     consumer, read path, persistence reader, changed input, or changed guard on its path), as
     `REVIEW.md` keeps newly exposed defects in scope; it predates the branch, so record it with
     that path analysis, and it does not block the gate.

   Record each such finding with its ground and evidence in the PR body and the final report. If
   the evidence is not conclusive, treat the finding as valid or ask the user; never resolve a
   finding by weakening security, tests, or required checks. A later round may re-raise a waived
   finding; the waiver stands while its recorded evidence still applies to the current head,
   otherwise treat the finding as valid.
3. After fixes, run `/code-review` again on the same explicit range. The gate passes only when a
   round on the current head reports no unresolved actionable findings; fixes from a round are
   never pushed without a following clean round. A gate run allows at most three review rounds
   in total and lasts until its head is pushed or the run stops; fixes after a clean round
   continue the same run and its cap. A new run needs a changed head after a push or an explicit
   user instruction. A finding is the same as an earlier one when it names the same file and
   defect, even if reworded or shifted by a few lines; a re-raised finding that is neither fixed
   nor validly waived stays unresolved. If the third invocation of a run is not a valid clean
   round, whether it reports actionable findings or is interrupted or invalid, stop before
   pushing and report the remaining findings or the run's state with proposed resolutions to the
   user. After a clean round, rerun the required validation on the final tree and mention the
   review rounds and their resolutions in the PR body. Any change to tracked files after a clean
   round, including a validation or test fix, starts another round before it is pushed; a
   validation rerun that changes nothing needs none. If that change follows a clean third round,
   stop before pushing and report the change with its proposed fix to the user, because the run
   has no round left.
4. Rebase rule: a head that only replays feature commits onto a newer `<remote>/develop` needs
   no new round when their last gate round was clean with no unresolved findings, `git range-diff` shows the feature commits unchanged, and `<remote>/develop`'s changes since the
   reviewed base touch no file the feature changes and no module, dependency, or symbol it
   imports, calls, or changes (so no `develop` change references a symbol, module, or schema the
   feature changes); the required validation must still pass on the rebased tree before the push
   (for a head the workflow moved, the required checks at merge time are that validation).
   Compute the file overlap mechanically with `git diff --name-only --no-renames <reviewed-base> <remote>/develop` against the feature's changed files from the same command, so renamed-away
   paths count, and keep the symbol-level judgment as a secondary check. A conflict resolution
   or any other change to the feature diff runs the gate. The repository's
   `auto-rebase-squash.yml` workflow rebases open PRs with squash auto-merge when `develop`
   advances, and it applies no overlap test. That protection holds only while a monitor runs. On
   every monitoring iteration, if the head changed without a push of yours, apply this rule to
   the new head; when it fails, disable auto-merge with `gh pr merge <number> --disable-auto`
   and run the gate before re-enabling it. Keep auto-merge disabled while a gate run or feedback
   repair is in progress, and disable it before any stop, hand-off, or other unmonitored state
   with the PR open; re-enable it only after the gate or this rule has cleared the current head,
   including heads the workflow moved.
5. After a gate run on a head that already has a PR, update the PR body once per run with that
   head's SHA, the reviewed base SHA, the rounds run, and each waiver with its evidence, so
   every waiver names the head it covers.

## Create and monitor the pull request

1. Push the rebased feature branch only after the code review gate has passed or its rebase rule
   exempts the push. Create exactly one non-draft PR targeting `develop`, using an English
   Conventional Commit-style title and an English body that summarizes the changes and
   validation. Reuse an existing open PR for the same head/base instead of creating a duplicate.
   Register every created or worked-on PR with the thread's PR-linking tool when available,
   immediately after selecting or creating it; verify thread links before finishing.
2. Enable `gh pr merge <number> --auto --squash` once all currently visible feedback is
   reconciled and repository permissions/checks allow it. Pending required checks alone do not
   require delaying auto-merge; they still gate the merge. Disable it with `gh pr merge <number> --disable-auto` while actionable feedback is being repaired and before any gate run or
   push-bound change starts.
3. Preserve Markdown formatting whenever creating or replying to PR content. Pass bodies as
   structured text with actual line-feed characters (U+000A), not the literal two-character
   sequence `\n`. For a PR description, use `gh pr create --body-file <file>` or `gh pr edit <number> --body-file <file>`; for a top-level conversation comment or status comment, use `gh pr comment <number> --body-file <file>`. For an inline review reply, use the review-comment
   reply endpoint `POST /repos/<owner>/<repo>/pulls/<number>/comments/<comment-id>/replies`
   through the GitHub API. Do not use `gh pr comment` for descriptions or inline replies, and do
   not use a quoted shell argument containing `\n`, because shells such as PowerShell pass that
   sequence literally. Decode escaped newlines exactly once before posting and verify that
   intended list items appear on separate lines.
4. Monitor until merged using the host's event-driven PR watcher when available.
   After reconciling the current head, register `watch_pull_request` and yield;
   resume this workflow on each notification, re-read the head, and reconcile
   feedback before evaluating checks. Watcher registration is a monitored wait,
   not completion or an unmonitored handoff: auto-merge may remain enabled only
   for a head already cleared by the review and clean-feedback gates. If no
   watcher is available, poll checks, reviews, comments, and threads at bounded
   intervals (about 30 seconds; never block updates for more than 60 seconds).
   Do not run a second polling loop alongside an active watcher. Delegated child
   agents return the PR URL, head SHA, and pending state to their parent instead
   of watching. Do not finish while the PR is merely open, auto-merge-enabled,
   or apparently complete. Before evaluating checks on each wake or iteration,
   reconcile all PR feedback:

   - Query both review threads and top-level issue comments for the current head. Review threads
     must be inspected through GitHub's GraphQL `reviewThreads` data, including each thread's
     `isResolved` state; REST review-comment data alone is insufficient.
   - Treat every new or unanswered comment, every unresolved review thread, and every
     `CHANGES_REQUESTED` review on the current head as unfinished work. Understand the feedback,
     implement the necessary fix when it is valid, and run the relevant tests. Reply to the
     comment with the result. Resolve the review thread only after the response and fix are
     complete. If feedback is not actionable, reply with the concrete reason before resolving
     the thread; never resolve or dismiss feedback merely to make the PR green. Resolving a
     P2-or-higher thread as not actionable is a waiver and follows the gate's confirmation and
     listing rule.
   - Issue comments have no review-thread resolve flag. They are closed for this workflow only
     when they have a clear reply and any requested action is complete. Re-check comments after
     every push because new bot or reviewer feedback may arrive for the new commit.
   - After feedback is handled, verify that the current head still has zero unresolved review
     threads and no unanswered comments. Keep auto-merge disabled until this clean-feedback gate
     has passed. If a new comment appears, disable auto-merge immediately with `gh pr merge <number> --disable-auto`, then return to the feedback step instead of relying on the merge
     result.

   - After the clean-feedback gate passes, enable squash auto-merge with `gh pr merge <number> --auto --squash` on every iteration where the current head has no unresolved feedback, no
     gate run or push-bound change is in progress, and the gate or its rebase rule has cleared
     the current head (including a head changed by anyone other than this agent), regardless of
     whether required checks are still pending or already passing. Re-enable it after every
     later push only after the same gate passes again.

   For the remaining PR states:

   - Any later change to the branch's own diff, such as a feedback fix, a CI fix, or a conflict
     resolution, must pass the code review gate on the new head before it is pushed; the gate's
     rebase rule covers a rebase that leaves the feature commits unchanged.
   - If the branch is behind `develop` or has merge conflicts, fetch `develop`, rebase again,
     resolve and test the conflicts, validate commit subjects, pass the code review gate for
     every conflict resolution (a conflict-free replay follows the rebase rule), and push with
     `--force-with-lease`. Re-enable auto-merge only after the clean-feedback gate passes for
     the new head.
   - If required checks fail, inspect the failed job and logs, fix the underlying code or
     configuration, run the relevant local checks, create a compliant commit, pass the code
     review gate on the new head, push it, and continue monitoring. Do not retry indefinitely
     without diagnosing the failure.
   - Require Gitar's native `Gitar` check for the current head under `.github/AGENTS.md`. A
     missing, pending, or failed check blocks merging. Inspect the reviewed commit and reconcile
     findings after every push. Resolve every review thread, including outdated threads and
     those from other reviewers, only after fixing or reconciling its finding. No bot or user
     bypass is allowed. Local review is additional evidence, not proof of a hosted review.
   - If checks are pending, register/reuse the event-driven watcher and yield, or wait for the
     next bounded poll on hosts without it. Continue monitoring after every fix, push, review
     response, thread resolution, rebase, and auto-merge state change. Do not stop at green
     checks, resolved comments, enabled auto-merge, or a bot's completion message: finish only
     after GitHub reports the PR as actually merged, with `mergedAt` and a merge commit, all
     final required checks green, every review thread resolved, and every top-level comment
     answered with its requested action complete. If GitHub reports a required review,
     permission, unavailable runner, merge queue, or policy requirement that the agent cannot
     satisfy, report it clearly and stop rather than bypassing it.
   - If the PR is closed without merging, stop and report that outcome; do not reopen or create
     a replacement without user direction.

5. Before final completion or a blocked handoff, call `unwatch_pull_request` when available to
   stop watching. An open PR handed back without active monitoring must have auto-merge disabled
   under the gate rules above. Finish successfully only after all of these completion gates are
   true: GitHub reports `state=MERGED`, `mergedAt` is non-null, a merge commit is present, all
   review threads are resolved, every top-level PR comment has a reply or its requested action
   is complete, and the final required checks passed for the merged head. Auto-merge being
   enabled, a bot saying "Completed", or a successful-looking summary comment is not merge
   evidence. Report the PR URL, final merge status, the validation performed, and any conflict,
   comment, or CI fixes made. If the workflow stops, report the exact state and the smallest
   user action needed to continue.
