## ADDED Requirements

### Requirement: MU9 Claude Messages adapter behind the model seam
The system SHALL translate a neutral model request into one Anthropic Messages request and its reply into a neutral model turn in a single adapter, so no other code reads Claude's content block types. Tool use SHALL be automatic with at most one call per response, effort SHALL follow the requested reasoning level, and the stable tool list and instructions SHALL be marked for prompt caching.

#### Scenario: Tool round
- **WHEN** a turn continues after a tool call
- **THEN** the request resends the first user message, the earlier assistant content unchanged (thinking signatures included) and all tool results of that round in one user message.

#### Scenario: Images, files and JSON answers
- **WHEN** a request carries images or attachment files or asks for a JSON answer
- **THEN** images become image blocks, files become text document blocks, a schema answer uses the output format, and a plain JSON answer is asked for in the instructions.

#### Scenario: Web search with a schema answer
- **WHEN** a request searches the web and expects a schema-bound answer
- **THEN** it adds the web search server tool (the basic version for Haiku), names the schema in the instructions instead of the output format, and the turn reports the final JSON text and every page read or cited.

#### Scenario: Refusal fallback
- **WHEN** an Opus or Sonnet model is requested
- **THEN** the request asks for the server-side refusal fallback to an older Claude model with its beta header; Haiku requests do not.

Evidence: `backend/providers/claude_messages_adapter.py:request_payload`, `backend/providers/claude_messages_adapter.py:model_turn`; `tests/test_claude_provider.py:ClaudeRequestPayloadTests`, `tests/test_claude_provider.py:ClaudeModelTurnTests`.

### Requirement: MU10 Bounded Claude streaming lifecycle
The system SHALL send every Claude request as one bounded stream with the configured key, API version and timeout, forward visible text as it arrives, stop on cancellation, classify provider failures into safe reasons and record the reported usage once per request. Provider error text and refusal explanations SHALL never reach the athlete or the logs.

#### Scenario: Missing key
- **WHEN** no Anthropic key is configured
- **THEN** the request fails as not configured without contacting the provider.

#### Scenario: Paused search
- **WHEN** the provider pauses a server-side search loop
- **THEN** the paused content is resent as is, at most three times in total.

#### Scenario: Refusal
- **WHEN** the reply ends with a refusal after any fallback
- **THEN** the request fails with a short static message, its usage is billed and the log names the model that answered.

#### Scenario: Failure classification
- **WHEN** the provider answers with an HTTP error or an error event
- **THEN** authentication, unknown model, rate limit, overload, billing and invalid request map to safe reasons with the upstream status and retry delay, without the provider's text.

#### Scenario: Bounds and cancellation
- **WHEN** the stream exceeds the byte limit, ends without its stop event, times out or is cancelled
- **THEN** it fails with the matching safe reason, a cancelled stream is billed with the usage it reported, and the cancellation handle is released.

Evidence: `backend/providers/claude_requests.py:ClaudeMessagesClient`, `backend/providers/claude_requests.py:read_sse_events`, `backend/providers/claude_messages_adapter.py:StreamAssembler`; `tests/test_claude_provider.py:ClaudeStreamClientTests`.

### Requirement: MU11 Newest Claude model per family with a step back
The system SHALL resolve each Claude family (Opus, Sonnet, Haiku) to its newest model from the Models API, listed at most once a day, and remember the last model of each family that answered. When a newly resolved model is rejected as an invalid request or unknown model and the last working model then answers, the family SHALL keep using that model and report the rejected one until a newer model appears.

#### Scenario: Newest model
- **WHEN** the Models API lists several models of a family
- **THEN** the newest plain family model is used; dated snapshots, deployment variants and other families are ignored.

#### Scenario: Listing fails
- **WHEN** the Models API cannot be read
- **THEN** the last known models stay in use, or the built-in current models before the first listing.

#### Scenario: Rejected new model
- **WHEN** the newest model is rejected and the last working model answers the same request
- **THEN** the answer is returned, the new model is marked rejected and later requests use the working model directly.

#### Scenario: No blame without proof
- **WHEN** the rejection is of another kind, no different working model exists, or the working model fails too
- **THEN** the error is raised and nothing is marked rejected.

#### Scenario: Status without provider calls
- **WHEN** the settings read the model in use per family
- **THEN** the stored state answers without a provider request.

Evidence: `backend/providers/claude_models.py:ClaudeModelResolver`, `backend/providers/claude_models.py:newest_by_family`; `tests/test_claude_provider.py:ClaudeModelResolverTests`.

### Requirement: MU12 Separate Claude usage counters
The system SHALL count Claude requests and tokens in their own daily counters, with cache reads and writes included in the input tokens, using the same safe normalization as the OpenAI counters.

#### Scenario: Claude usage
- **WHEN** a Claude request reports usage
- **THEN** the Claude counters add one request and its input, output and total tokens, and the OpenAI counters stay unchanged.

Evidence: `backend/providers/usage.py:usage_counts`, `backend/providers/state.py:ProviderStateService.record_usage`, `backend/providers/claude_messages_adapter.py:neutral_usage`; `tests/test_provider_usage.py`, `tests/test_provider_state.py`.
