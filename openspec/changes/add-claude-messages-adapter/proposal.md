## Why

Issue #2355 adds the Claude API as a selectable model provider. Part 1 stored the Anthropic credentials. This part builds the provider side behind the neutral model seam: the adapter that turns a `ModelRequest` into an Anthropic Messages request and a reply into a `ModelTurn`, a bounded streaming client, and the per-family model resolution ("always the latest, with a step back to the last working model"). Part 3 connects them to the Coach, the photo analysis, the web search and the settings UI.

## What Changes

- New Claude adapter beside the OpenAI Responses adapter: tool use with `tool_choice: auto` and one call per response, adaptive thinking left at the model default with `output_config.effort` from the selected thinking level, prompt caching of the tool list, system prompt and turn, images and attachment files as image and document blocks, JSON answers through `output_config.format` (or a JSON instruction when the web is searched, because search citations and a schema-bound answer exclude each other), the `web_search` server tool, and the server-side refusal `fallbacks: "default"` for Opus and Sonnet (athlete decision 2).
- New streaming client: every Claude request streams through the existing bounded transport (byte limit, cancellation, safe error classification, usage once per request); a paused server-side search is resumed a bounded number of times; a refusal of the whole fallback chain ends with a short safe error.
- New model resolution: the newest model per family from the Models API (refreshed at most once a day), the last model that answered per family, and a rejected newer model that is skipped until a newer one appears. A failing listing keeps the last known models.
- Claude usage is counted in its own daily counters next to OpenAI's.
- The base URL joining helper moves from the OpenAI module to the shared provider transport with a provider-neutral error message.
- Nothing is wired to the Coach or the UI yet.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `model-selection-and-usage`: adds the Claude adapter, the Claude streaming lifecycle, the per-family model resolution and the Claude usage counters.

## Impact

- New `backend/providers/claude_messages_adapter.py`, `backend/providers/claude_models.py`; extended `backend/providers/claude_requests.py`.
- `backend/providers/state.py`, `backend/providers/usage.py` (provider `anthropic`), `backend/providers/http.py` (`endpoint`), `backend/providers/openai_requests.py`, `backend/providers/connection_check_probes.py`.
- Tests: `tests/test_claude_provider.py` with `tests/fixtures/claude_messages.json` (synthetic events in the documented API shapes), `tests/test_provider_state.py`, `tests/test_provider_usage.py`.
