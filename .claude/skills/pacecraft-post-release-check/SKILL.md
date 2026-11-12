---
name: pacecraft-post-release-check
description: Check production after every deployment, or on request after a restart - version, schema, record counts, guards, logs, server health, backup age and a UI walk - by sequencing the prod base skills; read-only apart from a few immediately undone local actions. Do not use to deploy, repair or change production.
disable-model-invocation: true
---

Read and follow the canonical workflow in `.agents/skills/pacecraft-post-release-check/SKILL.md` from
the repository root. This stub only registers it as a user-invoked Claude Code
command; do not add workflow content here.
