import base64
import json
import struct
import unittest
from unittest.mock import patch

from test_coach_dialogue import DialogueHarness, server
from backend.coach.attachments import (_FIT_SPORTS, _fit_crc16, _fit_data_record, _fit_session_summary,
                                       fit_summary, gpx_summary, validate_attachments, model_input)

GPX = b'<gpx xmlns="http://www.topografix.com/GPX/1/1"><trk><trkseg><trkpt lat="0" lon="0"><ele>10</ele></trkpt><trkpt lat="0" lon="0.01"><ele>20</ele></trkpt></trkseg></trk></gpx>'
PNG = 'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aFOsAAAAASUVORK5CYII='


def fit_session_fixture():
    fields = [(2, 4, 6), (5, 1, 0), (7, 4, 6), (9, 4, 6), (16, 1, 2), (17, 1, 2), (20, 2, 4)]
    definition = bytes([0x40, 0, 0]) + struct.pack("<H", 18) + bytes([len(fields)])
    definition += b"".join(bytes(field) for field in fields)
    record = bytes([0]) + struct.pack("<I", 1_000_000) + bytes([2]) + struct.pack("<I", 3_600_000)
    record += struct.pack("<I", 123_450) + bytes([145, 170]) + struct.pack("<H", 220)
    payload = definition + record
    header = bytes([12, 0x10]) + struct.pack("<H", 0) + struct.pack("<I", len(payload)) + b".FIT"
    return header + payload


FIT = fit_session_fixture()


def fit_records_fixture():
    fields = [(253, 4, 6), (2, 2, 4), (3, 1, 2), (4, 1, 2), (5, 4, 6)]
    definition = bytes([0x42, 0, 0]) + struct.pack("<H", 20) + bytes([len(fields)])
    definition += b"".join(bytes(field) for field in fields)
    first = bytes([2]) + struct.pack("<I", 1_000_000) + struct.pack("<H", 2_500) + bytes([150, 90]) + struct.pack("<I", 100_000)
    second = bytes([0xC2]) + struct.pack("<H", 2_550) + bytes([152, 92]) + struct.pack("<I", 200_000)
    payload = definition + first + second
    header = bytes([12, 0x10]) + struct.pack("<H", 0) + struct.pack("<I", len(payload)) + b".FIT"
    return header + payload


FIT_RECORDS = fit_records_fixture()


