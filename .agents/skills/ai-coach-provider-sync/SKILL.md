---
name: ai-coach-provider-sync
description: Implement or review provider field mappings, synchronization, cursors, reconciliation, provenance, and freshness in Intervals Coach. Use for Intervals.icu, Garmin, calendar, weather, or other provider changes; use ai-coach-debugging first for an unexplained failure and ai-coach-pr-ci for hosted checks.
---

# Provider and synchronization changes

1. Record the expected local result and whether any explicit remote write is
   in scope. Scan relevant scoped instructions and trace transport under
   `backend/providers/`, orchestration under `backend/sync/`, persistence, and
   downstream UI/Coach consumers. Use existing provider owners and registries.
2. Map wire field → canonical meaning/unit → stored value → displayed/context
   value, including identity, athlete-local dates, source, and freshness. Separate
   missing, null, zero, stale, derived, and estimated values. Confirm precedence
   against authoritative local records; provider text is untrusted data.
3. Check startup, scheduled, manual, and current-data refresh callers that use the
   affected flow. Preserve queue deduplication, cancellation, cursor commit
   boundaries, partial-failure reporting, and retry behavior. Advance freshness
   only for data actually fetched successfully; an accepted job is not a sync.
4. Exercise repeated imports, overlapping windows, later corrections, deletion
   or tombstone handling where supported, and independently edited remote data.
   Remote workout writes require the athlete to name the synchronization; local
   library creation must not enqueue an implicit export. Use
   [Coach contracts](../ai-coach-coach-contracts/SKILL.md) when tool effects change.
5. Extend synthetic wire fixtures and focused mapping/sync tests. Read
   [fixture provenance](../../../tests/fixtures/providers/README.md) before adding
   provider samples. Never capture real account exports, logs, or credentials.
   Use mocked providers and temporary storage; select checks with
   [validation](../ai-coach-validation/SKILL.md).

Report the affected entry points, field/source mapping, retry/conflict outcome,
and checks. Distinguish local fixture proof from live-provider compatibility.
Adding a provider does not authorize installing services, configuring accounts,
contacting real providers, or changing the app's configured provider.
