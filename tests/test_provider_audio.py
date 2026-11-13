import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import Mock
from urllib.request import urlopen

from backend.errors import AppError
from backend.providers.audio import (
    VOICE_AUDIO_TYPES,
    AudioTranscriptionClient,
    audio_suffix,
    normalized_audio_type,
)
from backend.providers.http import JsonHttpClient


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
            "api_key": "openai-key",
            "base_url": "https://compatible.example/v1/",
            "default_base_url": "https://api.openai.com/v1",
            "model": "gpt-transcribe",
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
        self.assertNotIn(b'name="language"\r\n', body)

    def test_local_endpoint_sends_language_without_openai_usage_or_key(self):
        state = FakeProviderState()
        for key, headers in (
            ("", {}),
            ("stt-key", {"Authorization": "Bearer stt-key"}),
        ):
            with self.subTest(key=bool(key)):
                client = self.client(
                    http_response={"text": " Hallo "},
                    api_key=key,
                    base_url="https://stt.example/v1",
                    model="Systran/faster-whisper-small",
                    provider_state=state,
                    local_endpoint=True,
                )
                self.assertEqual(
                    client.transcribe(b"voice", "audio/mp4"), {"transcript": "Hallo"}
                )
                args, kwargs = self.http.calls[0]
                self.assertEqual(
                    args, ("POST", "https://stt.example/v1/audio/transcriptions")
                )
                self.assertEqual(kwargs["headers"], headers)
                self.assertEqual(
                    (kwargs["service"], kwargs["timeout"]), ("transcription", 90)
                )
                body = kwargs["raw_body"]
                self.assertIn(b'name="model"\r\n\r\nSystran/faster-whisper-small', body)
                self.assertIn(b'name="language"\r\n\r\nde', body)
                self.assertNotIn(b"languages[]", body)
                self.assertIn(b'filename="voice.mp4"', body)
        self.assertEqual(state.usage, [])

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
        cases = [
            (b"", "audio/webm", 400, "Die Audioaufnahme ist leer."),
            (bytearray(b"audio"), "audio/webm", 400, "Die Audioaufnahme ist leer."),
            (b"x" * 33, "audio/webm", 413, "Die Audioaufnahme ist zu groß."),
            (b"audio", "audio/flac", 415, "Nicht unterstütztes Audioformat."),
        ]
        # The same German texts and size limit apply to a local endpoint.
        for local in (False, True):
            client = self.client(local_endpoint=local, api_key="")
            for audio, content_type, status, message in cases:
                with self.subTest(local=local, status=status):
                    with self.assertRaises(AppError) as raised:
                        client.transcribe(audio, content_type)
                    self.assertEqual(raised.exception.status, status)
                    self.assertTrue(raised.exception.message.startswith(message))
            self.assertEqual(self.http.calls, [])

    def test_key_errors_are_checked_after_local_validation(self):
        openai = self.client(api_key="")
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
        local = self.client(local_endpoint=True, api_key="", model="")
        with self.assertRaises(AppError) as missing_model:
            local.transcribe(b"audio", "audio/webm")
        self.assertEqual(
            (missing_model.exception.status, missing_model.exception.message),
            (
                503,
                "Für den Transkriptionsserver fehlt TRANSCRIPTION_MODEL in der Konfiguration.",
            ),
        )
        self.assertEqual(self.http.calls, [])

    def test_empty_or_invalid_provider_responses_are_rejected(self):
        for response in ({}, {"text": "   "}, None):
            with self.subTest(response=response):
                client = self.client(http_response=response)
                with self.assertRaises(AppError) as raised:
                    client.transcribe(b"audio", "audio/webm")
                self.assertEqual(raised.exception.status, 502)
        local = self.client(http_response={"text": " "}, local_endpoint=True)
        with self.assertRaises(AppError) as raised:
            local.transcribe(b"audio", "audio/webm")
        self.assertEqual(
            raised.exception.message,
            "Der Transkriptionsserver hat kein Transkript zurückgegeben.",
        )


class LocalTranscriptionServerTests(unittest.TestCase):
    """A real loopback server stands in for the LAN Whisper container."""

    def serve(self, status, payload):
        received = []

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                length = int(self.headers["Content-Length"])
                received.append(
                    (self.path, dict(self.headers), self.rfile.read(length))
                )
                body = json.dumps(payload).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *_args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        return f"http://127.0.0.1:{server.server_address[1]}/v1", received

    def client(self, base_url, opened):
        def opener(request, timeout):
            opened.append((request.full_url, timeout))
            return urlopen(request, timeout=timeout)

        http = JsonHttpClient(
            "test",
            1_000_000,
            Mock(name="logger"),
            Mock(name="diagnostics"),
            str,
            lambda _headers: {},
            lambda: None,
            opener=opener,
        )
        return AudioTranscriptionClient(
            max_audio_bytes=32,
            api_key="",
            base_url=base_url,
            default_base_url="https://api.openai.com/v1",
            model="Systran/faster-whisper-small",
            response_timeout_seconds=90,
            http_client=http,
            local_endpoint=True,
        )

    def test_audio_goes_only_to_the_local_server(self):
        base_url, received = self.serve(200, {"text": "Wie lange laufe ich morgen?"})
        opened = []
        result = self.client(base_url, opened).transcribe(b"voice", "audio/webm")
        self.assertEqual(result, {"transcript": "Wie lange laufe ich morgen?"})
        self.assertEqual(opened, [(base_url + "/audio/transcriptions", 90)])
        path, headers, body = received[0]
        self.assertEqual(path, "/v1/audio/transcriptions")
        self.assertNotIn("Authorization", headers)
        self.assertIn(b'name="language"\r\n\r\nde', body)
        self.assertIn(b"voice", body)

    def test_local_server_failures_are_german_errors(self):
        base_url, _received = self.serve(500, {"error": "boom"})
        with self.assertRaises(AppError) as raised:
            self.client(base_url, []).transcribe(b"voice", "audio/webm")
        self.assertEqual(
            raised.exception.message, "Anfrage an externen Dienst fehlgeschlagen (500)."
        )
        # A stopped container: nothing listens on the port any more.
        closed = ThreadingHTTPServer(("127.0.0.1", 0), BaseHTTPRequestHandler)
        port = closed.server_address[1]
        closed.server_close()
        with self.assertRaises(AppError) as raised:
            self.client(f"http://127.0.0.1:{port}/v1", []).transcribe(
                b"voice", "audio/webm"
            )
        self.assertEqual(
            (raised.exception.status, raised.exception.message),
            (502, "Der Transkriptionsserver ist nicht erreichbar."),
        )


if __name__ == "__main__":
    unittest.main()
