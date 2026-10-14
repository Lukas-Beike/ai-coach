---
name: ai-coach-ponytail
description: Apply Ponytail's smallest complete change approach to Intervals Coach coding, bug fixes, refactoring, code reviews, and dependency choices. Use alongside the relevant task workflow; skip non-coding requests.
license: MIT adaptation; see ../THIRD_PARTY.md.
---

# Ponytail for Intervals Coach

Adapted from DietrichGebert's Ponytail; see [pinned source and license](../THIRD_PARTY.md).
Modified for agent-neutral Markdown loading, repository ownership, and required
validation. No external plugin, host-specific command, or runtime hook is needed.

## Use and modes

Use for coding tasks by default in `full` mode. Scan and read this file directly
if the agent cannot discover repository skills. Combine it with the relevant
workflow in [the skill index](../README.md); it does not replace that workflow.

Honor plain-language requests such as `ponytail lite`, `ponytail full`, and
`ponytail ultra`. Keep the chosen mode for the session. `stop ponytail` or
`normal mode` disables this workflow until the user enables it again; repository
instructions continue to apply. Do not write mode flags or change global settings.

- **lite:** Implement the requested solution; mention a materially simpler option.
- **full:** Choose the smallest change that fully satisfies the request.
- **ultra:** Also question speculative requirements; preserve explicit user choices.

## Choose the smallest complete change

Understand the affected flow, callers, tests, fixtures, and contracts before
editing. Fix the root cause in its cohesive owner and finish affected consumers.
Choose the first option that satisfies the actual request:

1. Omit unrequested features, flexibility, and scaffolding.
2. Reuse existing project code, components, and conventions.
3. Prefer standard-library or native platform features when no project owner exists.
4. Use an existing dependency before adding one; a few clear lines need no new package.
5. Otherwise write the minimum clear implementation in the correct layer.

Avoid speculative wrappers and abstractions. A compact diff must remain readable;
do not compress code or relocate orchestration to bypass ownership rules. Remove
code only when the requested change makes it unnecessary.

Preserve security, privacy, data integrity, accessibility, error handling, and
explicit approvals. Simplification never waives migrations, protected workflows,
or required checks. Follow [validation](../ai-coach-validation/SKILL.md), inspect
the final diff, and report evidence plus material risks or unrun checks. Do not
expand task scope or authorization, or claim measured savings without measurements.
