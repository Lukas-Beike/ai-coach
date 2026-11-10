import unittest

from backend.errors import AppError
from backend.providers.audio import (
    VOICE_AUDIO_TYPES,
    AudioTranscriptionClient,
    audio_suffix,
    normalized_audio_type,
)


class FakeHttpClient:
    def __init__(self, response=None):
        self.response = response
        self.calls = []

    def request(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return self.response


class FakeProviderState:
    def __init__(self):
        self.usage = []

    def record_usage(self, provider, response, operation):
        self.usage.append((provider, response, operation))


class AudioProviderTests(unittest.TestCase):
    def client(self, *, http_response=None, **kwargs):
        self.http = FakeHttpClient(http_response)
        dependencies = {
            "max_audio_bytes": 32,
            "openai_api_key": "openai-key",
            "openai_base_url": "https://compatible.example/v1/",
            "default_openai_base_url": "https://api.openai.com/v1",
            "openai_transcription_model": "gpt-transcribe",
            "response_timeout_seconds": 90,
            "http_client": self.http,
        }
        dependencies.update(kwargs)
        return AudioTranscriptionClient(**dependencies)

    def test_normalized_audio_type_removes_parameters_and_casefolds(self):
        self.assertEqual(
            normalized_audio_type(" Audio/WebM; codecs=opus "), "audio/webm"
        )
        self.assertEqual(normalized_audio_type("audio/MP4;foo=bar"), "audio/mp4")
        self.assertEqual(normalized_audio_type(""), "")

    def test_audio_suffix_projects_supported_types_and_unknown_types_to_none(self):
        self.assertEqual(audio_suffix("audio/WAV; charset=binary"), ".wav")
        self.assertEqual(audio_suffix("audio/x-wav"), ".wav")
        self.assertEqual(audio_suffix("audio/unknown"), None)
        self.assertEqual(audio_suffix("text/plain"), None)
        self.assertEqual(
            set(VOICE_AUDIO_TYPES.values()),
            {".webm", ".mp4", ".ogg", ".mp3", ".wav", ".mpga", ".m4a"},
        )

    def test_openai_transcription_preserves_input_and_wire_contract(self):
        client = self.client(http_response={"text": "  Wie trainiere ich morgen?  "})
        audio = b"voice"

        self.assertEqual(
            client.transcribe(audio, "audio/webm; codecs=opus"),
            {
                "transcript": "Wie trainiere ich morgen?",
            },
        )
        self.assertEqual(audio, b"voice")
        self.assertEqual(len(self.http.calls), 1)
        args, kwargs = self.http.calls[0]
        self.assertEqual(
            args, ("POST", "https://compatible.example/v1/audio/transcriptions")
        )
        self.assertEqual(kwargs["headers"], {"Authorization": "Bearer openai-key"})
        self.assertEqual(kwargs["timeout"], 90)
        self.assertEqual(kwargs["service"], "openai")
        self.assertEqual(kwargs["content_type"].split(";", 1)[0], "multipart/form-data")
        body = kwargs["raw_body"]
        self.assertIn(b'name="model"\r\n\r\ngpt-transcribe', body)
        self.assertIn(b'name="languages[]"\r\n\r\nde', body)
        self.assertIn(b'name="file"; filename="voice.webm"', body)
        self.assertIn(b"Content-Type: audio/webm", body)
        self.assertIn(b"Intervals.icu", body)
        self.assertIn(audio, body)

    def test_transcription_records_usage_without_audio_or_transcript(self):
        state = FakeProviderState()
        usage = {"type": "tokens", "input_tokens": 12, "output_tokens": 3}
        client = self.client(
            http_response={"text": "Hallo", "usage": usage}, provider_state=state
        )

        client.transcribe(b"voice", "audio/webm")

        self.assertEqual(len(state.usage), 1)
        provider, response, operation = state.usage[0]
        self.assertEqual((provider, operation), ("openai", "transcription"))
        self.assertEqual(response["usage"], usage)
        self.assertNotIn(b"voice", repr(state.usage).encode())

    def test_transcription_without_usage_still_counts_the_request(self):
        state = FakeProviderState()
        client = self.client(http_response={"text": "Hallo"}, provider_state=state)

        client.transcribe(b"voice", "audio/webm")

        self.assertEqual([entry[2] for entry in state.usage], ["transcription"])

    def test_validation_precedes_provider_io_and_keeps_order(self):
        client = self.client()
        cases = [
            (b"", "audio/webm", 400),
            (bytearray(b"audio"), "audio/webm", 400),
            (b"x" * 33, "audio/webm", 413),
            (b"audio", "audio/flac", 415),
        ]
        for audio, content_type, status in cases:
            with self.subTest(status=status):
                with self.assertRaises(AppError) as raised:
                    client.transcribe(audio, content_type)
                self.assertEqual(raised.exception.status, status)
        self.assertEqual(self.http.calls, [])

    def test_key_errors_are_checked_after_local_validation(self):
        openai = self.client(openai_api_key="")
        for client, provider, message in (
            (
                openai,
                "openai",
                "OpenAI ist nicht eingerichtet. Zugangsdaten unter Mehr → Anbindungen hinterlegen.",
            ),
        ):
            with self.subTest(provider=provider):
                with self.assertRaises(AppError) as raised:
                    client.transcribe(b"audio", "audio/webm")
                self.assertEqual(
                    (raised.exception.status, raised.exception.message), (503, message)
                )
        with self.assertRaises(AppError) as invalid:
            openai.transcribe(b"audio", "audio/flac")
        self.assertEqual(invalid.exception.status, 415)

    def test_empty_or_invalid_provider_responses_are_rejected(self):
        for response in ({}, {"text": "   "}, None):
            with self.subTest(response=response):
                client = self.client(http_response=response)
                with self.assertRaises(AppError) as raised:
                    client.transcribe(b"audio", "audio/webm")
                self.assertEqual(raised.exception.status, 502)


if __name__ == "__main__":
    unittest.main()
