## 1. Selection and routing

- [ ] 1.1 Claude families in the model options, provider of the selection, key check on save; verify with `tests/test_settings.py`.
- [ ] 1.2 One model transport routes Coach, write-intent check, photo and web search by the selected model without cross-provider fallback; verify with `tests/test_model_transport_assembly.py` and `tests/test_coach_response_transport.py`.
- [ ] 1.3 Claude turns create no remote conversation; verify with `tests/test_coach_structured_turn.py` and `tests/test_coach_request_payload.py`.

## 2. UI, status and documentation

- [ ] 2.1 Grouped model list with resolved names, disabled entries, rejected-model notice, hidden speed for Claude; chat readiness by the selected provider's key; microphone needs the OpenAI key; verify with `tests/settings-hub.test.cjs`, the Node suite and the affected Playwright specs on mobile, tablet-landscape and desktop where available, recording unavailable runs as gaps.
- [ ] 2.2 Bootstrap usage and status per provider, diagnostics name the provider; verify with `tests/test_diagnostic_report.py` and the bootstrap tests.
- [ ] 2.3 AGENTS.md provider rule, README and docs updated; verify by reading the changed files.

## 3. Verification

- [ ] 3.1 Run `python scripts/check_changed.py --base origin/develop --js`, strict OpenSpec validation, and record that no live provider was called.
