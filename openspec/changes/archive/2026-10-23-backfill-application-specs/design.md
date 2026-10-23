# Design

## Context

This is the first behavior-specification baseline of an existing application.
Application source is frozen at `b8c911c9dda83a7920171916ace32681c0c38ba0`;
OpenSpec setup checkpoint `6f942515a` adds tooling only. The project is version
1.13.22 with current schema v13 and supported released schemas from v9.
The backfill must preserve source, runtime configuration and athlete data.

## Goals / Non-Goals

**Goals:** Describe all current product and operational capability areas, expose
their success/failure/authorization/persistence scenarios, cite current code and
regression tests, and record coverage and uncertainty. Provide durable main specs
that subsequent changes can update through deltas.

**Non-goals:** Application fixes, schema changes, invented desired behavior,
new providers, production inspection, an independent security/codebase audit,
proof of every runtime/browser scenario, remote writes, PRs, releases or deployment.

## Decisions

1. **Capability boundaries.** Use the 30 cohesive capabilities in the proposal.
   Backend domains remain implementation owners; a capability may cross an API,
   service, persistence and UI boundary. UI specs own presentation/client state;
   domain specs own durable effects. Generic scheduler contracts stay separate
   from nutrition export semantics.
2. **Source authority.** Inspect current implementation and tests before writing
   requirements. AGENTS/README state intended boundaries but do not alone prove
   implementation. Record contradictions in the coverage ledger rather than
   turning known defects into desirable SHALL behavior.
3. **Evidence format.** Every requirement cites repository-relative source paths
   and symbols and existing test paths/names in backticks. These references remain
   valid when deltas move to the archive. A cited test means inspected coverage;
   the ledger separately records which tests were actually executed.
4. **Scenario format.** Delta requirements use `## ADDED Requirements`,
   `### Requirement:`, and concrete `#### Scenario:` WHEN/THEN blocks. New main
   specs retain Purpose and use `## Requirements`. Include failure/no-data,
   authorization, freshness/conflict and recovery cases wherever implemented.
5. **Bounded delegation.** Three isolated workers prepare disjoint domain deltas
   using user-selected Codex GPT-6.1-Sol/xhigh/default. The parent reviews exact
   frozen patches, verifies claims against current source and alone integrates
   them. The parent owns platform specs, shared metadata, coverage and closure.
6. **Coverage is explicit.** Cover backend owners, route surfaces, Coach tools,
   browser modules and build/runtime boundaries. An index entry or format-valid
   document is not a conformance test. Broad static coverage and focused execution
   are reported separately; full application/browser/live-provider validation is
   not inferred from this documentation change.
7. **Archive after review.** Strictly validate the complete delta, resolve review
   concerns, sync into the empty main inventory, verify all requirement/scenario
   counts and content, then archive the completed change. Keep the coverage
   ledger with main specs and update README's initial-empty wording.

## Risks / Trade-offs

- A large one-time baseline can overstate untested behavior. Mitigate with exact
  source/test evidence, bounded requirements and explicit uncertainty.
- Provider/model names, schedules and schema versions can drift. Record the
  inspected revision and update affected specs/tests with future changes.
- Pure format validation cannot prove requirement truth. Parent evidence review
  and scoped regression execution remain separate acceptance checks.
- Existing defects may contradict intended contracts. List supported discrepancies
  and unresolved intent without fixing them in this backfill.

## Migration Plan

Documentation migration only. No database, data directory, provider configuration
or frontend asset/cache version changes are needed. Removing the new documentation
reverts the baseline without changing application state.

## Open Questions

Unverified behavioral details and any discrepancies found during evidence review
are recorded in `openspec/COVERAGE.md`; they are not silently promoted to normative
requirements. There are no scope decisions required to begin the authorized backfill.
