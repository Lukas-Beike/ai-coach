## 1. Adapter and streaming client

- [ ] 1.1 Claude adapter for requests, tool rounds, images, files, JSON answers, web search, caching, effort and fallbacks; verify with `tests/test_claude_provider.py` (`ClaudeRequestPayloadTests`, `ClaudeModelTurnTests`).
- [ ] 1.2 Streaming client with byte bound, cancellation, pause resumption, refusal and safe error classification; verify with `tests/test_claude_provider.py` (`ClaudeStreamClientTests`).

## 2. Model resolution and usage

- [ ] 2.1 Newest model per family with a step back to the last working model; verify with `tests/test_claude_provider.py` (`ClaudeModelResolverTests`).
- [ ] 2.2 Separate Claude usage counters; verify with `tests/test_provider_usage.py` and `tests/test_provider_state.py`.

## 3. Verification

- [ ] 3.1 Run `python scripts/check_changed.py --base origin/develop`, strict OpenSpec validation for this change, and record that no live provider was called.
