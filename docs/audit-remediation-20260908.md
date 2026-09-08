# Full audit remediation

Remediation of the 25 findings reviewed at `ad63d9f`. The installation contract
remains a fresh SQLCipher database and fresh browser profile; current-schema
restore and same-build restart remain supported.

| Finding | Corrected behavior | Regression evidence |
| --- | --- | --- |
| F01 | Adaptive apply requires a published preview and a later user turn referencing that preview. | Same-turn denial and subsequent approval test. |
| F02 | Competition synchronization preserves rows edited or deleted during the provider request. | Concurrent local rename test. |
| F03 | Direct weather reads participate in maintenance draining and validate the current location before persistence. | Delayed fetch versus privacy deletion and location-change tests. |
| F04 | Resumed Coach jobs reread durable cancellation after registering their cancellation event. | Cancellation during session restoration test. |
| F05 | Reset releases the recovered chat busy state and updates controls. | Browser recovery/reset test. |
| F06 | Queued unsent messages participate in leave-page protection without browser text persistence. | Browser beforeunload/storage test. |
| F07 | A missing acceptance receipt retains the message with an error and draft recovery action. | Browser missing-receipt test. |
| F08 | Cancellation requested before the operation ID arrives is applied to that same operation. | Delayed SSE identity test. |
| F09 | Authoritative chat generations invalidate history deleted by another tab while retaining rejected drafts and newly accepted turns. | API generation and browser cross-tab reset/recovery tests. |
| F10 | Profile saves acknowledge only the submitted form snapshot; later edits remain dirty. | Delayed profile PUT test. |
| F11 | Performance polling preserves the active inline metric editor. | Browser editor identity/value test. |
| F12 | Session changes invalidate pending microphone acquisition, stop capture, and discard late transcription. | Late microphone permission test and existing delayed-transcription contract. |
| F13 | Tombstones suppress imports, including the pre-delete remote snapshot; only captured tombstones are acknowledged. | Read/push deletion and concurrent tombstone tests. |
| F14 | Restore normalizes interrupted durable jobs and wakes workers. | SQLCipher backup/restore/claim test. |
| F15 | Reading an asynchronous sync job refreshes the model's training context. | Distinct old/new Garmin context test. |
| F16 | Expired or failed cached weather stays stale; failed refreshes do not record success. | Cache-age and refresh-history tests. |
| F17 | Calendar import and daily planning use interval overlap, including exclusive DTEND. | Ongoing event, daily projection, recurrence and boundary tests. |
| F18 | Nested calendar components cannot overwrite VEVENT properties. | VALARM description test. |
| F19 | Privacy exports stream all stored records without Coach/UI collection limits. | 20-check-in and 1001-library-record export test. |
| F20 | Incomplete provider answers produce partial receipts and retain continuation context. | Truncated-answer test. |
| F21 | Failed or unfinished morning answers are not marked ready. | Failed morning-answer test. |
| F22 | Chat and library expose bounded cursor pagination; library pages query the database without a total collection ceiling. | Browser append/deduplication and 1,001-template HTTP pagination tests. |
| F23 | Empty activity filter results still expose the next server page. | Empty-filter pagination test. |
| F24 | Garmin daily scheduling is independent of Intervals configuration. | Garmin-only configuration test. |
| F25 | Test bootstrap intercepts dotenv reads before importing the server and supplies explicit provider configuration. | Subprocess import with denied dotenv reads and synthetic inherited credentials. |

The additional 320-pixel focus failure is corrected by revealing today's agenda
again after the navigation layout settles. The existing keyboard/font-size
browser scenario verifies it. Frontend assets and the service worker use v200.

Validation uses mocked providers and disposable fixture data. Real provider
accounts, model language-recognition quality, physical microphones, and OS-level
notification UI are outside this remediation's runtime validation. No previous
installation data is converted, deleted, or used as a test fixture.
