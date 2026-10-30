# Design

## Context

At 52870061, `AthletePutRoutes` patches the profile locally. `ProfileService.save_in_transaction` is also reached by athlete-context save; `CoachProfileUpdateService` can run inside the outer transaction in `StructuredCoachRound`; `HistoryUndoService.apply_many` can restore profiles inside the turn-undo transaction. Garmin token write-back opens its own unit of work. The stopped candidate's transaction across network I/O can block token persistence and other database users. The earlier candidate can send a profile snapshot superseded while waiting for the Garmin lock. These are design findings, not implemented behavior.

## Goals / Non-Goals

**Goals:** Preserve local saves and existing atomicity, prevent a queued upload from sending a superseded body pair, avoid holding the database lock or transaction during remote I/O, report the actual outcome, and display profile body fat without inventing a measurement history.

**Non-Goals:** Remote writes from Coach, undo, context replacement, imports, or restore; automatic retry after an ambiguous upload; new schema or live-account test. Undo remains local and does not remove a prior Garmin entry.

## Decisions

### Mutation coordination and ordering

Introduce one process-wide, reentrant profile-mutation coordinator injected through the composition root. Every outermost entry point that can commit a profile change MUST acquire it before acquiring the shared database lock or starting a writer transaction, and retain it until that transaction commits or rolls back. Enumerate and verify callers rather than assuming these are exhaustive: profile patch/save and athlete-context replacement, Coach structured-tool round and direct execution of profile updates, individual history undo and proposal execution, and turn undo. A wrapper that acquires the coordinator inside `save_in_transaction` or `restore_in_transaction` is insufficient: those can already be inside another owner's transaction. Nested paths use the same reentrant coordinator. Audit backup restore, privacy/maintenance, and other profile replacement paths for interaction with the maintenance gate; preserve their existing atomicity and lock ordering.

The ordering rule is maintenance gate (where applicable), Garmin synchronization lock for an export, profile-mutation coordinator, database lock, then database writer/reader. No path holding the coordinator or database lock may wait for the Garmin lock. Garmin refreshes and token operations must not acquire the profile coordinator while holding database state in the opposite order. Verify this against actual callers before finalizing wiring; do not introduce a second independently instantiated coordinator.

An explicitly opted-in profile form save commits its patch locally and releases its mutation coordinator and database locks. If body fields changed, the export acquires the Garmin lock first, then the coordinator. It briefly reads the committed profile, closes the reader, and compares both body fields and the latest committed profile change identity to the captured result. If either differs, return `superseded` without writing, even when a value changed away and back. Bound lock acquisition and upload start to ten seconds from the profile request; check again after authentication so a timed-out browser request cannot start a delayed upload. The identity uses existing profile change history; unrelated profile changes may conservatively supersede an upload. Otherwise keep the coordinator through the remote call and token write-back, while holding neither a database lock nor an open reader/writer transaction. This serializes later local profile edits after the upload; earlier edits supersede it. Network time can delay profile mutations, but must not stall unrelated database writes. Test actual persistence and nested entry points, not only mocked locks.

### External effects and outcomes

Only the profile form explicitly opts in; unrelated API calls, Coach, undo and restore remain local. A changed valid pair (weight 20?300 kg, body fat 1?70%) uses the saved athlete-local timestamp and the pinned `garminconnect` body-composition FIT upload. Missing, non-finite or out-of-range fields skip upload with `invalid`; unconfigured Garmin and failed authentication return `unavailable`; an unknown upload result returns `uncertain`, never an automatic application-level retry; a superseded pair returns `superseded`. A success requires a successful provider result. Never log raw provider errors or payloads. Persist refreshed Garmin tokens through the existing guarded token store after the call; a failed remote call does not roll back the local profile. The SDK can replay an upload after an explicit 401 and session refresh; guard every upload POST, including that replay, against the same deadline and bound its request timeout. Verify pinned behavior with isolated synthetic transport tests; do not retry an ambiguous timeout.

The profile UI sends the opt-in on a save containing a body change and explains success, invalid, unavailable, rejected, superseded and uncertain separately. After a known invalid, unavailable or rejected outcome it offers an explicit retry of the currently saved pair. A lost or malformed response is uncertain: warn the athlete to check Garmin and do not offer a blind retry. Serialize saves and retries in the current view; preserve a known retry after a definite request rejection or unrelated save. The Body overview prefers the profile fat value with a `Profil` label and no date or historic points; otherwise it retains Garmin fallback. Bump PWA cache and asset versions together.

## Risks / Trade-offs

- A long provider operation delays competing profile mutations ? use bounded provider timeout, test waiting and release on every exception, and allow unrelated writes.
- Missing an outer transaction owner risks lock inversion ? inventory every path and test real temporary persistence for Coach and both undo variants; require independent review before adoption.
- Network interruption can leave the Garmin outcome ambiguous ? surface `uncertain` and do not silently retry.
- The unofficial Garmin API may change ? pin SDK behavior in isolated tests; no live-account compatibility is claimed.

## Migration Plan

No schema change. Existing encrypted data and stored tokens remain intact. Rollback stops future uploads but does not remove existing Garmin entries. Deploy only through the normal release process.