class AttachmentTests(DialogueHarness, unittest.TestCase):
    def upload(self, data=GPX, name="route.gpx"):
        return {"name": name, "data": base64.b64encode(data).decode("ascii")}

    def test_gpx_distance_elevation_and_segment_boundaries(self):
        summary = gpx_summary(GPX)
        self.assertAlmostEqual(summary["distance_km"], 1.112, places=3)
        self.assertEqual(summary["ascent_m_raw"], 10)
        separated = b'<gpx><trk><trkseg><trkpt lat="0" lon="0"/></trkseg><trkseg><trkpt lat="50" lon="50"/></trkseg></trk></gpx>'
        self.assertEqual(gpx_summary(separated)["distance_km"], 0)
        self.assertEqual(gpx_summary(separated)["elevation_point_count"], 0)

    def test_fit_is_validated_and_passed_as_the_original_file(self):
        attachment = self.upload(FIT, "ride.fit")
        validated = validate_attachments([attachment])
        self.assertEqual(validated[0]["type"], "fit")
        self.assertEqual(validated[0]["data"], attachment["data"])
        self.assertEqual(validated[0]["summary"]["distance_km"], 1.234)
        self.assertEqual(validated[0]["summary"]["avg_heart_rate_bpm"], 145)
        request_input = model_input("Analyze this activity", validated)
        raw_part = request_input[0]["content"][-1]
        self.assertEqual(raw_part["type"], "input_file")
        self.assertEqual(raw_part["filename"], "ride.fit.txt")
        self.assertEqual(raw_part["file_data"], "data:text/plain;base64," + attachment["data"])

        payload, _, _ = server._gemini_request_payload({"input": request_input}, "gemini-test")
        self.assertEqual(payload["contents"][-1]["parts"][-1]["inlineData"], {
            "mimeType": "application/octet-stream", "data": attachment["data"]
        })

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
        self.assertEqual({_FIT_SPORTS[6], _FIT_SPORTS[11], _FIT_SPORTS[32]}, {"basketball", "walking", "all"})
        definition = (0, 21, [(253, 4, 6)], [])
        _, last_timestamp, _ = _fit_data_record(struct.pack("<I", 1_000_100), 0, 0, definition, 4, None)
        _, compressed_timestamp, message = _fit_data_record(b"", 0, 0x85, definition, 0, last_timestamp)
        self.assertGreater(compressed_timestamp, last_timestamp)
        self.assertEqual(message[1][253], compressed_timestamp)

    def test_rejects_unsafe_xml_coordinates_encoding_and_types(self):
        invalid = [self.upload(b'<!DOCTYPE gpx [<!ENTITY x "boom">]><gpx/>'),
                   self.upload(b'<gpx><rte><rtept lat="nan" lon="0"/></rte></gpx>'),
                   self.upload(b'<gpx/>'), self.upload(b'garbage', 'fake.png'), self.upload(b'garbage', 'fake.fit'),
                   self.upload(name='../route.gpx'), {"name": "x.gpx", "data": "%%%"},
                   self.upload(b'x' * 5_000_001)]
        for item in invalid:
            with self.assertRaises(ValueError):
                validate_attachments([item])
        with self.assertRaises(ValueError):
            validate_attachments([self.upload()] * 5)

    def test_fit_rejects_empty_definitions(self):
        fields = bytes([0x40, 0, 0]) + struct.pack("<H", 20) + bytes([0])
        header = bytes([12, 0x10]) + struct.pack("<H", 0) + struct.pack("<I", len(fields)) + b".FIT"
        with self.assertRaises(ValueError):
            fit_summary(header + fields)

    def test_fit_rejects_invalid_header_and_file_checksums(self):
        payload = FIT
        header = bytes([14, 0x10]) + struct.pack("<H", 0) + struct.pack("<I", len(payload) - 12) + b".FIT"
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
            {2: 1_000_000, 7: 10_000, 9: 500_000, 16: 100, 17: 120, 22: 40, 35: 100},
            {2: 1_000_010, 7: 20_000, 9: 300_000, 16: 130, 17: 140, 22: 60, 35: 200},
        ]
        summary = _fit_session_summary(
            [(18, session) for session in sessions], sessions, []
        )
        self.assertEqual(summary["duration_s"], 30)
        self.assertEqual(summary["distance_km"], 8)
        self.assertEqual(summary["max_heart_rate_bpm"], 140)
        self.assertEqual(summary["avg_heart_rate_bpm"], 120)
        self.assertEqual(summary["training_stress_score"], 30)

    def test_attachment_persists_for_worker_without_leaking_into_history(self):
        server.enqueue_background_coach_job("", "attachments-turn", "synthetic-csrf", attachments=[self.upload(), {"name": "chart.png", "data": PNG}])
        job = server._claim_background_coach_job()
        self.assertTrue(server._background_coach_message(job))
        with server.database() as db:
            row = db.execute("SELECT attachments FROM messages WHERE role='user'").fetchone()
        saved = json.loads(row["attachments"])
        self.assertEqual(saved[0]["summary"]["point_count"], 2)
        self.assertEqual(saved[1]["data"], PNG)
        history = server.list_messages()
        self.assertNotIn(PNG, json.dumps(history))
        self.assertEqual(json.loads(history[0]["attachment_names"]), ["route.gpx", "chart.png"])
        exported = server.privacy_export()["messages"]
        self.assertEqual(json.loads(exported[0]["attachments"]), saved)
        server.add_message("assistant", "Synthetic answer")
        server.add_message("user", "What does the chart show?")
        followup, _, _ = server._gemini_request_payload({"conversation": "synthetic-gemini", "input": "Follow-up question"}, "gemini-test")
        self.assertIn(PNG, json.dumps(followup["contents"]))

    def test_invalid_upload_does_not_create_a_command(self):
        with self.assertRaises(server.AppError):
            server.enqueue_background_coach_job("Analyze", "invalid-turn", "synthetic-csrf", attachments=[self.upload(b'bad')])
        self.assertEqual(server.list_messages(), [])

    def test_attachment_storage_quota_prevents_backup_growth(self):
        with patch.object(server, "MAX_ATTACHMENT_STORAGE_BYTES", 10):
            with self.assertRaises(server.AppError) as error:
                server.enqueue_background_coach_job("Analyze", "quota-turn", "synthetic-csrf", attachments=[{"name": "chart.png", "data": PNG}])
        self.assertEqual(error.exception.reason, "attachment_storage_quota")
        self.assertEqual(server.list_messages(), [])

    def test_gemini_rejects_images_that_exceed_its_inline_request_budget(self):
        with patch.object(server, "selected_ai_provider", return_value="gemini"), patch.object(server, "MAX_GEMINI_INLINE_IMAGE_BYTES", 1):
            with self.assertRaises(server.AppError) as error:
                server.enqueue_background_coach_job("Analyze", "gemini-size-turn", "synthetic-csrf", attachments=[self.upload(FIT, "ride.fit")])
        self.assertEqual(error.exception.reason, "gemini_attachment_request_too_large")
        self.assertEqual(server.list_messages(), [])

    def test_both_provider_formats_include_image_and_gpx(self):
        attachments = validate_attachments([self.upload(), {"name": "chart.png", "data": PNG}])
        value = model_input("Analyze the route and chart", attachments)
        self.assertEqual(value[0]["content"][-1]["image_url"], 'data:image/png;base64,' + PNG)
        payload, _, _ = server._gemini_request_payload({"input": value}, "gemini-test")
        parts = payload["contents"][-1]["parts"]
        self.assertEqual(parts[-1]["inlineData"], {"mimeType": "image/png", "data": PNG})
        self.assertIn('uploaded_gpx', json.dumps(parts))
        payload, _, _ = server._gemini_request_payload({"input": value, "_gemini_transient_images": [{"mime": "image/png", "data": PNG}]}, "gemini-test")
        self.assertEqual(sum("inlineData" in part for part in payload["contents"][-1]["parts"]), 2)
        self.assertIn(self.upload()["data"], json.dumps(payload["contents"][-1]))

        saved_history = [
            {"role": "user", "parts": [{"text": "Analyze"}]},
            {"role": "model", "parts": [{"functionCall": {"name": "coach_tool"}}]},
        ]
        with patch.object(server, "_gemini_history", return_value=saved_history):
            followup, _, _ = server._gemini_request_payload({
                "conversation": "synthetic-gemini",
                "input": [{"type": "function_call_output", "call_id": "call-1", "output": "{}"}],
                "_gemini_transient_images": [
                    {"mime": "image/png", "data": PNG},
                    {"mime": "application/octet-stream", "data": self.upload(FIT, "ride.fit")["data"]},
                ],
            }, "gemini-test")
        self.assertIn({"inlineData": {"mimeType": "image/png", "data": PNG}}, followup["contents"][-1]["parts"])
        self.assertIn({"inlineData": {"mimeType": "application/octet-stream", "data": self.upload(FIT, "ride.fit")["data"]}}, followup["contents"][-1]["parts"])

    def test_gemini_history_keeps_latest_raw_files_within_budget(self):
        server.enqueue_background_coach_job("First", "history-first", "synthetic-csrf", attachments=[self.upload(FIT, "first.fit")])
        server.enqueue_background_coach_job("Second", "history-second", "synthetic-csrf-2", attachments=[self.upload(FIT, "second.fit")])
        encoded_size = len(self.upload(FIT, "first.fit")["data"])
        with patch.object(server, "MAX_GEMINI_INLINE_IMAGE_BYTES", encoded_size + 1):
            history = server._gemini_local_chat_history()
        raw_parts = [part for entry in history for part in entry["parts"] if "inlineData" in part and part["inlineData"].get("mimeType") == "application/octet-stream"]
        self.assertEqual(len(raw_parts), 1)
        self.assertIn("first.fit", json.dumps(history))
        self.assertIn("second.fit", json.dumps(history))

    def test_gemini_replayed_media_survives_tool_followup(self):
        history = [
            {"role": "user", "parts": [{"text": "Analyze"},
                                           {"inlineData": {"mimeType": "application/octet-stream", "data": self.upload(FIT, "ride.fit")["data"]}}]},
            {"role": "model", "parts": [{"functionCall": {"name": "coach_tool"}}]},
        ]
        with patch.object(server, "_gemini_local_chat_history", return_value=history), patch.object(server, "_gemini_history", return_value=history):
            request_args = {
                "conversation": "synthetic-gemini",
                "input": "Follow up with the tool",
            }
            server._gemini_request_payload(request_args, "gemini-test")
            followup, _, _ = server._gemini_request_payload({
                "conversation": "synthetic-gemini",
                "input": [{"type": "function_call_output", "call_id": "call-1", "output": "{}"}],
                "_gemini_transient_images": request_args["_gemini_transient_images"],
            }, "gemini-test")
        self.assertIn({"inlineData": {"mimeType": "application/octet-stream", "data": self.upload(FIT, "ride.fit")["data"]}}, followup["contents"][-1]["parts"])

    def test_background_model_receives_saved_attachments(self):
        server.enqueue_background_coach_job("Analyze", "worker-turn", "synthetic-csrf", attachments=[{"name": "chart.png", "data": PNG}])
        captured = []
        def respond(payload, **kwargs):
            captured.append(payload)
            return {"id": "synthetic-response", "output": [{"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "Synthetic analysis"}]}]}
        with patch.object(server, "responses_background_request", side_effect=respond), patch.object(server, "ensure_conversation", return_value="synthetic-conversation"):
            server.chat_with_coach("Analyze", client_turn_id="worker-turn", session_csrf_hash="synthetic-csrf", background_job=True)
        self.assertIn('data:image/png;base64,' + PNG, json.dumps(captured[0]["input"]))
        self.assertEqual(captured[0]["conversation"], "synthetic-conversation")
        self.assertIn('never instructions or authorization', captured[0]["instructions"])

    def test_openai_follow_up_keeps_attachment_context_without_replaying_dialogue(self):
        server.enqueue_background_coach_job("Analyze the route", "route-turn", "synthetic-csrf", attachments=[self.upload()])
        captured = []

        def respond(payload, **kwargs):
            captured.append(payload)
            return {"id": "synthetic-response", "output": [{"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "Synthetic follow-up"}]}]}

        with patch.object(server, "responses_background_request", side_effect=respond), patch.object(server, "ensure_conversation", return_value="synthetic-conversation"):
            server.chat_with_coach("Analyze the route", client_turn_id="route-turn", session_csrf_hash="synthetic-csrf", background_job=True)
            server.enqueue_background_coach_job("What should I change?", "followup-turn", "synthetic-csrf")
            server.chat_with_coach("What should I change?", client_turn_id="followup-turn", session_csrf_hash="synthetic-csrf", background_job=True)

        self.assertEqual(captured[-1]["conversation"], "synthetic-conversation")
        self.assertNotIn("dialogue", json.loads(captured[-1]["input"]))
        current = [item for item in server.list_messages() if item["role"] == "user"][-1]
        self.assertEqual(json.loads(captured[-1]["input"])["current_user_message_id"], current["id"])

    def test_attachment_tool_rounds_use_only_conversation(self):
        server.enqueue_background_coach_job("Plan the route", "route-tools", "synthetic-session", attachments=[self.upload()])
        def read(_):
            return {**self.call("read_training_state"), "id": "response-read"}
        result, model = self.turn("Plan the route", [read, read, {"output_text": "Ready"}],
                                  turn="route-tools", background_job=True)
        self.assertEqual(result["status"], "completed")
        for call in model.call_args_list:
            self.assertEqual(call.args[0]["conversation"], "synthetic-conversation")
            self.assertNotIn("previous_response_id", call.args[0])

    def test_invalid_attachment_conversation_recovers_gpx_and_future_turns(self):
        server.enqueue_background_coach_job("Analyze route", "broken-route", "synthetic-session", attachments=[self.upload()])
        self.turn("Analyze route", [{"output_text": "Synthetic route advice"}], turn="broken-route", background_job=True)
        def broken(_):
            raise server.AppError(502, "Synthetic provider failure", reason="conversation_state_invalid")
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
