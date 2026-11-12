import base64
import hashlib
import json
import struct
import unittest
import zipfile
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock, patch

from support import wire_step
from test_coach_dialogue import DialogueHarness, server

from backend.coach import attachments as coach_attachments
from backend.coach import structured_tool_round
from backend.coach.attachments import (
    _FIT_SPORTS,
    AttachmentRequestTooLarge,
    _fit_session_summary,
    fit_summary,
    gpx_summary,
    model_attachments,
    validate_attachments,
)
from backend.errors import AppError
from backend.providers import openai_requests, openai_stream
from backend.providers.fit_file import _fit_crc16, _fit_data_record
from backend.providers.openai_responses_adapter import model_input

GPX = b'<gpx xmlns="http://www.topografix.com/GPX/1/1"><trk><trkseg><trkpt lat="0" lon="0"><ele>10</ele></trkpt><trkpt lat="0" lon="0.01"><ele>20</ele></trkpt></trkseg></trk></gpx>'
PNG = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aFOsAAAAASUVORK5CYII="


def fit_session_fixture():
    fields = [
        (2, 4, 6),
        (5, 1, 0),
        (7, 4, 6),
        (9, 4, 6),
        (16, 1, 2),
        (17, 1, 2),
        (20, 2, 4),
    ]
    definition = bytes([0x40, 0, 0]) + struct.pack("<H", 18) + bytes([len(fields)])
    definition += b"".join(bytes(field) for field in fields)
    record = (
        bytes([0])
        + struct.pack("<I", 1_000_000)
        + bytes([2])
        + struct.pack("<I", 3_600_000)
    )
    record += struct.pack("<I", 123_450) + bytes([145, 170]) + struct.pack("<H", 220)
    payload = definition + record
    header = (
        bytes([12, 0x10])
        + struct.pack("<H", 0)
        + struct.pack("<I", len(payload))
        + b".FIT"
    )
    return header + payload


FIT = fit_session_fixture()


def fit_records_fixture():
    fields = [(253, 4, 6), (2, 2, 4), (3, 1, 2), (4, 1, 2), (5, 4, 6)]
    definition = bytes([0x42, 0, 0]) + struct.pack("<H", 20) + bytes([len(fields)])
    definition += b"".join(bytes(field) for field in fields)
    first = (
        bytes([2])
        + struct.pack("<I", 1_000_000)
        + struct.pack("<H", 2_500)
        + bytes([150, 90])
        + struct.pack("<I", 100_000)
    )
    # Compressed-timestamp records use a definition without field 253 (FIT SDK).
    compressed = [field for field in fields if field[0] != 253]
    definition += bytes([0x43, 0, 0]) + struct.pack("<H", 20)
    definition += bytes([len(compressed)]) + b"".join(bytes(f) for f in compressed)
    second = (
        bytes([0xE2])
        + struct.pack("<H", 2_550)
        + bytes([152, 92])
        + struct.pack("<I", 200_000)
    )
    payload = definition + first + second
    header = (
        bytes([12, 0x10])
        + struct.pack("<H", 0)
        + struct.pack("<I", len(payload))
        + b".FIT"
    )
    return header + payload


FIT_RECORDS = fit_records_fixture()


def fit_file(*messages):
    """Build a FIT file from (global_number, [(field, size, base_type)], rows)."""
    payload = b""
    for local, (number, fields, rows) in enumerate(messages):
        payload += bytes([0x40 | local, 0, 0]) + struct.pack("<H", number)
        payload += bytes([len(fields)]) + b"".join(bytes(field) for field in fields)
        payload += b"".join(bytes([local]) + row for row in rows)
    header = (
        bytes([12, 0x10])
        + struct.pack("<H", 0)
        + struct.pack("<I", len(payload))
        + b".FIT"
    )
    return header + payload


def raw_altitude(meters):
    return (meters + 500) * 5


