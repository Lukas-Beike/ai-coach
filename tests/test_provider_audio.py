import base64
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


class FakeGeminiClient:
    def __init__(self, response=None):
        self.response = response
        self.calls = []

    def generate(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return self.response


class AudioProviderTests(unittest.TestCase):
    def client(self, *, http_response=None, gemini_response=None, **kwargs):
        self.http = FakeHttpClient(http_response)
        self.gemini = FakeGeminiClient(gemini_response)
        dependencies = {
            "max_audio_bytes": 32,
            "openai_api_key": "openai-key",
            "gemini_api_key": "gemini-key",
            "openai_base_url": "https://compatible.example/v1/",
            "default_openai_base_url": "https://api.openai.com/v1",
            "openai_transcription_model": "gpt-transcribe",
            "response_timeout_seconds": 90,
            "http_client": self.http,
            "gemini_client": self.gemini,
        }
        dependencies.update(kwargs)
        return AudioTranscriptionClient(**dependencies)

    def test_normalized_audio_type_removes_parameters_and_casefolds(self):
        self.assertEqual(normalized_audio_type(" Audio/WebM; codecs=opus "), "audio/webm")
        self.assertEqual(normalized_audio_type("audio/MP4;foo=bar"), "audio/mp4")
        self.assertEqual(normalized_audio_type(""), "")

    def test_audio_suffix_projects_supported_types_and_unknown_types_to_none(self):
        self.assertEqual(audio_suffix("audio/WAV; charset=binary"), ".wav")
        self.assertEqual(audio_suffix("audio/x-wav"), ".wav")
        self.assertEqual(audio_suffix("audio/unknown"), None)
        self.assertEqual(audio_suffix("text/plain"), None)
        self.assertEqual(set(VOICE_AUDIO_TYPES.values()), {".webm", ".mp4", ".ogg", ".mp3", ".wav", ".mpga", ".m4a"})

    def test_openai_transcription_preserves_input_and_wire_contract(self):
        client = self.client(http_response={"text": "  Wie trainiere ich morgen?  "})
        audio = b"voice"

        self.assertEqual(client.transcribe(audio, "audio/webm; codecs=opus", provider="openai", model="ignored"), {
            "transcript": "Wie trainiere ich morgen?",
        })
        self.assertEqual(audio, b"voice")
        self.assertEqual(len(self.http.calls), 1)
        args, kwargs = self.http.calls[0]
        self.assertEqual(args, ("POST", "https://compatible.example/v1/audio/transcriptions"))
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

    def test_gemini_transcription_uses_exact_payload_and_transient_base64(self):
        client = self.client(gemini_response={"candidates": [{"content": {"parts": [{"text": "Transkript"}]}}]})
        audio = b"binary voice"

        self.assertEqual(client.transcribe(audio, "audio/MP4", provider="gemini", model="gemini-model"), {
            "transcript": "Transkript",
        })
        self.assertEqual(audio, b"binary voice")
        self.assertEqual(len(self.gemini.calls), 1)
        args, kwargs = self.gemini.calls[0]
        self.assertEqual(args[0], "gemini-model")
        self.assertEqual(kwargs, {"operation": "transcription"})
        payload = args[1]
        self.assertEqual(payload["generationConfig"], {"temperature": 0})
        parts = payload["contents"][0]["parts"]
        self.assertEqual(parts[0]["inlineData"], {
            "mimeType": "audio/mp4",
            "data": base64.b64encode(audio).decode("ascii"),
        })
        self.assertEqual(parts[1]["text"], "Transkribiere diese deutsche Trainingsfrage wortgetreu. Gib ausschließlich das Transkript zurück.")
        self.assertEqual(self.http.calls, [])

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
                    client.transcribe(audio, content_type, provider="openai", model="model")
                self.assertEqual(raised.exception.status, status)
        self.assertEqual(self.http.calls, [])
        self.assertEqual(self.gemini.calls, [])

    def test_key_errors_are_checked_after_local_validation(self):
        openai = self.client(openai_api_key="")
        gemini = self.client(gemini_api_key="")
        for client, provider, message in (
            (openai, "openai", "OPENAI_API_KEY ist nicht konfiguriert."),
            (gemini, "gemini", "GEMINI_API_KEY ist nicht konfiguriert."),
        ):
            with self.subTest(provider=provider):
                with self.assertRaises(AppError) as raised:
                    client.transcribe(b"audio", "audio/webm", provider=provider, model="model")
                self.assertEqual((raised.exception.status, raised.exception.message), (503, message))
        with self.assertRaises(AppError) as invalid:
            openai.transcribe(b"audio", "audio/flac", provider="openai", model="model")
        self.assertEqual(invalid.exception.status, 415)

    def test_empty_or_invalid_provider_responses_are_rejected(self):
        for response in ({}, {"text": "   "}, None):
            with self.subTest(response=response):
                client = self.client(http_response=response)
                with self.assertRaises(AppError) as raised:
                    client.transcribe(b"audio", "audio/webm", provider="openai", model="model")
                self.assertEqual(raised.exception.status, 502)
        client = self.client(gemini_response={"candidates": []})
        with self.assertRaises(AppError) as raised:
            client.transcribe(b"audio", "audio/webm", provider="gemini", model="model")
        self.assertEqual(raised.exception.status, 502)


if __name__ == "__main__":
    unittest.main()
