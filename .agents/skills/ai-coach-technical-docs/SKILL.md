---
name: ai-coach-technical-docs
description: Write or substantially revise Intervals Coach architecture decisions, technical proposals, and operational documentation, checking claims against code and reader needs. Do not use for a small wording fix, skill maintenance, or ordinary PR descriptions.
---

# Technical documentation that a reader can use

Project-authored guidance informed by the reader-testing concept assessed in
Anthropic doc-coauthoring; see [source assessment](../THIRD_PARTY.md).
No upstream text, scripts, or templates are vendored here.

1. Infer audience, task, desired decision, and document owner from the request and
   current code. Ask only for missing information that changes the result; do not
   require an interview or a separate workflow opt-in for an authorized draft.
2. Scan relevant sources before reading. Trace the actual behavior and record
   the reviewed revision. Separate implemented behavior, proposals, alternatives,
   and unverified assumptions. For a decision, explain the concrete problem,
   chosen option, meaningful tradeoffs, and observable acceptance evidence.
3. Keep setup and operational commands in `README.md`; link them instead of
   creating a second maintained runbook. Check paths, configuration names,
   defaults, and commands against code. Run safe synthetic checks when useful;
   never execute a destructive or remote operation merely to validate its docs.
4. Test the draft as a new reader: can they identify prerequisites, follow the
   stated steps, predict the result, and recover from the documented failure?
   Check links and challenge unstated assumptions. Use an independent reader
   only when authorized orchestration actually dispatches one; a parent
   walkthrough must be labeled as such, not independent validation.
5. Remove unsupported claims, duplicated policy, and unnecessary helper prose.
   Inspect the final diff and run documentation contract checks. Report what
   was verified, what remains proposed, and any unexecuted operational steps.

Use [skill evaluation](../ai-coach-skill-evaluation/SKILL.md) for skill changes
and the PR workflow's own description guidance for PR bodies. Documentation
work does not authorize publication, external messages, or deployments.