class FitEnhancedFieldTests(unittest.TestCase):
    def test_record_altitude_prefers_enhanced_field_when_valid(self):
        enhanced_only = fit_file(
            (
                20,
                [(78, 4, 6)],
                [struct.pack("<I", raw_altitude(m)) for m in (100, 110, 105)],
            )
        )
        base_only = fit_file(
            (
                20,
                [(2, 2, 4)],
                [struct.pack("<H", raw_altitude(m)) for m in (100, 120, 90)],
            )
        )
        both = fit_file(
            (
                20,
                [(2, 2, 4), (78, 4, 6)],
                [
                    struct.pack("<HI", raw_altitude(base), raw_altitude(enhanced))
                    for base, enhanced in ((100, 100), (120, 110), (90, 105))
                ],
            )
        )
        invalid_enhanced = fit_file(
            (
                20,
                [(2, 2, 4), (78, 4, 6)],
                [
                    struct.pack("<HI", raw_altitude(base), 0xFFFFFFFF)
                    for base in (100, 120, 90)
                ],
            )
        )
        mixed_rows = fit_file(
            (
                20,
                [(2, 2, 4), (78, 4, 6)],
                [
                    struct.pack("<HI", raw_altitude(100), raw_altitude(100)),
                    struct.pack("<HI", raw_altitude(120), 0xFFFFFFFF),
                    struct.pack("<HI", raw_altitude(90), raw_altitude(105)),
                ],
            )
        )
        for data, ascent, descent in (
            (enhanced_only, 10, 5),
            (base_only, 20, 30),
            (both, 10, 5),
            (invalid_enhanced, 20, 30),
            (mixed_rows, 20, 15),
        ):
            with self.subTest(ascent=ascent, descent=descent):
                summary = fit_summary(data)
                self.assertEqual(summary["ascent_m"], ascent)
                self.assertEqual(summary["descent_m"], descent)

    def test_session_speed_prefers_enhanced_field_when_valid(self):
        enhanced_only = fit_file(
            (18, [(124, 4, 6), (125, 4, 6)], [struct.pack("<II", 6000, 9000)])
        )
        base_only = fit_file(
            (18, [(14, 2, 4), (15, 2, 4)], [struct.pack("<HH", 5000, 8000)])
        )
        both = fit_file(
            (
                18,
                [(14, 2, 4), (15, 2, 4), (124, 4, 6), (125, 4, 6)],
                [struct.pack("<HHII", 5000, 8000, 6000, 9000)],
            )
        )
        invalid_enhanced = fit_file(
            (
                18,
                [(14, 2, 4), (15, 2, 4), (124, 4, 6), (125, 4, 6)],
                [struct.pack("<HHII", 5000, 8000, 0xFFFFFFFF, 0xFFFFFFFF)],
            )
        )
        for data, avg, max_speed in (
            (enhanced_only, 21.6, 32.4),
            (base_only, 18.0, 28.8),
            (both, 21.6, 32.4),
            (invalid_enhanced, 18.0, 28.8),
        ):
            with self.subTest(avg=avg, max_speed=max_speed):
                summary = fit_summary(data)
                self.assertAlmostEqual(summary["avg_speed_kmh"], avg, places=3)
                self.assertAlmostEqual(summary["max_speed_kmh"], max_speed, places=3)

    def test_record_max_speed_uses_enhanced_speed_only(self):
        enhanced_only = fit_file(
            (
                20,
                [(73, 4, 6)],
                [struct.pack("<I", speed) for speed in (8000, 10000, 9000)],
            )
        )
        self.assertAlmostEqual(
            fit_summary(enhanced_only)["max_speed_kmh"], 36.0, places=3
        )

    def test_record_max_speed_uses_speed_field_without_enhanced_speed(self):
        base_only = fit_file(
            (
                20,
                [(6, 2, 4)],
                [struct.pack("<H", speed) for speed in (8000, 12000, 9000)],
            )
        )
        self.assertAlmostEqual(fit_summary(base_only)["max_speed_kmh"], 43.2, places=3)

    def test_record_max_speed_prefers_enhanced_speed_per_row(self):
        both = fit_file(
            (
                20,
                [(6, 2, 4), (73, 4, 6)],
                [struct.pack("<HI", 12000, 10000), struct.pack("<HI", 11000, 8000)],
            )
        )
        summary = fit_summary(both)
        self.assertAlmostEqual(summary["max_speed_kmh"], 36.0, places=3)
        self.assertNotIn("avg_speed_kmh", summary)

    def test_session_max_speed_wins_over_record_speeds(self):
        session_wins = fit_file(
            (18, [(15, 2, 4)], [struct.pack("<H", 8000)]),
            (20, [(73, 4, 6)], [struct.pack("<I", 10000)]),
        )
        summary = fit_summary(session_wins)
        self.assertAlmostEqual(summary["max_speed_kmh"], 28.8, places=3)
        self.assertNotIn("avg_speed_kmh", summary)


