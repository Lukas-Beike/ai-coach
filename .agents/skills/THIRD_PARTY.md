# Skill provenance and licenses

The following project-specific adaptations retain their upstream terms.
They are rewritten workflows, not installations of the complete upstream skill
bundles. Each adapted skill identifies its modifications.

Anthropic skill-creator attribution: Copyright 2026 Anthropic, PBC.

| Local workflow | Upstream source | Pinned revision | License |
| --- | --- | --- | --- |
| `ai-coach-debugging` | [Superpowers systematic-debugging](https://github.com/obra/superpowers/tree/bb92a77741419a4ab5f06e711a283343f1ada0c3/skills/systematic-debugging), including root-cause-tracing and condition-based-waiting | `bb92a77741419a4ab5f06e711a283343f1ada0c3` | [MIT, copyright 2025 Jesse Vincent](licenses/Superpowers-MIT.txt) |
| `ai-coach-ui-design` | [Anthropic frontend-design](https://github.com/anthropics/skills/tree/dbd4588f9e1033efb41dad4bef2f7947c8993d44/skills/frontend-design) | `dbd4588f9e1033efb41dad4bef2f7947c8993d44` | [Apache 2.0](licenses/Apache-2.0.txt) |
| `ai-coach-skill-evaluation` | [Anthropic skill-creator](https://github.com/anthropics/skills/tree/dbd4588f9e1033efb41dad4bef2f7947c8993d44/skills/skill-creator) | `dbd4588f9e1033efb41dad4bef2f7947c8993d44` | [Apache 2.0](licenses/Apache-2.0.txt) |

Project changes replace broad upstream defaults with this repository's privacy,
SQLCipher, ownership, validation, and authorization requirements. UI guidance
extends the current design rather than requiring a new identity. Evaluation does
not automatically spawn agents, install packages, or execute remote workflows.

Review later upstream changes deliberately against code and project contracts;
do not synchronize bundles or install global copies. App-supplied materials have
separate licensing and runtime constraints; see
[app skill ownership](references/app-skill-ownership.md).
