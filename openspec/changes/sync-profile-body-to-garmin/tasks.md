# Tasks

## 1. Ownership and lock order

- [x] 1.1 Inventory all profile mutation entry points and transaction/maintenance boundaries, including HTTP profile/context, structured Coach rounds and direct tool execution, individual and turn undo, proposal execution, restore and privacy paths; record the verified lock order and prove one shared coordinator is injected.
- [x] 1.2 Introduce profile-mutation coordination at the outer transaction owners and verify atomic rollback, optimistic conflicts, receipts and undo using existing tests plus real temporary persistence; no Garmin write occurs from these paths.
- [x] 1.3 Add deterministic concurrent tests for profile/context, structured Coach, individual undo and turn undo against an active export; prove stale waiting exports are skipped, later mutations wait, exceptions release locks, and unrelated database writes continue; execute the tests with a running simulated export.

## 2. Garmin export

- [x] 2.1 Implement the explicitly opted-in profile-save export using the shared Garmin and profile locks, short committed reads, no database lock/transaction over network I/O, both valid saved values and athlete-local time; use mocked SDK plus temporary persistence to verify auth, token write-back, fixture/unconfigured mode and concurrent supersession.
- [x] 2.2 Verify success, invalid values, unavailable authentication, provider rejection, ambiguous timeout, and explicit SDK 401 refresh behavior without live accounts or raw error disclosure; prove no application retry on ambiguous result, including lost and malformed confirmations.

## 3. Presentation and documentation

- [x] 3.1 Connect profile saves to the opt-in and show distinct export outcomes including superseded and uncertain while preserving locally saved values; cover explicit retry after known failures, preservation across unrelated or rejected saves, lost responses and serialized actions with focused tests and document it in README.
- [x] 3.2 Complete the Body overview profile source, Garmin fallback and no synthetic history; verify with focused tests and isolated browser fixtures, and synchronize service-worker and asset versions.

## 4. Integration

- [x] 4.1 Independently review lock ordering, privacy, SDK effects and the complete final candidate; resolve findings and verify the full diff and strict OpenSpec validation.
- [x] 4.2 Run required backend, JavaScript, quality, Docker and isolated PWA/browser checks on the final tree, recording any environmental failures accurately.
