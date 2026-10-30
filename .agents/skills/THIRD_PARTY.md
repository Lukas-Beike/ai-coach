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
| `orchestrated-plan-implementation` | [Oliviero Pinotti orchestrator](https://github.com/olivieropinotti/orchestrator-skill/blob/a897bbfc06be4f73cfdc1ae8198bdb9b28623da0/skills/orchestrator/SKILL.md) | `a897bbfc06be4f73cfdc1ae8198bdb9b28623da0` | [MIT, copyright 2026 Oliviero Pinotti](#orchestration-mit-notices) |
| `orchestrated-plan-implementation` | [Alireza Rezvani Orchestration Protocol](https://github.com/alirezarezvani/claude-skills/blob/27cfcd0fb0a41f60adffcbd5271fdf8839f86ed2/orchestration/ORCHESTRATION.md) | `27cfcd0fb0a41f60adffcbd5271fdf8839f86ed2` | [MIT, copyright 2025 Alireza Rezvani](#orchestration-mit-notices) |

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
Orchestration keeps the upstream ideas of complete briefs, objective-first
handoffs, and asynchronous dispatch. It replaces unconditional delegation with a
cost-benefit decision, uses a fixed repository tier mapping, isolated worker
worktrees, and parent-only integration, and excludes nested delegation,
automatic setup, and blanket human approval. eddiearc/dev-orchestrator-skill was
also assessed at revision `300e9ade5161e27916159f178112c4cfc9300c33`; no license
was found there, so its text/templates are not copied or redistributed.

Review later upstream changes deliberately against code and project contracts;
do not synchronize bundles or install global copies. App-supplied materials have
separate licensing and runtime constraints; see
[app skill ownership](references/app-skill-ownership.md).

## OpenSpec generated skills

The six `openspec-*` skills are unmodified output of
[`@fission-ai/openspec` 1.14.3](https://www.npmjs.com/package/@fission-ai/openspec/v/1.14.3),
generated with `init --tools agents --profile core --language en --no-animation`.
The exact version and package integrity are pinned in `package-lock.json`.
Upstream: [Fission-AI/OpenSpec](https://github.com/Fission-AI/OpenSpec),
MIT, copyright (c) 2024 OpenSpec Contributors. The complete
[MIT notice](licenses/OpenSpec-MIT.txt) is retained with these generated files.
Repository integration adds index routing, local CLI invocation, project context,
and the incremental backfill runbook; it does not modify the generated bodies.

## Technical documentation source assessment

Reviewed Anthropic's [doc-coauthoring](https://github.com/anthropics/skills/tree/dbd4588f9e1033efb41dad4bef2f7947c8993d44/skills/doc-coauthoring)
at `dbd4588f9e1033efb41dad4bef2f7947c8993d44`. The directory contains only
`SKILL.md`, with no license field or bundled license; the repository's general
README statement that many skills use Apache 2.0 does not establish this file's
terms. No upstream text, scripts, or templates are copied or redistributed.
The project-authored `ai-coach-technical-docs` applies reader-oriented verification
to this repository's existing code-first evidence, README-owned commands, and
authorization rules, without a mandatory interview or automatic independent
workers/publication.

## Orchestration MIT notices

Retained upstream notices for the two rewritten orchestration workflows.

```text
MIT License

Copyright (c) 2026 Oliviero Pinotti

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

```text
MIT License

Copyright (c) 2025 Alireza Rezvani

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```
