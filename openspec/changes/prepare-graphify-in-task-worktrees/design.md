# Design

## Context

See proposal.md for motivation. Current state (inspected on `eed88ccef`):
`runtime(root)` is `root/.graphify-local`; `executable()` and
`python_executable()` point into `.graphify-local/venv`; `_setup()` creates that
venv and runs `pip install graphifyy[mcp]==VERSION` without hashes;
`update()` returns 2 with "run setup" when `verify_version()` fails. `VERSION`
is a constant in `scripts/graphify_local.py`. `local_env()` already isolates
HOME/APPDATA under `.graphify-local/home`. The T3 project has one
`runOnWorktreeCreate` script, `npm.cmd ci --ignore-scripts`, which did not run
for this worktree (no `node_modules`), cause unknown. The local PowerShell
execution policy is `Restricted`.

A dry-run resolution of `graphifyy[mcp]==0.9.93` on Windows/Python 3.14 yields
59 wheels. One is platform-gated: `mcp` requires
`pywin32>=311; sys_platform == 'win32'`, and pywin32 has no Linux wheels.

## Goals / Non-Goals

**Goals:**

- A fresh worktree prepared by `scripts/prepare_worktree.py` reports
  `Graphify local: current` and the SessionStart hook succeeds without manual
  commands.
- Every Graphify package installed is hash-verified from a reviewed lock that
  Dependabot can update.

**Non-Goals:**

- Changing graph generation, query semantics, the secret scan, the MCP helper,
  or hook launchers beyond what the shared environment requires.
- Automatic pruning, upgrading inside hooks, or any network access outside
  `setup` and `prepare_worktree.py`.
- Configuring the T3 project inside the repository; that is a post-merge host
  action.

## Decisions

1. **Lock pair in the repository root.** `requirements-graphify.in` contains
   `graphifyy[mcp]==0.9.93`; `requirements-graphify.txt` is generated with
   `pip-compile --allow-unsafe --generate-hashes`, matching the existing pairs so
   Dependabot's pip entry for `/` recognizes it. Alternative: a `pyproject`
   optional-dependency group, rejected because the repository already uses
   pip-compile pairs and CI contracts check them.
2. **Platform-independent lock.** The lock must install on Windows and POSIX.
   `pywin32` must appear only with a `sys_platform == "win32"` marker. If
   pip-compile on one platform drops or unconditionally pins it, declare it in
   the `.in` file with that marker so the lock keeps it. The implementer
   verifies by compiling on Windows and in a Linux `python:3.14` container
   and comparing package sets. A test asserts that every package without
   Linux wheels in the lock carries a matching marker (pywin32 today).
   Evidence (2026-10-24, pip-tools 7.6.1): Linux compiles, fresh or over the
   existing lock, yield 58 packages without `pywin32`; Windows yields 59. The
   lock is therefore compiled on Windows. Dependabot PRs (Linux) fail the
   contract test and get a Windows-regenerated lock pushed (user decision
   2026-10-24); the README documents this.
3. **Version from the lock.** `VERSION` is parsed from the `graphifyy==` line of
   `requirements-graphify.txt`; a missing/ambiguous line makes Graphify
   unavailable rather than guessing. A Dependabot bump therefore cannot leave
   the wrapper on the old version. Alternative: a test asserting a constant
   matches the lock, rejected because it would make every Dependabot PR fail.
4. **Shared environment per version and lock hash.** Base directory:
   `%LOCALAPPDATA%\ai-coach\graphify` on Windows, otherwise
   `$XDG_DATA_HOME/ai-coach/graphify` or `~/.local/share/ai-coach/graphify`.
   Environment directory: `<version>-<first 16 hex of SHA-256 of the lock>`.
   Virtual environments are not relocatable, so creation happens in place under
   a process lock `<base>/<name>.lock`; a `ready.json` marker containing the
   version and full lock hash is written last. An environment without a valid
   marker is incomplete: `setup` removes and recreates it under the lock, while
   `update`/`status`/`query` treat it as unavailable. `verify_version()` checks
   the marker and the installed `graphifyy` version. Tests redirect the base
   directory through patching; no new environment variable is introduced
   unless tests of subprocess launchers require it.
