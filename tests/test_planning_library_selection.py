"""Regression tests for pure workout-library bulk selection semantics."""

import hashlib
import unittest
import uuid

from backend.errors import AppError
from backend.planning.library import (
    LIBRARY_BULK_MAX_ENTRIES,
    PAYLOAD_HASH_PATTERN,
    library_bulk_request_entries,
    library_payload_hash,
)


class LibraryBulkRequestEntriesTests(unittest.TestCase):
    def setUp(self):
        self.first_id = str(uuid.UUID("12345678-1234-5678-1234-567812345678"))
        self.second_id = str(uuid.UUID("87654321-4321-8765-4321-876543218765"))
        self.payload_hash = "a" * 64

    def assert_app_error(self, entries, message, **kwargs):
        with self.assertRaises(AppError) as error:
            library_bulk_request_entries(entries, **kwargs)
        self.assertEqual(error.exception.status, 400)
        self.assertEqual(error.exception.message, message)

    def test_public_constants_and_default_limit(self):
        self.assertEqual(PAYLOAD_HASH_PATTERN, r"[0-9a-f]{64}")
        self.assertEqual(LIBRARY_BULK_MAX_ENTRIES, 100)
        entries = [
            {"library_workout_id": str(uuid.uuid4())}
            for _ in range(LIBRARY_BULK_MAX_ENTRIES)
        ]
        self.assertEqual(len(library_bulk_request_entries(entries)), 100)

    def test_empty_and_non_list_selections_are_rejected(self):
        message = "Mindestens eine Bibliothekseinheit muss ausgewählt werden."
        for entries in (None, (), {}, []):
            with self.subTest(entries=entries):
                self.assert_app_error(entries, message)

    def test_maximum_is_inclusive_and_overflow_is_rejected(self):
        entries = [
            {"library_workout_id": self.first_id},
            {"library_workout_id": self.second_id},
        ]
        self.assertEqual(len(library_bulk_request_entries(entries, max_entries=2)), 2)
        self.assert_app_error(
            entries + [{"library_workout_id": str(uuid.uuid4())}],
            "Es können höchstens 2 Bibliothekseinheiten gleichzeitig ausgewählt werden.",
            max_entries=2,
        )

    def test_entries_are_normalized_and_keep_input_order(self):
        entries = [
            {"id": "{" + self.second_id.upper() + "}", "date": " 2026-09-20 "},
            {
                "library_workout_id": self.first_id.upper(),
                "expected_payload_hash": self.payload_hash.upper(),
            },
        ]
        self.assertEqual(
            library_bulk_request_entries(entries),
            [
                {"library_workout_id": self.second_id, "date": "2026-09-20"},
                {
                    "library_workout_id": self.first_id,
                    "expected_payload_hash": self.payload_hash,
                },
            ],
        )

    def test_each_selection_must_be_an_object_with_a_valid_uuid(self):
        self.assert_app_error([None], "Jede Bulk-Auswahl muss ein Objekt sein.")
        self.assert_app_error(
            [{"library_workout_id": "not-a-uuid"}],
            "Ungültige Bibliothekseinheiten-ID in der Auswahl.",
        )

    def test_duplicate_ids_are_detected_after_uuid_canonicalization(self):
        self.assert_app_error(
            [
                {"library_workout_id": self.first_id},
                {"id": self.first_id.upper()},
            ],
            "Eine Bibliothekseinheit darf nur einmal ausgewählt werden.",
        )

    def test_optional_date_uses_iso_parser_and_keeps_legacy_truncation(self):
        for value in (
            "2026-02-30",
            "2026-9-20",
            "2026-09-20T12:30:00",
            "2026-09-20T00:00:00x",
            "",
        ):
            with self.subTest(value=value):
                self.assert_app_error(
                    [{"id": self.first_id, "date": value}],
                    "Das Bulk-Datum muss das Format JJJJ-MM-TT haben.",
                )
        self.assertEqual(
            library_bulk_request_entries([{"id": self.first_id}]),
            [{"library_workout_id": self.first_id}],
        )
        self.assertEqual(
            library_bulk_request_entries([{"id": self.first_id, "date": "20260920"}]),
            [{"library_workout_id": self.first_id, "date": "20260920"}],
        )

    def test_optional_hash_is_validated_and_canonicalized(self):
        self.assertEqual(
            library_bulk_request_entries(
                [
                    {
                        "id": self.first_id,
                        "expected_payload_hash": self.payload_hash.upper(),
                    }
                ]
            ),
            [
                {
                    "library_workout_id": self.first_id,
                    "expected_payload_hash": self.payload_hash,
                }
            ],
        )
        self.assert_app_error(
            [{"id": self.first_id, "expected_payload_hash": "g" * 64}],
            "Ungültiger Payload-Hash in der Bulk-Auswahl.",
        )
        self.assert_app_error(
            [{"id": self.first_id, "expected_payload_hash": "a" * 63}],
            "Ungültiger Payload-Hash in der Bulk-Auswahl.",
        )

    def test_required_hash_rejects_missing_or_malformed_hash(self):
        message = "Die Bulk-Aktion benötigt aktuelle Payload-Hashes."
        for entry in (
            {"id": self.first_id},
            {"id": self.first_id, "expected_payload_hash": ""},
            {"id": self.first_id, "expected_payload_hash": "z" * 64},
            {"id": self.first_id, "expected_payload_hash": "a" * 63},
        ):
            with self.subTest(entry=entry):
                self.assert_app_error([entry], message, require_hash=True)
        self.assertEqual(
            library_bulk_request_entries(
                [
                    {
                        "id": self.first_id,
                        "expected_payload_hash": self.payload_hash.upper(),
                    }
                ],
                require_hash=True,
            )[0]["expected_payload_hash"],
            self.payload_hash,
        )

    def test_input_is_not_mutated_and_unknown_fields_are_not_copied(self):
        entries = [
            {
                "id": self.first_id,
                "date": "2026-09-20",
                "expected_payload_hash": self.payload_hash.upper(),
                "extra": {"nested": [1, 2]},
            }
        ]
        before = [{**entries[0], "extra": {"nested": [1, 2]}}]
        result = library_bulk_request_entries(entries)
        self.assertEqual(entries, before)
        self.assertNotIn("extra", result[0])


class LibraryPayloadHashTests(unittest.TestCase):
    def test_hashes_string_value_without_json_normalization(self):
        left = '{"a":1}'
        right = '{ "a": 1 }'
        self.assertEqual(
            library_payload_hash(left),
            hashlib.sha256(left.encode("utf-8")).hexdigest(),
        )
        self.assertNotEqual(library_payload_hash(left), library_payload_hash(right))
        raw_mapping = {"a": 1}
        self.assertEqual(
            library_payload_hash(raw_mapping),
            hashlib.sha256(str(raw_mapping).encode("utf-8")).hexdigest(),
        )

    def test_falsey_payloads_hash_the_empty_string(self):
        empty_hash = hashlib.sha256(b"").hexdigest()
        for payload in (None, "", 0, False):
            with self.subTest(payload=payload):
                self.assertEqual(library_payload_hash(payload), empty_hash)


if __name__ == "__main__":
    unittest.main()
