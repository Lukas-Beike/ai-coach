"""Tests for the stdlib FIT decoder in backend.providers.fit_file.

Every FIT file is built here from struct and an independent bitwise CRC, so no
binary fixtures are read and the table-driven decoder is checked against a
second implementation of the FIT checksum.
"""

import ast
import random
import struct
import unittest
from pathlib import Path
from unittest import mock

from backend.providers import fit_file
from backend.providers.fit_file import (
    _fit_crc16,
    fit_field,
    fit_messages,
    fit_metric,
    fit_scaled,
    fit_timestamp_iso,
)

ENUM = 0x00
SINT8 = 0x01
UINT8 = 0x02
UINT16 = 0x84
UINT32 = 0x86

_FORMATS = {
    0: "B",
    1: "b",
    2: "B",
    3: "h",
    4: "H",
    5: "i",
    6: "I",
    8: "f",
    9: "d",
    10: "B",
    11: "H",
    12: "I",
    14: "q",
    15: "Q",
    16: "Q",
}
# FIT SDK invalid values per base type, as written by the builder for absent fields.
_INVALID = {
    0: 0xFF,
    1: 0x7F,
    2: 0xFF,
    3: 0x7FFF,
    4: 0xFFFF,
    5: 0x7FFFFFFF,
    6: 0xFFFFFFFF,
}


def crc16_reference(data: bytes) -> int:
    """Bitwise CRC-16 with the FIT polynomial, independent of the nibble table."""
    crc = 0
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    return crc


class FitBuilder:
    """Builds little-endian FIT files; each field is packed by its base type."""

    def __init__(self):
        self._body = bytearray()
        self._definitions = {}

    def define(self, local, global_number, fields):
        """Add a definition; ``fields`` is a list of (field number, base type)."""
        self._definitions[local] = fields
        self._body += struct.pack(
            "<BBBHB", 0x40 | local, 0, 0, global_number, len(fields)
        )
        for number, base_type in fields:
            size = struct.calcsize("<" + _FORMATS[base_type & 0x1F])
            self._body += struct.pack("<BBB", number, size, base_type)
        return self

    def data(self, local, values, *, time_offset=None):
        """Add one data record. Absent fields are written as FIT invalid values.

        With ``time_offset`` the record uses a compressed timestamp header and
        field 253 is omitted from the record, as the FIT protocol requires.
        """
        fields = self._definitions[local]
        if time_offset is None:
            header = local
            items = fields
        else:
            header = 0x80 | (local << 5) | (time_offset & 0x1F)
            items = [field for field in fields if field[0] != 253]
        self._body.append(header)
        for number, base_type in items:
            value = values.get(number, _INVALID.get(base_type & 0x1F))
            self._body += struct.pack("<" + _FORMATS[base_type & 0x1F], value)
        return self

    def raw(self, data):
        self._body += data
        return self

    def build(self, *, header_size=14, file_crc=True):
        header = struct.pack("<BBHI", header_size, 0x20, 2132, len(self._body))
        header += b".FIT"
        if header_size == 14:
            header += struct.pack("<H", crc16_reference(header))
        payload = header + bytes(self._body)
        if file_crc:
            payload += struct.pack("<H", crc16_reference(payload))
        return payload


def refit_crcs(data: bytes) -> bytes:
    """Return a 14-byte-header file whose header and file CRCs match its body."""
    body = data[14:-2]
    header = struct.pack("<BBHI", 14, 0x20, 2132, len(body)) + b".FIT"
    header += struct.pack("<H", crc16_reference(header))
    payload = header + body
    return payload + struct.pack("<H", crc16_reference(payload))


def _sample() -> FitBuilder:
    return (
        FitBuilder()
        .define(0, 20, [(253, UINT32), (3, UINT8), (4, UINT8)])
        .data(0, {253: 1000, 3: 120, 4: 80})
        .data(0, {253: 1001, 3: 122, 4: 81})
    )