5. **Hash-only install.** `setup` runs the shared environment's
   `python -m pip install --require-hashes --only-binary=:all:
   --disable-pip-version-check --no-input -r requirements-graphify.txt`.
   pip itself is not upgraded. A hash mismatch fails setup and leaves no
   `ready.json`.
6. **Per-worktree state stays local.** `.graphify-local/` keeps `home`,
   generations, `current.json`, `update.lock` and exports. `local_env()` is
   unchanged, so the shared environment never receives a worktree-specific
   HOME/APPDATA.
7. **Explicit prune.** `python scripts/graphify_local.py prune` removes sibling
   environments in the shared base other than the current name, skipping any
   whose lock is held, and prints what it removed. Only `prune` deletes shared
   environments.
8. **Python preparation entry point.** `scripts/prepare_worktree.py` resolves
   the repository root, runs `npm ci --ignore-scripts` (resolving `npm`/
   `npm.cmd` via `shutil.which`), then `graphify_local.py setup`, then
   `update`, reporting each step and exiting non-zero if any failed while still
   attempting the remaining independent steps. Python avoids the `Restricted`
   PowerShell policy and duplicate `.ps1`/`.sh` launchers. Alternative: a
   `prepare` subcommand in `graphify_local.py`, rejected because npm setup is
   not Graphify's responsibility.
9. **Offline enforcement test.** With subprocess calls patched, `update`,
   `status`, `query` and the session-start path must never call pip, `-m venv`
   or `npm`, including when the environment is missing.

10. **Incremental secret scan (user decision 2026-10-24).** Measured on this
    host: cold update 178 s, update after a one-file edit 146-152 s, no-op
    1.2 s, against the 180 s budget; about 82 s is the full Sonar scan of
    ~1,200 files. `.graphify-local/scan-cache.json` records SHA-256 content
    hashes that the scanner reported clean, bound to the wrapper schema, the
    scanner's resolved path and file signature, and the corpus rules. An update
    hashes every corpus file, scans only files whose hash is not recorded clean,
    binds the cache also to the signatures of the Sonar CLI's `sonar-secrets-*`
    engine binaries (no resolvable engine: no reuse), keeps only the current
    corpus hashes,
    re-checks file signatures after the scan exactly as today, and records new
    hashes only after their batch passed and signatures are unchanged. Any
    finding, scanner failure, binding mismatch or unreadable cache fails closed
    or falls back to a full scan; every graph input hash has been scanned clean.
11. **Separate preparation budget (user decision 2026-10-24).** Hooks and plain
    `update` keep the 180 s budget. `prepare_worktree.py` runs the first update
    with a 600 s budget through an explicit update option; no environment
    variable changes the hook budget.
12. **Quality runner excludes local Graphify state (user decision 2026-10-24).**
    `.graphify-local/` now exists in every prepared worktree and contains copied
    Python inputs, so `tools/quality_baseline.py` adds it to its root-level
    non-source directories, with a test that tracked sources remain included.

## Risks / Trade-offs

- [pip-compile drops platform-gated packages on the generating platform] →
  explicit marker line in `.in`, cross-platform compile check, marker test.
- [Dependabot does not detect the new pair] → post-merge check; add an explicit
  Dependabot entry only if detection fails.
- [Shared environment deleted or corrupted by another worktree] → marker check
  makes it unavailable; rerunning `setup` repairs it under the lock.
- [`prune` removes an environment an older branch still needs] → explicit
  command only; that worktree's `setup` recreates its environment.
- [T3 script change lands before develop contains the entry point] → update the
  T3 project only after merge.

## Migration Plan

Existing `.graphify-local/venv` directories become unused; they are git-ignored
and may be deleted manually. After merge, the T3 project script
`node-dev-deps` is replaced by `python scripts/prepare_worktree.py` with
`runOnWorktreeCreate: true`. Rollback: restore the previous T3 command and
revert the PR.

## Open Questions

- Why the existing T3 `runOnWorktreeCreate` script did not run for this
  worktree. Answered by the post-merge fresh-worktree check; it does not change
  the repository design.
