## 1. Implementation

- [x] 1.1 Split `prepare_remote_write` from `create_remote_write` and dispatch named remote writes without a card; keep the card for explicit Garmin removal entries
- [x] 1.2 Add the remote removal lines to the turn receipt
- [x] 1.3 Apply the whole-message refusal block to the Garmin wording check
- [x] 1.4 Update the `push_strength_to_garmin` tool description, docs and AGENTS.md

## 2. Validation

- [x] 2.1 Regression tests that fail before the change: card-free queueing per sync kind, Garmin removal card, removal receipt lines, Garmin refusal rows
- [x] 2.2 Review the scoped evidence lines in the delta specs and run `python scripts/spec_validate.py --change card-free-named-sync`
- [x] 2.3 Run `python tests/run_tests.py --changed`, ruff, mypy and `node --test tests/*.cjs`