class FitFileFramingTests(unittest.TestCase):
    def test_valid_file_decodes_definitions_and_records(self):
        self.assertEqual(
            fit_messages(_sample().build()),
            [
                (20, {253: 1000, 3: 120, 4: 80}),
                (20, {253: 1001, 3: 122, 4: 81}),
            ],
        )

    def test_twelve_byte_header_has_no_header_crc(self):
        self.assertEqual(
            len(fit_messages(_sample().build(header_size=12))),
            2,
        )

    def test_header_crc_mismatch_is_rejected(self):
        data = bytearray(_sample().build())
        data[12] ^= 0xFF
        with self.assertRaisesRegex(ValueError, "Invalid FIT header CRC"):
            fit_messages(bytes(data))

    def test_file_crc_mismatch_is_rejected(self):
        data = bytearray(_sample().build())
        data[-3] ^= 0x01
        with self.assertRaisesRegex(ValueError, r"Invalid FIT file CRC$"):
            fit_messages(bytes(data))

    def test_trailer_must_be_absent_or_a_two_byte_crc(self):
        data = _sample().build(file_crc=False) + b"\x00"
        with self.assertRaisesRegex(ValueError, "Invalid FIT file CRC length"):
            fit_messages(data)

    def test_truncated_file_is_rejected(self):
        data = _sample().build(file_crc=False)[:-3]
        with self.assertRaisesRegex(ValueError, "Truncated FIT data"):
            fit_messages(data)

    def test_truncated_data_record_is_rejected(self):
        builder = FitBuilder().define(0, 20, [(253, UINT32), (3, UINT8)])
        builder.raw(bytes([0x00, 0x01, 0x00]))  # five bytes needed, two present
        with self.assertRaisesRegex(ValueError, "Truncated FIT data record"):
            fit_messages(builder.build())

    def test_unsupported_header_signature_and_size_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "Invalid FIT header"):
            fit_messages(b"\x0c" + bytes(7) + b"NOPE" + bytes(4))
        header = struct.pack("<BBHI", 13, 0x20, 2132, 0) + b".FIT" + b"\x00"
        with self.assertRaisesRegex(ValueError, "Invalid FIT header size"):
            fit_messages(header + struct.pack("<H", crc16_reference(header)))

    def test_unknown_base_type_is_rejected(self):
        # One field whose base type 0x11 is not in the FIT profile.
        builder = FitBuilder().raw(bytes([0x40, 0, 0, 20, 0, 1, 3, 1, 0x11]))
        with self.assertRaisesRegex(ValueError, "Unsupported FIT base type"):
            fit_messages(builder.build())

    def test_field_width_not_matching_its_base_type_is_kept_as_bytes(self):
        # Field 200 is a uint16 declared three bytes wide.
        definition = bytes(
            [0x40, 0, 0, 20, 0, 3, 253, 4, 0x86, 3, 1, 0x02, 200, 3, 0x84]
        )
        record = bytes([0]) + struct.pack("<I", 1000) + bytes([120, 1, 2, 3])
        builder = FitBuilder().raw(definition + record)
        self.assertEqual(
            fit_messages(builder.build()),
            [(20, {253: 1000, 3: 120, 200: b"\x01\x02\x03"})],
        )

    def test_message_count_is_bounded(self):
        builder = FitBuilder().define(0, 20, [(3, UINT8)])
        for value in range(3):
            builder.data(0, {3: value})
        with (
            mock.patch.object(fit_file, "MAX_FIT_MESSAGES", 2),
            self.assertRaisesRegex(ValueError, "Too many FIT records"),
        ):
            fit_messages(builder.build())

    def test_table_crc_matches_the_bitwise_reference(self):
        rng = random.Random(1989)
        for length in (0, 1, 2, 12, 14, 255):
            payload = bytes(rng.randrange(256) for _ in range(length))
            self.assertEqual(_fit_crc16(payload), crc16_reference(payload))


