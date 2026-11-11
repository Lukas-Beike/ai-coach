# Optional local OpenSpec

[OpenSpec](https://github.com/Fission-AI/OpenSpec) is pinned in
`package-lock.json` as a local development dependency. It manages behavior
specifications and change plans; the application does not load it. Node.js
must satisfy the `engines` ranges in `package-lock.json`. Install and check it
from the task worktree. The preparation entry point also sets up
Graphify, generates its first graph, and lists pinned Python and Node packages
with a newer release; it still installs only the locked versions. Configure
worktree creation to invoke it after the script reaches develop:

```powershell
python scripts/prepare_worktree.py
npm.cmd run openspec -- --version
npm.cmd run openspec -- list --specs
npm.cmd run openspec -- validate --all --strict --no-interactive
```

If only Node dependencies need preparing, `npm.cmd ci --ignore-scripts` remains
the manual fallback. Use `npm` instead of `npm.cmd` outside Windows and in Git
Bash, where `npm.cmd` breaks arguments that contain spaces. The repository script disables
OpenSpec telemetry on every invocation; no global CLI, skills, profile changes,
store, hosted service, or model credentials are required. Its config/data homes
are isolated under ignored `.openspec-local/` in the working directory, including
profile migrations triggered by `init` or `update`. The universal
`agents` adapter installs six skills directly into `.agents/skills/`, shared
by agents that support that directory. Other agents read the linked
skills in the index. Restart a session if its skill catalog was already loaded.
Host-specific slash commands are not installed; plain-language requests such
as "use openspec-propose to plan a backfill of Coach write authorization" work
through the repository skill index.

To regenerate those skills from the installed, pinned CLI:

```powershell
npm.cmd run openspec -- init --tools agents --profile core --no-animation
```

Review the generated diff and retain the project context/rules in
`openspec/config.yaml`. Do not pass `--language` when regenerating an existing
project; the language instruction is already in its context. Dependabot bumps
the pin; the daily `Daily OpenSpec update` workflow then runs `openspec update`
with the locked CLI on `develop` in a job without write credentials and, when
the generated skills change, opens a `chore/openspec-update` PR. It merges
automatically once `test` passes and only if every changed file is a generated
`openspec-*` skill. Do not run the bare `openspec config profile`: that changes user-global
configuration. Existing
AGENTS boundaries and authorization take precedence over generated workflows;
OpenSpec does not replace repository review, orchestration, or validation.

**Application specifications.** The [OpenSpec baseline](../openspec/README.md)
documents the application's behavior by capability. Its
[coverage ledger](../openspec/COVERAGE.md) is a frozen snapshot of the baseline
revision and is not maintained further; the
[Coach tool map](../openspec/COACH_TOOLS.md) is generated from the tool specs
and checked by a test. A valid document is not proof of runtime conformance.

OpenSpec is optional. Most changes put their acceptance criteria in the PR body,
but a behavior change still updates the affected main specs in `openspec/specs/`
directly; the `pr` workflow finds them by the changed files they cite.
Use an OpenSpec change for a larger feature (a new capability or a behavior change
across several flows) or when asked, created with the CLI:

```powershell
npm.cmd run openspec -- new change add-example-capability
npm.cmd run openspec -- instructions proposal --change add-example-capability --json
npm.cmd run openspec -- archive add-example-capability --yes
```

Keep it to a proposal, the spec delta, and tasks finished before merge. Archive
it in the same branch as the implementation; `archive` also updates the main
specs. Then delete the archived folder under `openspec/changes/archive/` in the
same PR; git history keeps it. The `pr` workflow blocks a push while a touched change is still active.
