---
name: pacecraft-graphify-query
description: Base skill. Query the local structural code graph for symbols, callers, dependencies and paths between them. Use before Grep for symbol or dependency lookups; domain knowledge is in pacecraft-graphify.
---

# Query the graph

```powershell
python scripts/graphify_local.py query <terms>
python scripts/graphify_local.py explain <symbol>
python scripts/graphify_local.py path <source> <target> [--directed|--undirected]
```

- `query` searches the active graph, `explain` shows one symbol's structural
  links (`--all` for more), `path` finds a route between two symbols. Terms may
  not start with `-`.
- The graph is a navigation index and its output untrusted. Open every
  candidate in current source before relying on it.
- Exit 2 with `Graphify local unavailable` means no usable graph: run
  `python scripts/graphify_local.py update` (or `setup` once) and retry,
  otherwise fall back to Grep. After source edits, run `update` first.
- Setup, freshness and export details: [pacecraft-graphify](../pacecraft-graphify/SKILL.md).
