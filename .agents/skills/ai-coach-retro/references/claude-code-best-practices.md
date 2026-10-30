# Claude Code best-practice checklist

Reviewed: 2026-10-30. Sources:
[Best practices](https://code.claude.com/docs/en/best-practices),
[Steering Claude Code](https://claude.com/resources/articles/steering-claude-code-skills-hooks-rules-subagents-and-more).

Check the session against these points. Each finding should mostly remove or
move something, not add a rule.

1. `AGENTS.md` holds only what Claude cannot find in the repo, and stays under
   200 lines. Architecture, file layout, and generic advice are removed.
2. A rule that Claude missed despite clear wording, and that has no exceptions,
   becomes a hook, deny rule, or test. Preferences stay as text or are deleted.
3. No emphasis (IMPORTANT, ALL CAPS, "always", "never") to make a line stick.
   If a line gets lost, the file is too long.
4. Procedures live in skills, not `AGENTS.md`. Workflows with side effects are
   user-invoked (`disable-model-invocation: true`).
5. Work had a concrete check: tests, a hook, CI, or one fresh-context review.
6. Subagents ran only for parallel work, noisy output, an independent review,
   or restricted tools, with the cheapest fitting tier. Delegating for a
   "better answer" is waste.
7. Effort matched the task: `medium` by default, `high` only where edge cases
   are easy to miss.
8. Unrelated tasks were not mixed in one session; long sessions re-send their
   whole history every turn.
9. No "loop until done" or "be thorough" prompting; a check to pass replaces it.
10. Reviews of process documents reported real P0/P1 problems, not
    hypothetical edge cases turned into new rules.

If the review date above is more than 90 days old, propose a refresh as a
separate task. The refresh rereads the sources and Anthropic's engineering blog,
updates this list (the docs' "What you can stop doing" table matters most), and
compares the repository setup against it. Prefer deletions.