class AttachmentTests(DialogueHarness, unittest.TestCase):
    def upload(self, data=GPX, name="route.gpx"):
        return {"name": name, "data": base64.b64encode(data).decode("ascii")}

    GOLDEN = Path(__file__).parent / "fixtures" / "coach_wire_payloads.json"

    def _wire(self, turn, message, steps, attachments=None, conversation=False):
        """Run one queued job over the real transport; return its outgoing payloads."""
        server.COACH_BACKGROUND_JOBS.job_submission_service().enqueue(
            message, turn, "synthetic-session", attachments=attachments
        )
        sent = []
        queue = iter(steps)

        def stream(_client, payload, _on_delta, *_args, **_kwargs):
            sent.append(json.dumps(payload))
            step = next(queue)
            if callable(step):
                step = step(payload)
            if isinstance(step, Exception):
                raise step
            return step

        def classify(_client, payload):
            sent.append(json.dumps(payload))
            return {"output_text": json.dumps(self.gate_verdict)}

        provision = Mock(
            binding=Mock(return_value="synthetic-conversation"),
            bind_remote=Mock(return_value="synthetic-conversation"),
            rotate=Mock(return_value="synthetic-conversation"),
        )
        with (
            patch.object(openai_stream.OpenAIStreamClient, "stream", stream),
            patch.object(openai_requests.OpenAIResponsesClient, "responses", classify),
            patch.object(
                server.COACH_CONVERSATION, "provision_service", return_value=provision
            ),
            patch(
                "backend.coach.context.CoachTrainingContextService.build",
                return_value="Synthetic local data",
            ),
        ):
            server.COACH_TURNS.chat_turn_service().run(
                message,
                client_turn_id=turn,
                session_csrf_hash="synthetic-session",
                background_job=True,
            )
        # Instructions and tool schemas are fixed text: compare their hash.
        return [
            {
                key: (
                    {"sha256": hashlib.sha256(json.dumps(value).encode()).hexdigest()}
                    if key in {"instructions", "tools"}
                    else value
                )
                for key, value in json.loads(payload).items()
            }
            for payload in sent
        ]

    def _photo_wire(self):
        """Run a packaging-photo extraction; return the POSTs that reach OpenAI."""
        sent = []

        def post(method, url, payload=None, **_kwargs):
            sent.append(
                {
                    "method": method,
                    "url": url,
                    "payload": json.loads(json.dumps(payload)),
                }
            )
            return {
                "output_text": '{"name": "Synthetic whey", "kcal": 376}',
                "output": [],
            }

        image = base64.b64encode(b"\xff\xd8\xffsynthetic-image").decode("ascii")
        with (
            patch.object(
                server, "CONFIG", replace(server.CONFIG, openai_api_key="test-key")
            ),
            patch.object(
                server.PROVIDER_TRANSPORT.json_http_client(),
                "request",
                side_effect=post,
            ),
        ):
            server.NUTRITION_ASSEMBLY.meal_library_service().extract_packaging_photo(
                {"image_data_url": "data:image/jpeg;base64," + image}
            )
        return sent

    def _budget_exhausted(self, read, text):
        with patch.object(structured_tool_round, "COACH_TOOL_MAX_ROUNDS", 1):
            return self._wire(
                "wire-budget", "Noch mal lesen", [read("c-5"), read("c-6"), text]
            )

    def test_outgoing_wire_payloads_of_representative_turns_are_unchanged(self):
        """Golden payloads, recorded before the model seam (#2073 PR 2)."""
        reasoning = {"type": "reasoning", "id": "rs-1", "encrypted_content": "enc-1"}
        bare = {"type": "reasoning", "id": "rs-2"}

        def read(call_id):
            return lambda _: {
                **self.call("read_training_state", call_id=call_id),
                "output": [
                    reasoning,
                    bare,
                    self.call("read_training_state", call_id=call_id)["output"][0],
                ],
            }

        text = {"output_text": "Fertig."}
        server.PLANNING_DATA.competition().save(
            {
                "name": "Synthetic Giro",
                "event_date": "2026-10-03",
                "sport": "Ride",
                "priority": "A",
            }
        )
        (competition,) = server.PLANNING_DATA.competition().list()
        delete = lambda _: self.call(
            "delete_competition",
            {"competition_id": competition["id"]},
            [f"competition:{competition['id']}"],
        )
        self.confirm_impact("competition", delete=True)
        image = {"name": "chart.png", "data": PNG}
        invalid = AppError(
            502, "Synthetic invalid conversation", reason="conversation_state_invalid"
        )
        incomplete = {
            "status": "incomplete",
            "incomplete_details": {"reason": "max_output_tokens"},
            "output": [reasoning],
        }
        actual = {
            "plain": self._wire("wire-plain", "Wie war meine Woche?", [text]),
            "tool_round": self._wire(
                "wire-tools", "Plan ansehen", [read("c-1"), read("c-2"), text]
            ),
            "classifier_delete": self._wire(
                "wire-delete", "Den Giro entfernen", [delete, text]
            ),
            "reasoning_escalation": self._wire(
                "wire-tokens", "Erkläre die Woche", [incomplete, text]
            ),
            "tool_budget_exhausted": self._budget_exhausted(read, text),
            "nutrition_photo": self._photo_wire(),
            "attachment_conversation": self._wire(
                "wire-image", "Analysiere das", [read("c-3"), text], [image]
            ),
            "conversation_recovery": self._wire(
                "wire-recover",
                "Und jetzt?",
                [invalid, read("c-4"), text],
                [self.upload()],
            ),
        }
        # The competition id is generated per run.
        actual = json.loads(
            json.dumps(actual).replace(competition["id"], "synthetic-competition")
        )
        expected = json.loads(self.GOLDEN.read_text(encoding="utf-8"))
        self.assertEqual(expected, json.loads(json.dumps(actual, sort_keys=True)))

    def test_gpx_distance_elevation_and_segment_boundaries(self):
        summary = gpx_summary(GPX)
        self.assertAlmostEqual(summary["distance_km"], 1.112, places=3)
        self.assertEqual(summary["ascent_m_raw"], 10)
        separated = b'<gpx><trk><trkseg><trkpt lat="0" lon="0"/></trkseg><trkseg><trkpt lat="50" lon="50"/></trkseg></trk></gpx>'
        self.assertEqual(gpx_summary(separated)["distance_km"], 0)
        self.assertEqual(gpx_summary(separated)["elevation_point_count"], 0)

    def test_fit_is_validated_and_sent_as_parsed_measurements(self):
        attachment = self.upload(FIT, "ride.fit")
        validated = validate_attachments([attachment])
        self.assertEqual(validated[0]["type"], "fit")
        self.assertEqual(validated[0]["data"], attachment["data"])
        self.assertEqual(validated[0]["summary"]["distance_km"], 1.234)
        self.assertEqual(validated[0]["summary"]["avg_heart_rate_bpm"], 145)
        request_input = model_input(
            "Analyze this activity", model_attachments(validated)
        )
        raw_part = request_input[0]["content"][-1]
        self.assertEqual(raw_part["type"], "input_file")
        self.assertEqual(raw_part["filename"], "ride.fit.json")
        self.assertTrue(
            raw_part["file_data"].startswith("data:application/json;base64,")
        )
        envelope = json.loads(
            base64.b64decode(raw_part["file_data"].split(",", 1)[1]).decode("utf-8")
        )
        self.assertNotIn("raw_base64", envelope)
        self.assertNotIn(attachment["data"], json.dumps(envelope))
        self.assertEqual(envelope["sessions"][0]["avg_heart_rate_bpm"], 145)

    def test_fit_records_use_standard_headers_fields_and_compressed_timestamps(self):
        summary = fit_summary(FIT_RECORDS)
        self.assertEqual(summary["record_count"], 2)
        self.assertEqual(summary["duration_s"], 2)
        self.assertEqual(summary["distance_km"], 2.0)
        self.assertEqual(summary["max_heart_rate_bpm"], 152)
        self.assertEqual(summary["max_cadence_rpm"], 92)
        self.assertEqual(summary["ascent_m"], 10)

    def test_fit_sport_enum_and_timestamp_state_follow_the_profile(self):
        self.assertEqual(fit_summary(FIT)["sport"], "cycling")
        self.assertEqual(
            {
                _FIT_SPORTS[6],
                _FIT_SPORTS[11],
                _FIT_SPORTS[32],
                _FIT_SPORTS[41],
                _FIT_SPORTS[254],
            },
            {"basketball", "walking", "sailing", "kayaking", "all"},
        )
        definition = (0, 21, [(253, 4, 6)], [])
        _, last_timestamp, _ = _fit_data_record(
            struct.pack("<I", 1_000_100), 0, 0, definition, 4, None
        )
        _, compressed_timestamp, message = _fit_data_record(
            b"", 0, 0x85, (0, 21, [], []), 0, last_timestamp
        )
        self.assertGreater(compressed_timestamp, last_timestamp)
        self.assertEqual(message[1][253], compressed_timestamp)

    def test_rejects_unsafe_xml_coordinates_encoding_and_types(self):
        invalid = [
            self.upload(b'<!DOCTYPE gpx [<!ENTITY x "boom">]><gpx/>'),
            self.upload(b'<gpx><rte><rtept lat="nan" lon="0"/></rte></gpx>'),
            self.upload(b"<gpx/>"),
            self.upload(b"garbage", "fake.png"),
            self.upload(b"garbage", "fake.fit"),
            self.upload(name="../route.gpx"),
            {"name": "x.gpx", "data": "%%%"},
            self.upload(b"x" * 5_000_001),
        ]
        for item in invalid:
            with self.assertRaises(ValueError):
                validate_attachments([item])
        with self.assertRaises(ValueError):
            validate_attachments([self.upload()] * 5)

    def test_fit_rejects_empty_definitions(self):
        fields = bytes([0x40, 0, 0]) + struct.pack("<H", 20) + bytes([0])
        header = (
            bytes([12, 0x10])
            + struct.pack("<H", 0)
            + struct.pack("<I", len(fields))
            + b".FIT"
        )
        with self.assertRaises(ValueError):
            fit_summary(header + fields)

    def test_fit_rejects_invalid_header_and_file_checksums(self):
        payload = FIT
        header = (
            bytes([14, 0x10])
            + struct.pack("<H", 0)
            + struct.pack("<I", len(payload) - 12)
            + b".FIT"
        )
        checksummed = bytearray(header + b"\x00\x00" + payload[12:])
        checksummed[12:14] = struct.pack("<H", _fit_crc16(checksummed[:12]))
        checksummed += struct.pack("<H", _fit_crc16(checksummed))
        self.assertEqual(fit_summary(bytes(checksummed))["distance_km"], 1.234)
        checksummed[-1] ^= 0x01
        with self.assertRaises(ValueError):
            fit_summary(bytes(checksummed))
        with self.assertRaises(ValueError):
            fit_summary(checksummed[:-1])

    def test_fit_session_metrics_are_aggregated(self):
        sessions = [
            {
                2: 1_000_000,
                5: 2,
                7: 10_000,
                8: 10_000,
                9: 500_000,
                16: 100,
                17: 120,
                22: 40,
                34: 100,
                35: 100,
            },
            {
                2: 1_000_010,
                5: 5,
                7: 20_000,
                8: 10_000,
                9: 300_000,
                16: 130,
                17: 140,
                22: 60,
                34: 300,
                35: 200,
            },
        ]
        summary = _fit_session_summary(
            [(18, session) for session in sessions], sessions, []
        )
        self.assertEqual(summary["duration_s"], 30)
        self.assertEqual(summary["timer_time_s"], 20)
        self.assertEqual(summary["distance_km"], 8)
        self.assertEqual(summary["max_heart_rate_bpm"], 140)
        self.assertEqual(summary["avg_heart_rate_bpm"], 115)
        self.assertEqual(summary["normalized_power_w"], 253.044)
        self.assertEqual(summary["training_stress_score"], 30)
        self.assertEqual(summary["sport"], "multisport")

    def test_attachment_persists_for_worker_without_leaking_into_history(self):
        server.COACH_BACKGROUND_JOBS.job_submission_service().enqueue(
            "",
            "attachments-turn",
            "synthetic-csrf",
            attachments=[self.upload(), {"name": "chart.png", "data": PNG}],
        )
        job = server.COACH_BACKGROUND_JOBS.job_store().claim()
        self.assertTrue(server.COACH_BACKGROUND_JOBS.job_store().message(job))
        with server.database_manager().unit_of_work() as db:
            row = db.execute(
                "SELECT attachments FROM messages WHERE role='user'"
            ).fetchone()
        saved = json.loads(row["attachments"])
        self.assertEqual(saved[0]["summary"]["point_count"], 2)
        self.assertEqual(saved[1]["data"], PNG)
        history = server.COACH_CONVERSATION.message_service().list()
        self.assertNotIn(PNG, json.dumps(history))
        self.assertEqual(
            json.loads(history[0]["attachment_names"]), ["route.gpx", "chart.png"]
        )
        archive_path = server.PRIVACY_ASSEMBLY.archive_export_service().create_file()
        try:
            with zipfile.ZipFile(archive_path) as archive:
                exported = [
                    json.loads(line)
                    for line in archive.read("messages.jsonl").splitlines()
                ]
        finally:
            archive_path.unlink()
        self.assertEqual(json.loads(exported[0]["attachments"]), saved)
        server.COACH_CONVERSATION.message_service().add("assistant", "Synthetic answer")
        server.COACH_CONVERSATION.message_service().add(
            "user", "What does the chart show?"
        )

    def test_invalid_upload_does_not_create_a_command(self):
        with self.assertRaises(AppError):
            server.COACH_BACKGROUND_JOBS.job_submission_service().enqueue(
                "Analyze",
                "invalid-turn",
                "synthetic-csrf",
                attachments=[self.upload(b"bad")],
            )
        self.assertEqual(server.COACH_CONVERSATION.message_service().list(), [])

    def test_attachment_storage_quota_prevents_backup_growth(self):
        with (
            patch.object(coach_attachments, "MAX_ATTACHMENT_STORAGE_BYTES", 10),
            self.assertRaises(AppError) as error,
        ):
            server.COACH_BACKGROUND_JOBS.job_submission_service().enqueue(
                "Analyze",
                "quota-turn",
                "synthetic-csrf",
                attachments=[{"name": "chart.png", "data": PNG}],
            )
        self.assertEqual(error.exception.reason, "attachment_storage_quota")
        self.assertEqual(server.COACH_CONVERSATION.message_service().list(), [])

    def test_outgoing_provider_payload_is_limited_to_request_budget(self):
        fit_upload = self.upload(FIT, "ride.fit")
        outgoing = len(
            coach_attachments.openai_attachment_data(
                validate_attachments([fit_upload])[0]
            )[0]
        )
        self.assertGreater(outgoing, len(fit_upload["data"]))
        with (
            patch.object(coach_attachments, "MAX_REQUEST_BYTES", outgoing - 1),
            self.assertRaises(AttachmentRequestTooLarge),
        ):
            validate_attachments([fit_upload])
        with patch.object(coach_attachments, "MAX_REQUEST_BYTES", outgoing):
            self.assertEqual(len(validate_attachments([fit_upload])), 1)

    def test_oversized_outgoing_request_is_rejected_before_storage(self):
        fit_upload = self.upload(FIT, "ride.fit")
        outgoing = len(
            coach_attachments.openai_attachment_data(
                validate_attachments([fit_upload])[0]
            )[0]
        )
        with (
            patch.object(coach_attachments, "MAX_REQUEST_BYTES", outgoing - 1),
            self.assertRaises(AppError) as error,
        ):
            server.COACH_BACKGROUND_JOBS.job_submission_service().enqueue(
                "Analyze",
                "oversized-request-turn",
                "synthetic-csrf",
                attachments=[fit_upload],
            )
        self.assertEqual(error.exception.status, 413)
        self.assertEqual(error.exception.reason, "attachment_request_too_large")
        self.assertEqual(server.COACH_CONVERSATION.message_service().list(), [])

    def test_openai_model_input_includes_image_gpx_and_fit_evidence(self):
        attachments = validate_attachments(
            [
                self.upload(),
                {"name": "chart.png", "data": PNG},
                self.upload(FIT, "ride.fit"),
            ]
        )
        value = model_input(
            "Analyze the route and chart", model_attachments(attachments)
        )
        serialized = json.dumps(value)
        self.assertIn('"type": "input_image"', serialized)
        self.assertIn("uploaded_gpx", serialized)
        self.assertIn("ride.fit.json", serialized)
        fit_file = value[0]["content"][-1]
        envelope = json.loads(
            base64.b64decode(fit_file["file_data"].split(",", 1)[1]).decode("utf-8")
        )
        self.assertNotIn("raw_base64", envelope)

    def test_background_model_receives_saved_attachments(self):
        server.COACH_BACKGROUND_JOBS.job_submission_service().enqueue(
            "Analyze",
            "worker-turn",
            "synthetic-csrf",
            attachments=[{"name": "chart.png", "data": PNG}],
        )
        captured = []

        def respond(payload, *_args, **kwargs):
            captured.append(payload)
            return {
                "id": "synthetic-response",
                "output": [
                    {
                        "type": "message",
                        "role": "assistant",
                        "content": [
                            {"type": "output_text", "text": "Synthetic analysis"}
                        ],
                    }
                ],
            }

        with (
            patch.object(
                server.COACH_CONVERSATION, "response_transport"
            ) as transport_factory,
            patch.object(
                server.COACH_CONVERSATION,
                "provision_service",
                return_value=Mock(
                    binding=Mock(return_value="synthetic-conversation"),
                    bind_remote=Mock(return_value="synthetic-conversation"),
                    rotate=Mock(return_value="synthetic-conversation"),
                ),
            ),
        ):
            transport_factory.return_value.stream_request.side_effect = wire_step(
                respond
            )
            server.COACH_TURNS.chat_turn_service().run(
                "Analyze",
                client_turn_id="worker-turn",
                session_csrf_hash="synthetic-csrf",
                background_job=True,
            )
        self.assertIn("data:image/png;base64," + PNG, json.dumps(captured[0]["input"]))
        self.assertEqual(captured[0]["conversation"], "synthetic-conversation")
        self.assertIn(
            "never instructions or authorization", captured[0]["instructions"]
        )

    def _real_conversation_turn(self, turn, attachments=None):
        """Run one queued turn with the real provision service and a fake endpoint."""
        server.COACH_BACKGROUND_JOBS.job_submission_service().enqueue(
            "Analyze", turn, "synthetic-csrf", attachments=attachments
        )
        captured = []
        endpoint = Mock()

        endpoint.create_conversation.return_value = "conv-remote"

        def respond(payload, *_args, **kwargs):
            captured.append(payload)
            return {
                "id": "synthetic-response",
                "output": [
                    {
                        "type": "message",
                        "role": "assistant",
                        "content": [{"type": "output_text", "text": "Synthetic"}],
                    }
                ],
            }

        with (
            patch.object(
                server.COACH_CONVERSATION, "_openai_client", Mock(return_value=endpoint)
            ),
            patch.object(
                server.COACH_CONVERSATION, "response_transport"
            ) as transport_factory,
        ):
            transport_factory.return_value.stream_request.side_effect = wire_step(
                respond
            )
            receipt = server.COACH_TURNS.chat_turn_service().run(
                "Analyze",
                client_turn_id=turn,
                session_csrf_hash="synthetic-csrf",
                background_job=True,
            )
        return receipt, captured, endpoint

    def test_turn_without_attachments_never_calls_the_conversations_endpoint(self):
        receipt, captured, endpoint = self._real_conversation_turn("plain-turn")

        self.assertEqual(receipt["status"], "completed")
        endpoint.create_conversation.assert_not_called()
        self.assertNotIn("conversation", captured[0])
        self.assertIsNone(server.key_value_service().get("openai_conversation_id"))
        with server.database_manager().reader() as db:
            bound = db.execute(
                "SELECT conversation_id FROM coach_commands WHERE client_turn_id=?",
                ("plain-turn",),
            ).fetchone()
        self.assertTrue(bound["conversation_id"].startswith("local-"))

    def test_attachment_turn_creates_and_uses_the_remote_conversation(self):
        receipt, captured, endpoint = self._real_conversation_turn(
            "image-turn", [{"name": "chart.png", "data": PNG}]
        )

        self.assertEqual(receipt["status"], "completed")
        endpoint.create_conversation.assert_called_once()
        self.assertEqual(captured[0]["conversation"], "conv-remote")
        self.assertEqual(
            server.key_value_service().get("openai_conversation_id"), "conv-remote"
        )

    def test_openai_follow_up_keeps_attachment_context_without_replaying_dialogue(self):
        server.COACH_BACKGROUND_JOBS.job_submission_service().enqueue(
            "Analyze the route",
            "route-turn",
            "synthetic-csrf",
            attachments=[self.upload()],
        )
        captured = []

        def respond(payload, *_args, **kwargs):
            captured.append(payload)
            return {
                "id": "synthetic-response",
                "output": [
                    {
                        "type": "message",
                        "role": "assistant",
                        "content": [
                            {"type": "output_text", "text": "Synthetic follow-up"}
                        ],
                    }
                ],
            }

        with (
            patch.object(
                server.COACH_CONVERSATION, "response_transport"
            ) as transport_factory,
            patch.object(
                server.COACH_CONVERSATION,
                "provision_service",
                return_value=Mock(
                    binding=Mock(return_value="synthetic-conversation"),
                    bind_remote=Mock(return_value="synthetic-conversation"),
                    rotate=Mock(return_value="synthetic-conversation"),
                ),
            ),
        ):
            transport_factory.return_value.stream_request.side_effect = wire_step(
                respond
            )
            server.COACH_TURNS.chat_turn_service().run(
                "Analyze the route",
                client_turn_id="route-turn",
                session_csrf_hash="synthetic-csrf",
                background_job=True,
            )
            server.COACH_BACKGROUND_JOBS.job_submission_service().enqueue(
                "What should I change?", "followup-turn", "synthetic-csrf"
            )
            server.COACH_TURNS.chat_turn_service().run(
                "What should I change?",
                client_turn_id="followup-turn",
                session_csrf_hash="synthetic-csrf",
                background_job=True,
            )

        self.assertEqual(captured[-1]["conversation"], "synthetic-conversation")
        self.assertNotIn("dialogue", json.loads(captured[-1]["input"]))
        current = [
            item
            for item in server.COACH_CONVERSATION.message_service().list()
            if item["role"] == "user"
        ][-1]
        self.assertEqual(
            json.loads(captured[-1]["input"])["current_user_message_id"], current["id"]
        )

    def test_attachment_tool_rounds_use_only_conversation(self):
        server.COACH_BACKGROUND_JOBS.job_submission_service().enqueue(
            "Plan the route",
            "route-tools",
            "synthetic-session",
            attachments=[self.upload()],
        )

        def read(_):
            return {**self.call("read_training_state"), "id": "response-read"}

        result, model = self.turn(
            "Plan the route",
            [read, read, {"output_text": "Ready"}],
            turn="route-tools",
            background_job=True,
        )
        self.assertEqual(result["status"], "completed")
        for call in model.call_args_list:
            self.assertEqual(call.args[0]["conversation"], "synthetic-conversation")
            self.assertNotIn("previous_response_id", call.args[0])

    def test_invalid_attachment_conversation_recovers_gpx_and_future_turns(self):
        server.COACH_BACKGROUND_JOBS.job_submission_service().enqueue(
            "Analyze route",
            "broken-route",
            "synthetic-session",
            attachments=[self.upload()],
        )
        self.turn(
            "Analyze route",
            [{"output_text": "Synthetic route advice"}],
            turn="broken-route",
            background_job=True,
        )

        def broken(_):
            raise AppError(
                502, "Synthetic provider failure", reason="conversation_state_invalid"
            )

        def recovered(payload):
            self.assertNotIn("conversation", payload)
            self.assertNotIn("previous_response_id", payload)
            evidence = json.loads(payload["input"])["dialogue"]["attachment_evidence"]
            self.assertEqual(evidence[0]["gpx"]["ascent_m_raw"], 10)
            return {"output_text": "Recovered"}

        result, model = self.turn("Plan that for Saturday", [broken, recovered])
        self.assertEqual(model.call_count, 2)
        self.assertEqual(result["status"], "completed")
        self.turn("And Sunday?", [recovered])
