---
name: pr
description: "When the user's entire message is `pr`, rebase the current feature branch onto develop, repair conflicts, validate Conventional Commits and tests, create a GitHub pull request, enable squash auto-merge, and monitor it through merge. Do not use for ordinary PR questions or longer requests."
---

# Pull Request Workflow

Use this skill only when the user's message consists of the standalone command `pr` (ignoring surrounding whitespace). Treat that command as authorization for the complete workflow below, including rewriting the current feature branch, pushing it, creating a pull request, enabling squash auto-merge, and fixing branch conflicts or failed CI tests. Keep the user updated at meaningful state changes.

## Preconditions

1. Work in the repository and current worktree from which the command was issued. Read the applicable `AGENTS.md` files before changing anything and follow their test, branch, commit, and security rules.
2. Verify that Git and an authenticated GitHub CLI (`gh`) or an equivalent configured GitHub integration are available. Do not print credentials, tokens, environment files, database contents, or provider payloads.
3. Identify the current branch, its upstream remote, and the `develop` branch. The current branch must be a feature/topic branch; never rebase or push `develop`, `main`, or another protected branch.
4. Require a clean working tree, including untracked files. Do not stash, reset, discard, or overwrite unrelated user work. Stop and report the exact blocker if the tree is dirty, the branch is ambiguous, authentication is missing, or `develop` cannot be found.

## Rebase and commit validation

1. Fetch the latest `develop` from the selected remote, then rebase the current feature branch onto it. Preserve the user's commits and file changes; do not use destructive reset or checkout commands.
2. Resolve conflicts by understanding both sides and applying the repository's intended behavior. Inspect conflict markers, the surrounding code, and relevant tests. After each resolution, stage only the intended files and continue the rebase. Run the relevant tests after the rebase. If a conflict concerns an ambiguous product decision, secrets, durable data, or an unsafe change that cannot be inferred, stop and ask the user rather than guessing.
3. Inspect every commit in the feature range (`develop..HEAD`). Each commit subject must use the repository's allowed Conventional Commits syntax, normally:

   `type(optional-scope): description`

   An optional `!` may precede the colon. In this repository, use one of `build`, `chore`, `ci`, `docs`, `feat`, `fix`, `perf`, `refactor`, `revert`, `style`, or `test`, followed by a non-empty imperative description. Preserve authorship and commit content. Rewrite invalid subjects with a focused interactive rebase or equivalent non-destructive amend operation, then re-run the validation. If the rebase changed published history, push only with `--force-with-lease` to the feature branch's configured remote.
4. Run the repository's required validation commands before opening the PR. Fix genuine failures in the branch, adding only Conventional Commits-compliant commits (or amending an unpushed fix), and rerun the affected checks. Do not weaken security, remove tests, skip required checks, or mask an environmental/provider failure as a code fix.

## Create and monitor the pull request

1. Push the rebased feature branch. Create exactly one non-draft PR targeting `develop`, using an English Conventional Commit-style title where practical and an English body that summarizes the changes and validation. Reuse an existing open PR for the same head/base instead of creating a duplicate.
2. Enable squash auto-merge with the GitHub CLI equivalent of `gh pr merge <number> --auto --squash`. Confirm that auto-merge is enabled and record the PR URL/number.
3. Preserve Markdown formatting whenever creating or replying to a PR comment. Pass the comment body as structured text with actual line-feed characters (U+000A), not the literal two-character sequence `\n`. When using the GitHub CLI from a shell, write the body to a temporary UTF-8 file and use `gh pr comment <number> --body-file <file>`; do not use a quoted shell argument containing `\n`, because shells such as PowerShell pass that sequence literally. Decode escaped newlines exactly once before posting and verify that intended list items appear on separate lines. Apply this rule to PR descriptions, review replies, and status comments.
4. Poll the PR and its checks in short intervals (about 30 seconds; never block updates for more than 60 seconds). Continue until the PR is merged or a genuine blocker requires the user. For each state:

   - If the branch is behind `develop` or has merge conflicts, fetch `develop`, rebase again, resolve and test the conflicts, validate commit subjects, and push with `--force-with-lease`. Re-enable auto-merge if GitHub cleared it.
   - If required checks fail, inspect the failed job and logs, fix the underlying code or configuration, run the relevant local checks, create a compliant commit, push it, and continue monitoring. Do not retry indefinitely without diagnosing the failure.
   - If checks are pending, wait and poll. If GitHub reports a required review, permission, unavailable runner, merge queue, or policy requirement that the agent cannot satisfy, report it clearly and stop rather than bypassing it.
   - If the PR is closed without merging, stop and report that outcome; do not reopen or create a replacement without user direction.

4. Finish only after GitHub reports the PR as merged. Report the PR URL, final merge status, the validation performed, and any conflict or CI fixes made. If the workflow stops, report the exact state and the smallest user action needed to continue.
