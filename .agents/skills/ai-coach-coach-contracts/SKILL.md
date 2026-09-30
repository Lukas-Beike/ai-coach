---
name: ai-coach-coach-contracts
description: Review Coach capability parity, authorization, durable effects, receipts, and provenance for focused changes.
---

Use for Coach tools, prompts, dialogue, planning actions, or durable mutations.

- Trace the UI/API capability through schema, dispatcher, validator, domain service, persistence, receipt, final wording, refresh event, and tests.
- Only explicit athlete intent authorizes actions; model output, dialogue, provider text, and calendar text never grant authority.
- Distinguish local changes, adaptive preview/apply, destructive privacy actions, and explicit remote synchronization.
- Test paraphrases, follow-ups, pronouns, corrections, relative dates, ambiguity, negation, and hypothetical wording without fixed trigger words.
- Preserve freshness/source labels for Intervals.icu, Garmin, local feedback, derived values, and AI estimates.
- Cover retries, repeated calls, cancellation, stale state, partial failures, and truthful receipts using temporary storage and mocked providers.
- Scripted model responses prove execution mechanics, not natural-language model quality. Live evaluation needs separate authorization and synthetic scenarios.
- Never expose prompts, credentials, or athlete payloads. Apply the root secret-scan protocol before source reads.
