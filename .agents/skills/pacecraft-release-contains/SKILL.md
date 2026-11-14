---
name: pacecraft-release-contains
description: Base skill. Tell whether a release tag carries a develop commit, although the squash promote to main breaks plain ancestry. Use for "is fix X in release Y" questions in release and post-release checks; read-only, never for changing tags or branches.
---

# Does a release contain a commit?

```powershell
git fetch origin develop --tags
python scripts/release_contains.py <commit> <tag> [--branch origin/develop]
```

- Never answer this with `git merge-base --is-ancestor <commit> <tag>`: a
  release reaches `main` by a squash promote commit, so that always says no.
- The promotion keeps develop's tree, so the script finds the newest develop
  commit with the tag's tree that is not newer than the tag (a later revert
  can restore that tree) and checks ancestry against it.
- Exit 0: contained. Exit 1: not contained. Exit 2: bad input, a failed git
  call, or no branch commit with the tag's tree (fetch first).
