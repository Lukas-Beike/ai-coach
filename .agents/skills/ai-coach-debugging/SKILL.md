---
name: ai-coach-debugging
description: Diagnose an Intervals Coach bug, flaky test, or unexplained failure before changing code. Use for root-cause investigation; use ai-coach-pr-ci for GitHub check status and ai-coach-codex-security for requested security scans.
license: MIT adaptation; see ../THIRD_PARTY.md.
---

# Debugging Intervals Coach

Adapted from Superpowers systematic-debugging, root-cause-tracing, and
condition-based-waiting, with the feedback-loop and ranked-hypothesis steps of
Matt Pocock's diagnosing-bugs. Modified for this project's ownership, privacy,
SQLCipher, fixture, and authorization contracts; see [provenance](../THIRD_PARTY.md).

## Establish the failure

- State the expected behavior, observed behavior, smallest triggering input or
  state, and affected revision/environment. Separate an application failure from
  missing tools, a cancelled CI wrapper, or an outdated test assumption.
- Capture the exact failing assertion or safe error metadata. Read source files directly;
  never collect real credentials, athlete records, request payloads,
  database contents, browser storage state, or unfiltered provider logs.
- Reproduce with temporary storage, mocked providers, or the disposable browser
  fixture. Use [navigation](../ai-coach-navigator/SKILL.md) to locate the owner and
  [browser validation](../ai-coach-pwa-e2e/SKILL.md) for UI failures. If reproduction
  is unavailable, record that limit and trace the reachable path statically.
- Before theorizing, name one command you have already run that goes red on
  the reported symptom (not merely "does not crash"), gives the same verdict on
  every run, and takes seconds. Then cut inputs and steps one at a time until
  every remaining element is needed for the failure.

## Trace one cause at a time

1. Follow the failed value or state backward through its caller, owner, persistence,
   provider adapter, and UI consumer as relevant. Locate where it first diverges
   from the contract. Check transaction, timing, timezone, and source-label
   boundaries rather than guessing from the visible symptom.
2. Compare a working case or adjacent implementation. Inspect recent changes and
   the exact child-job/test output. Do not infer an application regression solely
   from a wrapper's exit status, stale selector, or fixture date window.
3. Rank 3-5 falsifiable hypotheses, each with the observation that would
   disprove it, before testing the first; one idea anchors too early. Run the
   smallest experiment; change one variable. For races, wait on observable
   readiness or job state with a timeout instead of adding arbitrary sleeps.
4. If evidence rejects the hypothesis, revise it before another code change.
   Repeated unsuccessful fixes call for rechecking ownership and assumptions,
   not layering more patches or relaxing a guard.

Use synthetic inputs and redacted metadata such as status, field presence,
counts, and timings for instrumentation. Keep it temporary or within the existing
redaction contract; never log raw payloads to diagnose a boundary. Tag temporary
logs with a unique prefix such as `[DEBUG-a4f2]` and grep it away before finishing.

## Fix and prove

- Correct the owning responsibility with the smallest coherent change. Follow
  `AGENTS.md` when extracting affected legacy logic from `server.py`; avoid new
  orchestration there, dependency cycles, and unrelated refactoring.
- Preserve authorization, provider provenance, durable athlete state, and encrypted
  startup. A workaround that disables any of these does not resolve the failure.
- For a functional regression, choose a focused check that exposes the original
  failure and passes with the fix. Keep tests about observable behavior; do not
  demand a new test for a reversible instruction or cosmetic edit. If no seam
  reproduces the real call pattern, report that as an architecture finding
  instead of adding a shallow test that cannot catch the bug.
- Inspect the final diff and run [appropriate validation](../ai-coach-validation/SKILL.md).
  Report the cause, changed behavior, executed proof, and remaining limits. An
  untested hypothesis remains a hypothesis; local proof is not a merge or release.
