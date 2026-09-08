---
name: pr
description: "When the user's entire message is `pr`, rebase the current feature branch onto develop, repair conflicts, validate Conventional Commits and tests, create a GitHub pull request, enable squash auto-merge, and monitor it through merge. Do not use for ordinary PR questions or longer requests."
---

# Pull Request Workflow

Use this skill only when the user's message consists of the standalone command `pr` (ignoring surrounding whitespace). Treat that command as authorization for the complete workflow below, including rewriting the current feature branch, pushing it, creating a pull request, enabling squash auto-merge, and fixing branch conflicts or failed CI tests. Keep the user updated at meaningful state changes.

## Preconditions

1. Resolve the repository and worktree from the session's recorded implementation worktree, not from the directory in which the `pr` command happens to be issued. The command may be started from another checkout, but all PR work must use the worktree where this session created or modified the feature. Confirm that path with `git rev-parse --show-toplevel`, then read the applicable `AGENTS.md` files there and follow its test, branch, and security rules.
2. If the session worktree cannot be identified unambiguously, or if its feature branch and changes do not match the work performed in this session, stop and report the exact blocker. Never fall back to the primary checkout, use the command's current directory, or infer the feature branch from another worktree. Once identified, complete the entire PR workflow from the session worktree, including rebase, fixes, validation, pushes, PR operations, and merge verification.
3. Verify that Git and an authenticated GitHub CLI (`gh`) or an equivalent configured GitHub integration are available. Do not print credentials, tokens, environment files, database contents, or provider payloads.
4. Identify the current branch, its upstream remote, and the `develop` branch. The current branch must be a feature/topic branch; never rebase or push `develop`, `main`, or another protected branch.
5. Require a clean working tree, including untracked files. Do not stash, reset, discard, or overwrite unrelated user work. Stop and report the exact blocker if the tree is dirty, the branch is ambiguous, authentication is missing, or `develop` cannot be found.

## Rebase and commit validation

1. Fetch the latest `develop` from the selected remote, then rebase the current feature branch onto it. Preserve the user's commits and file changes; do not use destructive reset or checkout commands.
2. Resolve conflicts by understanding both sides and applying the repository's intended behavior. Inspect conflict markers, the surrounding code, and relevant tests. After each resolution, stage only the intended files and continue the rebase. Run the relevant tests after the rebase. If a conflict concerns an ambiguous product decision, secrets, durable data, or an unsafe change that cannot be inferred, stop and ask the user rather than guessing.
3. Inspect every commit in the feature range (`develop..HEAD`). Each commit subject must use the repository's allowed Conventional Commits syntax, normally:

   `type(optional-scope): description`

   An optional `!` may precede the colon. In this repository, use one of `build`, `chore`, `ci`, `docs`, `feat`, `fix`, `perf`, `refactor`, `revert`, `style`, or `test`, followed by a non-empty imperative description. Preserve authorship and commit content. Rewrite invalid subjects with a focused interactive rebase or equivalent non-destructive amend operation, then re-run the validation. If the rebase changed published history, push only with `--force-with-lease` to the feature branch's configured remote.
4. Run the repository's required validation commands before opening the PR. Fix genuine failures in the branch, adding only Conventional Commits-compliant commits (or amending an unpushed fix), and rerun the affected checks. Do not weaken security, remove tests, skip required checks, or mask an environmental/provider failure as a code fix.

## Create and monitor the pull request

1. Push the rebased feature branch. Create exactly one non-draft PR targeting `develop`, using an English Conventional Commit-style title where practical and an English body that summarizes the changes and validation. Reuse an existing open PR for the same head/base instead of creating a duplicate.
2. Keep auto-merge disabled while the initial checks and all currently visible feedback are being reconciled. Do not enable `gh pr merge <number> --auto --squash` merely because the PR was created or checks are pending.
3. Preserve Markdown formatting whenever creating or replying to PR content. Pass bodies as structured text with actual line-feed characters (U+000A), not the literal two-character sequence `\n`. For a PR description, use `gh pr create --body-file <file>` or `gh pr edit <number> --body-file <file>`; for a top-level conversation comment or status comment, use `gh pr comment <number> --body-file <file>`. For an inline review reply, use the review-comment reply endpoint `POST /repos/<owner>/<repo>/pulls/<number>/comments/<comment-id>/replies` through the GitHub API. Do not use `gh pr comment` for descriptions or inline replies, and do not use a quoted shell argument containing `\n`, because shells such as PowerShell pass that sequence literally. Decode escaped newlines exactly once before posting and verify that intended list items appear on separate lines.
4. Enter a repeat-until-merged loop. Poll the PR, its checks, reviews, comments, and review threads in short intervals (about 30 seconds; never block updates for more than 60 seconds). Do not finish while the PR is merely open, auto-merge-enabled, or apparently complete. Before evaluating the checks on each iteration, reconcile all PR feedback:

   - Query both review threads and top-level issue comments for the current head. Review threads must be inspected through GitHub's GraphQL `reviewThreads` data, including each thread's `isResolved` state; REST review-comment data alone is insufficient.
   - Treat every new or unanswered comment, every unresolved review thread, and every `CHANGES_REQUESTED` review on the current head as unfinished work. Understand the feedback, implement the necessary fix when it is valid, and run the relevant tests. Reply to the comment with the result. Resolve the review thread only after the response and fix are complete. If feedback is not actionable, reply with the concrete reason before resolving the thread; never resolve or dismiss feedback merely to make the PR green.
   - Issue comments have no review-thread resolve flag. They are closed for this workflow only when they have a clear reply and any requested action is complete. Re-check comments after every push because new bot or reviewer feedback may arrive for the new commit.
   - After feedback is handled, verify that the current head still has zero unresolved review threads and no unanswered comments. Keep auto-merge disabled until this clean-feedback gate has passed. If a new comment appears, disable auto-merge immediately with `gh pr merge <number> --disable-auto`, then return to the feedback step instead of relying on the merge result.

   For the remaining PR states:

   - If the branch is behind `develop` or has merge conflicts, fetch `develop`, rebase again, resolve and test the conflicts, validate commit subjects, and push with `--force-with-lease`. Re-enable auto-merge only after the clean-feedback gate passes for the new head.
   - If required checks fail, inspect the failed job and logs, fix the underlying code or configuration, run the relevant local checks, create a compliant commit, push it, and continue monitoring. Do not retry indefinitely without diagnosing the failure.
   - If checks are pending, wait and poll. Once the current head has passed the clean-feedback gate, enable squash auto-merge with `gh pr merge <number> --auto --squash`; re-enable it after every later push only after the same gate passes again. If GitHub reports a required review, permission, unavailable runner, merge queue, or policy requirement that the agent cannot satisfy, report it clearly and stop rather than bypassing it.
   - If the PR is closed without merging, stop and report that outcome; do not reopen or create a replacement without user direction.

5. Finish only after all of these completion gates are true: GitHub reports `state=MERGED`, `mergedAt` is non-null, a merge commit is present, all review threads are resolved, every top-level PR comment has a reply or its requested action is complete, and the final required checks passed for the merged head. Auto-merge being enabled, a bot saying "Completed", or a successful-looking summary comment is not merge evidence. Report the PR URL, final merge status, the validation performed, and any conflict, comment, or CI fixes made. If the workflow stops, report the exact state and the smallest user action needed to continue.