class FitFileValueTests(unittest.TestCase):
    def test_compressed_timestamps_restore_the_last_full_timestamp(self):
        builder = FitBuilder().define(0, 20, [(253, UINT32), (3, UINT8)])
        builder.data(0, {253: 1030, 3: 100})  # 1030 & 31 == 6
        builder.data(0, {3: 101}, time_offset=3)  # wraps to 1059
        builder.data(0, {3: 102}, time_offset=5)  # 1059 & 31 == 3, so +2 to 1061
        self.assertEqual(
            fit_messages(builder.build()),
            [
                (20, {253: 1030, 3: 100}),
                (20, {253: 1059, 3: 101}),
                (20, {253: 1061, 3: 102}),
            ],
        )

    def test_invalid_sentinels_decode_to_none(self):
        builder = FitBuilder().define(
            0, 20, [(3, UINT8), (4, SINT8), (5, UINT16), (6, UINT32), (7, ENUM)]
        )
        builder.data(0, {3: 0xFF, 4: 0x7F, 5: 0xFFFF, 6: 0xFFFFFFFF, 7: 0xFF})
        builder.data(0, {3: 0, 4: -5, 5: 0, 6: 0, 7: 0})
        self.assertEqual(
            fit_messages(builder.build()),
            [
                (20, {3: None, 4: None, 5: None, 6: None, 7: None}),
                (20, {3: 0, 4: -5, 5: 0, 6: 0, 7: 0}),
            ],
        )

    def test_fit_field_scales_one_message(self):
        self.assertEqual(fit_field({5: 1234}, 20, 5), 12.34)
        self.assertEqual(fit_field({2: 2550}, 20, 2), 10.0)
        self.assertEqual(fit_field({9: 1500}, 19, 9), 15.0)
        self.assertEqual(fit_field({3: 120}, 20, 3), 120.0)
        self.assertIsNone(fit_field({}, 20, 5))
        self.assertIsNone(fit_field({5: "12"}, 20, 5))
        self.assertIsNone(fit_field({5: float("nan")}, 20, 5))

    def test_fit_field_prefers_enhanced_speed_and_falls_back_on_invalid(self):
        self.assertEqual(fit_field({73: 1500, 6: 9000}, 20, 6), 1.5)
        self.assertEqual(fit_field({73: None, 6: 2000}, 20, 6), 2.0)
        self.assertEqual(fit_field({6: 2000}, 20, 6), 2.0)

    def test_lap_max_speed_prefers_the_enhanced_field(self):
        self.assertEqual(fit_field({111: 4500, 14: 9000}, 19, 14), 4.5)
        self.assertEqual(fit_field({111: None, 14: 4000}, 19, 14), 4.0)
        self.assertEqual(fit_field({14: 4000}, 19, 14), 4.0)

    def test_enhanced_field_sentinel_falls_back_to_base_end_to_end(self):
        builder = FitBuilder().define(0, 20, [(73, UINT32), (6, UINT16)])
        builder.data(0, {73: 1500, 6: 9000})
        builder.data(0, {6: 2000})  # enhanced speed absent, so the sentinel is used
        messages = fit_messages(builder.build())
        self.assertEqual([fit_field(f, 20, 6) for _, f in messages], [1.5, 2.0])

    def test_fit_scaled_and_fit_metric_keep_message_order(self):
        messages = [(20, {5: 100}), (19, {9: 200}), (20, {5: 250}), (20, {3: 99})]
        self.assertEqual(fit_scaled(messages, 20, 5), [1.0, 2.5])
        self.assertEqual(fit_metric(messages, 20, 5), [100, 250])
        self.assertEqual(fit_metric(messages, 20, 3), [99])
        self.assertEqual(fit_scaled(messages, 19, 9), [2.0])

    def test_fit_timestamp_iso_uses_the_fit_epoch(self):
        self.assertEqual(fit_timestamp_iso(0), "1989-12-31T00:00:00Z")
        self.assertEqual(fit_timestamp_iso(86_400), "1990-01-01T00:00:00Z")
        self.assertIsNone(fit_timestamp_iso(-1))
        self.assertIsNone(fit_timestamp_iso(float("nan")))
        self.assertIsNone(fit_timestamp_iso("0"))
        self.assertIsNone(fit_timestamp_iso(10**30))


class FitFileRobustnessTests(unittest.TestCase):
    def test_decoder_module_has_no_application_imports(self):
        tree = ast.parse(Path(fit_file.__file__).read_text(encoding="utf-8"))
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)
        self.assertEqual([name for name in imported if name.startswith("backend")], [])

    def test_random_and_mutated_inputs_raise_only_value_error(self):
        rng = random.Random(20261019)
        valid = _sample().build()
        cases = [
            bytes(rng.randrange(256) for _ in range(rng.randrange(0, 80)))
            for _ in range(300)
        ]
        for _ in range(300):
            mutated = bytearray(valid)
            for _ in range(rng.randrange(1, 4)):
                mutated[rng.randrange(14, len(mutated) - 2)] = rng.randrange(256)
            cases.append(bytes(mutated))
            cases.append(refit_crcs(bytes(mutated)))
        for data in cases:
            try:
                fit_messages(data)
            except ValueError:
                continue


if __name__ == "__main__":
    unittest.main()
