# Design

## Context

The v16 planning migration rewrote selected JSON structures and preserved audit hash compatibility. The current v18 shape adds feedback rating time. Planning still imports provider field constants for load, intensity and frozen FTP; provider reads and writes already have a planning-field mapping boundary.

## Goals / Non-Goals

Preserve stored data, remote sync baselines and undo behavior while replacing local planning keys. Preserve wire behavior and explicit synchronization. Do not reset a database or change provider authorization.

## Decisions

Use `planned_load`, `planned_intensity` and `ftp` for the local values; translate Intervals.icu names at its adapter. Rewrite only known planning record structures in a transactional v18-to-v19 step, including nested snapshots, previews and conflicts. The renamed derived metrics are absent from audit projections, so pending undo data stays unchanged. Retain legacy hash recognition for existing history and sync baselines. A generic recursive rewrite is rejected because unrelated provider payloads may contain the same keys with different meaning.

Retired activity-detail KV records remain byte-for-byte unchanged. Their frozen target basis is normalized when the existing backfill writes canonical analysis; the retirement proof compares that normalized view so a legacy record is removed only when its canonical equivalent is present.

Freeze the v18 schema shape before raising the current version. Keep v16 and v17 steps; retire v9 through v15 recognition and migration code. Retain an old fixture where needed to verify rejection. The current migration gate rejects versions before opening its savepoint, preserving old and unknown databases.

## Risks / Trade-offs

- Missing a stored JSON location or an audit hash can break existing records or sync → trace all writers and readers, and test populated upgrades, editing, sync hashes and undo.
- Old backups become unrestorable in the new build → reject them without modification and document using a compatible older release first.
- A failed upgrade could leave partial data → use the existing transaction and verify injected failures and encrypted startup.

## Migration Plan

Upgrade v16 through v17 and v18 to v19 in one transaction; upgrade v17 and v18 through their remaining steps. Verify same-build restart and staged backup restore. A failed migration rolls back; rolling back application code after a successful upgrade requires an earlier compatible backup, since older builds reject newer schema versions.
