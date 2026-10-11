# Repository skills and app dependencies

Project workflows are owned and versioned here. Built-in and plugin skills may
still be supplied by the host application; adding repository files does not
remove them from the session. Tool connections, authentication, and app settings
remain runtime dependencies, even when their project workflow lives in Git.

## Replacement assessment

The local package assessment below was made on 2026-10-11. Recheck the installed
version, skill-specific terms, supporting files, and tools before a later migration.
Plugin manifest licenses alone do not establish the terms of every bundled file.

| App-supplied family | Verified local evidence | Repository decision |
| --- | --- | --- |
| Codex system skill-creator, skill-installer, openai-docs, imagegen | Their local license files are Apache 2.0. Image generation still needs an app/model tool; docs lookup needs current official sources. | Instruction-only adaptations are possible with notices. Project skill maintenance is covered by `ai-coach-skill-evaluation`; importing project skills follows the local index. Do not vendor unrelated built-ins just to reproduce the app catalog. |
| Engineering Suite/Ponytail 2.0.0 | Local `LICENSE` is MIT, copyright 2026 Engineering Suite contributors. | Portable workflow text is a candidate if a project need is demonstrated. Existing scoped ownership/review guidance already covers much of the scope; no bundle or measurement scripts were copied. |
| Unraid MCP 2.10.2 | Manifest declares MIT and an MCP server launched through `uvx`, with external connection/authentication settings. | Project release/deployment workflow is already local. Copying the general Unraid skill cannot replace its MCP server, credentials, or connection. Keep connection secrets outside Git. |
| Codex Security 0.1.32 | Manifest declares Proprietary and a separate MCP configuration. | Keep the local `ai-coach-codex-security` wrapper and app/ChatGPT-authenticated scan capability. Do not copy proprietary prompts or claim a repository wrapper supplies the scanner. |
| SonarQube 2.6.0 | Local `LICENSE` is SONAR Source-Available License v1.0. | Keep project scan/review policy local; retain the CLI/MCP runtime. Do not treat the plugin as an MIT/Apache bundle. Copying its instructions would not implement deterministic secrets scanning. |
| Computer-use 26.930.61225 | Manifest declares Proprietary; browser/computer tools are supplied by the host. | Use the local PWA workflow and the host's supported browser controls. Skill text alone does not replace the browser runtime or its permissions. |
| Documents 26.909.12148 | Plugin manifest says MIT, but `skills/documents/LICENSE.txt` states OpenAI service terms and explicitly restricts extraction, retained copies outside the service, and redistribution. | Do not vendor this skill. A manifest label is insufficient when the skill has explicit terms. |
| PDF, presentations, spreadsheets 26.909.12148; visualization, sites, pets, artifact templates and plugin management | These are app/artifact workflows, some with supporting tools or scripts. Redistribution and portable execution were not established for the complete bundles. | They are not project dependencies. Do not copy or describe them as replaced; assess a specific need and its file-level terms separately. |

No project skill copies were found in the inspected direct personal directories
`~/.codex/skills` (apart from app-managed `.system`), `~/.agents/skills`, or
`~/.claude/skills`. This does not prove that every app account, synced skill store,
ancestor directory, or admin policy is empty.

## Discovery and duplicate handling

- [Codex](https://learn.chatgpt.com/docs/build-skills) discovers repository
  `.agents/skills`, the canonical root for every project skill in this checkout.
  The former `.codex/skills` workflows have been moved here. Codex does not merge
  same-name skills; both may appear if another scope supplies a duplicate.
  A local skill can be disabled through an app-managed `[[skills.config]]` entry
  pointing at its `SKILL.md`, with `enabled = false`, followed by restart. A
  repository copy does not itself disable a built-in or plugin skill.
- [Claude Code](https://code.claude.com/docs/en/skills) natively discovers project
  skills under `.claude/skills`, not this canonical root. Follow the linked
  workflows from `AGENTS.md` explicitly. Personal skills take precedence over
  project skills of the same name; plugin skills are namespaced and coexist.
- Keep a single canonical project workflow. Avoid committed Windows-dependent
  symlinks, duplicated skill bodies, and links to personal app cache paths. Do
  not claim Claude slash-command discovery from loading `AGENTS.md` alone.
- Disabling/uninstalling plugins, changing user configuration, or disconnecting
  accounts is a separate app operation with effects beyond this repository.
  No such settings or managed packages were changed by this assessment.

Evaluate a proposed replacement on synthetic tasks before disabling its original.
Check that required tools, authentication, supporting files, and behavior remain
available; matching names or successful frontmatter validation is insufficient.
