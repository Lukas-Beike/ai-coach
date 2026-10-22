# Skill provenance and licenses

The following project-specific adaptations retain their upstream terms.
They are rewritten workflows, not installations of the complete upstream skill
bundles. Each adapted skill identifies its modifications.

Anthropic skill-creator attribution: Copyright 2026 Anthropic, PBC.

| Local workflow | Upstream source | Pinned revision | License |
| --- | --- | --- | --- |
| `ai-coach-ponytail` | [Ponytail](https://github.com/DietrichGebert/ponytail/blob/2961b52fc1fe6a5a87c7a959a79512e5c2f3ffe5/skills/ponytail/SKILL.md) | `2961b52fc1fe6a5a87c7a959a79512e5c2f3ffe5` | [MIT, copyright 2026 DietrichGebert](licenses/Ponytail-MIT.txt) |
| `ai-coach-debugging` | [Superpowers systematic-debugging](https://github.com/obra/superpowers/tree/bb92a77741419a4ab5f06e711a283343f1ada0c3/skills/systematic-debugging), including root-cause-tracing and condition-based-waiting | `bb92a77741419a4ab5f06e711a283343f1ada0c3` | [MIT, copyright 2025 Jesse Vincent](licenses/Superpowers-MIT.txt) |
| `ai-coach-ui-design` | [Anthropic frontend-design](https://github.com/anthropics/skills/tree/dbd4588f9e1033efb41dad4bef2f7947c8993d44/skills/frontend-design) | `dbd4588f9e1033efb41dad4bef2f7947c8993d44` | [Apache 2.0](licenses/Apache-2.0.txt) |
| `ai-coach-skill-evaluation` | [Anthropic skill-creator](https://github.com/anthropics/skills/tree/dbd4588f9e1033efb41dad4bef2f7947c8993d44/skills/skill-creator) | `dbd4588f9e1033efb41dad4bef2f7947c8993d44` | [Apache 2.0](licenses/Apache-2.0.txt) |
| `code-review` | [Anthropic Claude Code code-review command](https://github.com/anthropics/claude-plugins-official/blob/af59ee3a1051a29dda4a2e7a2af221aa457ae08b/plugins/code-review/commands/code-review.md), author Boris Cherny | Local marketplace snapshot `.gcs-sha`: `af59ee3a1051a29dda4a2e7a2af221aa457ae08b`; original command SHA-256: `7d5a0bc9a41babad32a387152f9680316997bc4ad376928827d670b1760cc890` | [Apache 2.0](licenses/Apache-2.0.txt) |

Project changes replace broad upstream defaults with this repository's privacy,
SQLCipher, ownership, validation, and authorization requirements. UI guidance
extends the current design rather than requiring a new identity. Evaluation does
not automatically spawn agents, install packages, or execute remote workflows.
Ponytail is adapted for direct Markdown loading by any agent, with a distinct
local skill name, plain-language modes, and project checks taking precedence.
Code review preserves the original command as a provenance reference and adapts
its five perspectives and confidence scoring for explicit branch ranges,
report-only execution, sequential review, and `REVIEW.md` evidence/severity rules.
It removes automatic model-specific delegation, trivial/bot skips, and PR writes.

Review later upstream changes deliberately against code and project contracts;
do not synchronize bundles or install global copies. App-supplied materials have
separate licensing and runtime constraints; see
[app skill ownership](references/app-skill-ownership.md).
