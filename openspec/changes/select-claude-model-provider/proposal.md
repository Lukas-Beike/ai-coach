## Why

Issue #2355 lets the athlete choose Claude instead of OpenAI as the Coach's model provider. Parts 1 and 2 added the Anthropic credentials and the Claude adapter behind the neutral model seam. This last part makes Claude selectable and routes every model use (Coach turns with tools, the write-intent check, the packaging-photo analysis and the nutrition web search) to the provider of the selected model, without any fallback from one provider to the other. Voice transcription stays with OpenAI.

## What Changes

- Mehr › Coach & Modell shows one grouped model list (athlete decision 4): the OpenAI models and the Claude families Opus, Sonnet and Haiku, each named with the model it currently resolves to. Choosing an entry selects its provider; entries without a configured key are disabled, and saving a Claude family without an Anthropic key is rejected. The speed selector is hidden for Claude. A rejected newly resolved Claude model shows a short notice under the list.
- One model transport routes every request by the selected model: a Claude family resolves its newest model (part 2) and goes to the Messages API, everything else to OpenAI Responses. A Claude failure never reaches OpenAI.
- Claude turns keep the whole dialogue local: no OpenAI conversation is created or rotated for their attachments.
- The chat is ready when the selected provider has its key; the status hint names the missing key of that provider. The microphone needs the OpenAI key whatever model answers.
- Usage and status shown in the app follow the selected provider; the OpenAI and Claude cards show their own provider status. Diagnostics name the selected provider.
- **BREAKING (rule)**: AGENTS.md "Only Responses API is supported" becomes "OpenAI Responses or the Anthropic Messages API, explicitly selected; no Chat Completions and no cross-provider fallback".

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `model-selection-and-usage`: MU1 adds the Claude families to the explicit selection; MU4 becomes the selected-provider transport without cross-provider fallback.
- `nutrition-photo-analysis`: label extraction uses the selected model's provider.
- `voice-and-notifications`: transcription stays with OpenAI and the microphone needs its key.
- `coach-conversation`: a Claude turn keeps attachments and dialogue local.

## Impact

- `backend/settings.py`, `backend/providers/model_assembly.py`, `backend/providers/claude_models.py`, `backend/providers/claude_requests.py`, `backend/coach/response_transport.py`, `backend/coach/conversation_assembly.py`, `backend/coach/request_payload.py`, `backend/coach/structured_turn.py`, `backend/coach/turn_failures.py`, `backend/http_api/bootstrap_state.py`, `backend/diagnostics/report.py`, `server.py`.
- `public/index.html`, `public/views.js`, `public/coach.js`, `public/shared.js`, `public/styles.css`.
- AGENTS.md, README.md, docs (configuration, coach, features).
