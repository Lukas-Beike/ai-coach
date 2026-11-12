# Local code graph

Worktree preparation uses `python scripts/prepare_worktree.py` to install Node
development dependencies and the locked Playwright Chromium, the hash-locked
`ruff`, `mypy` and `tzdata` pins from `requirements-dev.txt` into that
interpreter (`tools/quality_baseline.py` runs the tools as `python -m`; Windows
has no system time zone database), set up Graphify, generate the first graph,
and build this checkout's browser-test app image (skipped when Docker is not
running). Agent worktrees run it too, so each gets its own `node_modules`. It then
prints an advisory list of pinned Python (queried at pypi.org) and npm
(`npm outdated`) packages that have a newer release; this needs network access,
installs nothing and never changes the exit code.
Graphify's version comes from the hash-locked `requirements-graphify.txt`.
Run the tooling scripts with Python 3.14 or newer. Setup requires Python 3.14
for its environment and selects it explicitly (`py -3.14` on Windows,
`python3.14` on POSIX) when called with a newer interpreter.
One shared virtual environment per version and lock hash lives under
`%LOCALAPPDATA%/ai-coach/graphify` on Windows, or
`$XDG_DATA_HOME/ai-coach/graphify` (default `~/.local/share/ai-coach/graphify`)
on POSIX. Graphs, update locks, isolated home and exports stay per worktree
under `.graphify-local/`. Session hooks never install missing tools.
Preparation uses `update --preparation` with a 600-second budget; hooks and
plain `update` keep 180 seconds. Graphify does not require Sonar; source allowlists
and credential/runtime exclusions remain enforced.
Codex and Claude Code are configured to run the same local `update
--session-start` command synchronously at session start and resume. This keeps
the graph fresh before use; after edits during a session, run
`python scripts/graphify_local.py update` before querying it. Check `status`
first if an update could not complete.

As a manual fallback, run `python scripts/graphify_local.py setup`, then
`python scripts/graphify_local.py update`. Setup serializes creation, verifies
every package hash and reuses a ready environment without installing again.
`python scripts/graphify_local.py prune` explicitly removes other unlocked shared
environments that no running Graphify command uses; nothing prunes automatically. Old `.graphify-local/venv` directories
are unused and may be removed manually. Only setup and worktree preparation may
download packages; subsequent graph operations stay offline. Use
`status`, `query <terms>`, `path <source> <target>`, and `explain <symbol>` to
inspect availability and navigate; queries select the active graph
automatically. Run `python scripts/graphify_local.py export html --output .graphify-local/exports/graph.html` or
`python scripts/graphify_local.py export wiki --output .graphify-local/exports/wiki`
for local views; exports are restricted to `.graphify-local/exports/`. `mcp`
starts the optional local stdio MCP server. Its read-only snapshot exposes
`graph_query`, `graph_node`, `graph_path`, and `graph_stats`, with no upstream
PR tools; restart the server after graph edits to refresh the snapshot. The hook
does not read session payloads or transcripts. Native host activation has not
been verified; the hook tests do not prove Codex or Claude dispatch. Codex may
require repository trust approval in `/hooks` before activation.

The graph represents structural relationships only. Semantic documentation
enrichment is disabled; it requires a separately installed, explicitly local
model and is outside this integration. Always check current source, callers,
tests, and applicable instructions before acting on graph findings. Broad or
stale matches can be incomplete; use ordinary source search when needed.

The Codex hook is configured in `.codex/hooks.json` and refreshes Graphify without
scanning incoming prompts. Codex requires accepting the repository hook in its
`/hooks` trust UI. Claude Code uses `.claude/settings.json` and requires its
normal repository trust. Do not bypass either trust prompt. The checked-in
Claude hook uses the documented PowerShell shell on Windows. For POSIX Claude
installations, use the included `scripts/graphify-session-start.sh` and this
SessionStart command configuration:

```json
{
  "type": "command",
  "command": "sh \"$(git rev-parse --show-toplevel)/scripts/graphify-session-start.sh\"",
  "shell": "bash",
  "timeout": 240
}
```

Both launchers resolve the repository root, including when the session starts
in a nested directory. If the worker or Python is unavailable, they print a
short status message, do not install anything, and let the session continue.

On 2026-10-24, T3 Code delivered the Claude SessionStart hook in a task worktree.
This observation does not establish delivery by every host/provider; run the
update manually if the hook is skipped. After merge, the T3 worktree-creation
script can invoke `python scripts/prepare_worktree.py`; host configuration is
separate from this repository.

AI documentation is checked by the existing
`Validate repository AI documentation` workflow. Locally, after secrets scans,
run `python -m unittest discover -s tests -p test_ai_docs_contract.py -v`.
These structural checks catch broken guidance/discovery; they do not measure
coding quality. Behavioral comparisons use the repository skill-evaluation workflow
with synthetic tasks and isolated sessions, without live accounts or deployments.

For Claude Code, verify instruction loading in the actual session:

1. Run `claude --version`; native AGENTS support requires 2.1.277+, with broader
   session support from 2.1.281. Restart after upgrading.
2. In `/config`, check **Project instructions**. The default
   `claude-md-or-agents-md` works when no project/ancestor `CLAUDE.md`,
   `.claude/CLAUDE.md`, or `CLAUDE.local.md` shadows AGENTS. If one is needed,
   choose `claude-md-and-agents-md`; ensure the built-in AGENTS plugin is enabled.
3. Use `/memory` to confirm root instructions loaded; after reading backend,
   frontend, or test files, verify their scoped instructions too.

Claude instruction loading does not auto-discover skills under `.agents/`.
Follow the skill index explicitly; do not copy skills globally. Project
workflows remain repository-owned; app-supplied skills and their tools have
[separate replacement constraints](../.agents/skills/references/app-skill-ownership.md).
AGENTS and review text guide behavior; CI, permissions, and hooks provide
deterministic enforcement.
These files do not activate hosted reviews or prove session configuration.

References: [Claude best practices](https://code.claude.com/docs/en/best-practices)
and [AGENTS loading](https://code.claude.com/docs/en/memory#agents-md).
