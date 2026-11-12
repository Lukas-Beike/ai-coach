## ADDED Requirements

### Requirement: Transcription stays with OpenAI
The system SHALL transcribe voice input with OpenAI whichever model provider answers the Coach, and SHALL offer the microphone only while an OpenAI key is configured.

#### Scenario: Claude selected
- **WHEN** a Claude family is the Coach model and an OpenAI key is configured
- **THEN** recording and transcription work as before through OpenAI.

#### Scenario: No OpenAI key
- **WHEN** no OpenAI key is configured
- **THEN** the microphone control is disabled while the chat itself stays usable with a configured Claude key.

Evidence: `backend/providers/model_assembly.py:ModelTransportAssembly.audio_transcription_client`, `public/coach.js:updateVoiceButton`; `tests/test_provider_audio.py`, Playwright `e2e/settings-hub.spec.js`.
