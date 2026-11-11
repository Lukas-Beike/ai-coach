# Development

## AI coding instructions

Keep shared policy in [AGENTS.md](../AGENTS.md) and its scoped files, PR review
criteria in [REVIEW.md](../REVIEW.md), and task workflows in the
[repository skill index](../.agents/skills/README.md). Load relevant workflows on
demand; keep deployment commands here. All project skills have one canonical
root, `.agents/skills/`; full review and `pr` were moved from the legacy `.codex/`
root without duplicate copies. No duplicate `CLAUDE.md` is needed.

Rules without exceptions are enforced, not just written down:
[`.claude/settings.json`](../.claude/settings.json) denies agent file access to any
`.env`/`.env.local` and to the `data/` directory of this checkout and the
primary `ai-coach` checkout. Before every shell command it runs
`scripts/hooks/guard_private_paths.py`, a tested text-matching safety net (not
a sandbox) that blocks clear `.env`, `data`, and Garmin token path forms with no
exceptions, so you run the Docker runbook commands that pass `.env` or mount
`data` yourself. It also blocks commands that merely mention such a path, such
as a commit message; pass that text through a file.
`.claude/agents/` defines the `explorer` (Haiku, low effort, read-only),
`implementer` (Sonnet, medium), and `reviewer` (Sonnet, medium, read-only)
subagents.

Sessions default to `medium` effort (`effortLevel` in `.claude/settings.json`);
raise it with `/effort high` for tricky work. Agents may not go above `high`
without your approval. `/pr`, `/deliver-issue`, `/next-issue`, and `/ai-coach-release-unraid`
are user-only Claude Code commands (`disable-model-invocation: true`) that load
the canonical workflows in `.agents/skills/`.

To keep usage down, start a fresh session (`/clear`) for each unrelated task;
every turn re-sends the whole conversation. Check `/usage` occasionally to see
which skills and subagents earn their cost, and delete skills nobody loads.

The local [code-review skill](../.agents/skills/code-review/SKILL.md) adapts
Claude's review workflow for PRs and pre-push branch diffs. Agents read it
directly; the `pr` workflow requires no host-specific slash command.

The [orchestration skill](../.agents/skills/orchestrated-plan-implementation/SKILL.md)
decides per task whether delegating to subagents pays off; by default the main
model does the work. Delegated tasks use fixed tiers without a model question:
Claude Haiku alternating with Gemini Flash for easy tasks, Claude Sonnet for
standard work, and Claude Opus only for genuinely hard or risky tasks, each at
its newest available version. Writers use isolated worktrees; the main model
reviews and integrates their branches.

The [retro skill](../.agents/skills/ai-coach-retro/SKILL.md) runs on request and
briefly after a `deliver-issue` run. It prefers removing or shortening
instructions; a new rule needs an observed failure that a hook or test cannot
prevent.

Coding tasks default to the repository's [Ponytail workflow](../.agents/skills/ai-coach-ponytail/SKILL.md)
in `full` mode: the smallest complete change, reusing existing code before adding
dependencies or abstractions. Any agent can read its Markdown directly;
the external Ponytail plugin is optional. Say `ponytail lite`, `ponytail full`,
`ponytail ultra`, or `stop ponytail` to change the session mode. Repository safety
rules and required checks still apply. This is instruction routing, not a CI gate.

For any coding agent, start in the task worktree and load root plus applicable
scoped AGENTS guidance. Identify the requested behavior, affected owner, and
acceptance check; select the relevant skill, implement the complete flow, inspect
the final diff, and run affected validation. Include final-state evidence and
unverified checks in the handoff. Source code and current workflow behavior take
precedence over remembered paths or stale operating assumptions.

## Secret checks before Git pushes

Source reads, incoming prompts/provider data, and Graphify do not require a secret
scan. Outgoing Git objects are checked by `.githooks/pre-push`, which invokes
`python scripts/check_push_secrets.py`. It scans the lines the outgoing
commits add (so flagged lines already on the branch's base never block a push)
and commit/tag messages, including intermediate commits, in temporary storage and suppresses scanner payload output.
A finding, missing Sonar CLI, or scanner error blocks the push. Deleted refs need
no scan. After a clean scan the hook runs CI's repository quality ratchet
(`python tools/quality_baseline.py`: mypy and Ruff, about 35 seconds
on Windows) on a clean export of HEAD; new findings block the push. Do not use `--no-verify`.

Enable the hook in each clone (the relative path also works in its worktrees):

```powershell
git config core.hooksPath .githooks
```

For a one-off push without changing clone configuration, use
`git -c core.hooksPath=.githooks push <remote> <branch>`.
