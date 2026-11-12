---
name: pacecraft-spec-validate
description: Base skill. Validate the OpenSpec main specs, one change, or everything in strict non-interactive mode. Use after editing openspec/; not for creating or archiving changes.
---

# Validate OpenSpec

```powershell
python scripts/spec_validate.py [--change <name>] [--all]
```

- Always validates the main specs (`validate --specs --strict --no-interactive`);
  `--change` adds that change, `--all` adds `validate --all`. Uses `npm run
  openspec`, so run `npm ci` first if `node_modules` is missing.
- One `ok|FAILED <what> (<seconds>s)` line per command, with the last 20 lines
  of a failure.
- Exit 0: valid. Exit 1: a validation failed; fix the spec, do not loosen the
  rule. Exit 2: bad change name or `npm` missing.
