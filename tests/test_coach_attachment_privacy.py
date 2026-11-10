"""What an attachment reveals when it is sent to the AI provider."""

from __future__ import annotations

import base64
import json
import struct
import unittest
import zlib

from backend.coach.attachment_privacy import hidden_position_indexes
from backend.coach.attachments import model_input, validate_attachments
from backend.coach.image_metadata import strip_image_metadata

STEP_DEGREES = 0.0009  # about 100 m of latitude
POINTS = 40
HIDDEN = {*range(5), *range(35, 40)}
START = (52.0, 13.0)
SERIAL = 987654321
FRIENDLY_NAME = "SYNTHETIC-PERSON-NAME"


def _semicircles(degrees):
    return round(degrees * 2**31 / 180)


def _fit_bytes():
    def message(local, number, fields, rows):
        definition = bytes([0x40 | local, 0, 0]) + struct.pack("<H", number)
        definition += bytes([len(fields)]) + b"".join(bytes(f) for f in fields)
        return definition + b"".join(bytes([local]) + row for row in rows)

    name = FRIENDLY_NAME.encode().ljust(24, b"\0")
    payload = (
        message(0, 0, [(3, 4, 12)], [struct.pack("<I", SERIAL)])
        + message(1, 3, [(0, 24, 7), (4, 2, 4)], [name + struct.pack("<H", 725)])
        + message(2, 23, [(3, 4, 12)], [struct.pack("<I", SERIAL + 1)])
        + message(
            3,
            20,
            [(253, 4, 6), (0, 4, 5), (1, 4, 5), (3, 1, 2)],
            [
                struct.pack(
                    "<IiiB",
                    1_000_000 + index,
                    _semicircles(START[0] + index * STEP_DEGREES),
                    _semicircles(START[1]),
                    120 + index,
                )
                for index in range(POINTS)
            ],
        )
    )
    header = (
        bytes([12, 0x10])
        + struct.pack("<H", 0)
        + struct.pack("<I", len(payload))
        + b".FIT"
    )
    return header + payload


def _gpx_bytes():
    points = "".join(
        f'<trkpt lat="{START[0] + index * STEP_DEGREES:.6f}" lon="{START[1]}">'
        f"<ele>{100 + index}</ele><time>2026-05-01T08:00:{index:02d}Z</time>"
        f"<extensions><gpxtpx:TrackPointExtension><gpxtpx:hr>{120 + index}"
        "</gpxtpx:hr></gpxtpx:TrackPointExtension></extensions></trkpt>"
        for index in range(POINTS)
    )
    return (
        '<gpx xmlns="http://www.topografix.com/GPX/1/1" '
        'xmlns:gpxtpx="http://www.garmin.com/xmlschemas/TrackPointExtension/v1" '
        'creator="SYNTHETIC-DEVICE-MODEL"><metadata><author><name>SYNTHETIC-AUTHOR'
        "</name></author><desc>SYNTHETIC-DESCRIPTION</desc></metadata>"
        f"<trk><name>SYNTHETIC-HOME-LOOP</name><trkseg>{points}</trkseg></trk></gpx>"
    ).encode()


def _segment(marker, payload):
    return b"\xff" + bytes([marker]) + struct.pack(">H", len(payload) + 2) + payload


def _jpeg_bytes():
    return (
        b"\xff\xd8"
        + _segment(0xE0, b"JFIF\0\1\1\0\0\1\0\1\0\0")
        + _segment(0xE1, b"Exif\0\0SYNTHETIC-GPS-LATITUDE")
        + _segment(0xE1, b"http://ns.adobe.com/xap/1.0/\0SYNTHETIC-XMP")
        + _segment(0xFE, b"SYNTHETIC-COMMENT")
        + _segment(0xDA, b"\1\1\0\0?\0")
        + b"\x12\x34\x56"
        + b"\xff\xd9"
    )


def _png_chunk(kind, payload):
    crc = zlib.crc32(kind + payload)
    return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", crc)


def _png_bytes():
    header = struct.pack(">IIBBBBB", 1, 1, 8, 0, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", header)
        + _png_chunk(b"tEXt", b"Comment\0SYNTHETIC-GPS-TEXT")
        + _png_chunk(b"eXIf", b"SYNTHETIC-EXIF")
        + _png_chunk(b"IDAT", zlib.compress(b"\0\x80"))
        + _png_chunk(b"IEND", b"")
    )


def _webp_bytes():
    def chunk(kind, payload):
        return (
            kind
            + struct.pack("<I", len(payload))
            + payload
            + b"\0" * (len(payload) & 1)
        )

    flags = 0x08 | 0x04 | 0x20
    body = (
        b"WEBP"
        + chunk(b"VP8X", bytes([flags]) + b"\0\0\0" + b"\0\0\0\0\0\0")
        + chunk(b"EXIF", b"SYNTHETIC-EXIF-GPS")
        + chunk(b"XMP ", b"SYNTHETIC-XMP")
        + chunk(b"VP8L", b"\x2f\0\0\0\0")
    )
    return b"RIFF" + struct.pack("<I", len(body)) + body


def _upload(data, name):
    return {"name": name, "data": base64.b64encode(data).decode("ascii")}


def _sent_file(upload):
    """The file part of the request as the provider receives it."""
    attachments = validate_attachments([upload])
    parts = model_input("Analyze this", attachments)[0]["content"]
    body = json.dumps(parts)
    encoded = parts[-1]["file_data"].split(",", 1)[1]
    return body, json.loads(base64.b64decode(encoded)), attachments[0]


class TrackTrimTests(unittest.TestCase):
    def test_first_and_last_500_m_are_hidden(self):
        positions = [(52.0 + i * STEP_DEGREES, 13.0) for i in range(POINTS)]
        self.assertEqual(hidden_position_indexes(positions), HIDDEN)

    def test_short_track_is_hidden_completely(self):
        positions = [(52.0 + i * STEP_DEGREES, 13.0) for i in range(9)]
        self.assertEqual(hidden_position_indexes(positions), set(range(9)))

    def test_points_without_position_keep_their_slot(self):
        positions = [None, *[(52.0 + i * STEP_DEGREES, 13.0) for i in range(POINTS)]]
        self.assertEqual(hidden_position_indexes(positions), {i + 1 for i in HIDDEN})


class FitAttachmentTests(unittest.TestCase):
    def test_sends_all_records_without_original_file_device_or_user_data(self):
        upload = _upload(_fit_bytes(), "run.fit")
        body, document, attachment = _sent_file(upload)

        self.assertNotIn("raw_base64", body)
        self.assertNotIn(upload["data"], body)
        for secret in (str(SERIAL), str(SERIAL + 1), FRIENDLY_NAME, "72.5"):
            self.assertNotIn(secret, json.dumps(document))
        self.assertEqual(attachment["type"], "fit")
        table = document["records"]
        self.assertEqual(len(table["rows"]), POINTS)
        columns = table["columns"]
        self.assertEqual(
            [row[columns.index("heart_rate_bpm")] for row in table["rows"]],
            [120 + i for i in range(POINTS)],
        )

    def test_positions_of_first_and_last_500_m_are_removed(self):
        _, document, _ = _sent_file(_upload(_fit_bytes(), "run.fit"))
        columns = document["records"]["columns"]
        latitude = columns.index("latitude_deg")
        longitude = columns.index("longitude_deg")
        rows = document["records"]["rows"]

        for index, row in enumerate(rows):
            if index in HIDDEN:
                self.assertIsNone(row[latitude])
                self.assertIsNone(row[longitude])
            else:
                self.assertAlmostEqual(
                    row[latitude], START[0] + index * STEP_DEGREES, places=4
                )
                self.assertAlmostEqual(row[longitude], START[1], places=4)
        self.assertEqual(rows[0][columns.index("heart_rate_bpm")], 120)


class GpxAttachmentTests(unittest.TestCase):
    def test_sends_points_without_file_metadata(self):
        body, document, _ = _sent_file(_upload(_gpx_bytes(), "loop.gpx"))

        for secret in (
            "SYNTHETIC-DEVICE-MODEL",
            "SYNTHETIC-AUTHOR",
            "SYNTHETIC-DESCRIPTION",
            "SYNTHETIC-HOME-LOOP",
        ):
            self.assertNotIn(secret, body)
            self.assertNotIn(secret, json.dumps(document))
        self.assertEqual(len(document["points"]), POINTS)
        self.assertIn("hr", document["columns"])
        self.assertEqual(
            [point[document["columns"].index("hr")] for point in document["points"]],
            [120 + i for i in range(POINTS)],
        )

    def test_start_and_end_positions_are_removed_but_other_values_stay(self):
        _, document, attachment = _sent_file(_upload(_gpx_bytes(), "loop.gpx"))
        columns = document["columns"]
        for index, point in enumerate(document["points"]):
            located = point[columns.index("lat")] is not None
            self.assertEqual(located, index not in HIDDEN)
            self.assertEqual(point[columns.index("ele")], 100 + index)
        summary = attachment["summary"]
        shared = summary["sampled_coordinates_lat_lon_ele"]
        self.assertNotIn(
            [START[0], START[1], 100], [[p[0], p[1], p[2]] for p in shared]
        )
        self.assertAlmostEqual(
            summary["end"][0], START[0] + 34 * STEP_DEGREES, places=5
        )
        self.assertAlmostEqual(summary["distance_km"], 3.903, places=2)


class ImageMetadataTests(unittest.TestCase):
    def test_jpeg_loses_exif_xmp_and_comment_but_keeps_pixels(self):
        stripped = strip_image_metadata(_jpeg_bytes(), "image/jpeg")
        for secret in (b"Exif", b"SYNTHETIC", b"adobe"):
            self.assertNotIn(secret, stripped)
        self.assertIn(b"JFIF", stripped)
        self.assertTrue(stripped.endswith(b"\x12\x34\x56\xff\xd9"))

    def test_png_loses_text_and_exif_chunks(self):
        stripped = strip_image_metadata(_png_bytes(), "image/png")
        self.assertNotIn(b"SYNTHETIC", stripped)
        self.assertNotIn(b"tEXt", stripped)
        self.assertIn(b"IDAT", stripped)
        self.assertTrue(stripped.endswith(_png_chunk(b"IEND", b"")))

    def test_webp_loses_exif_and_xmp_chunks_and_flags(self):
        stripped = strip_image_metadata(_webp_bytes(), "image/webp")
        self.assertNotIn(b"SYNTHETIC", stripped)
        self.assertNotIn(b"EXIF", stripped)
        self.assertEqual(struct.unpack_from("<I", stripped, 4)[0], len(stripped) - 8)
        self.assertEqual(stripped[20], 0x20)
        self.assertIn(b"VP8L", stripped)

    def test_unparseable_image_is_rejected_not_passed_through(self):
        for data, mime in (
            (b"\xff\xd8\xff\xe1\x00\x40Exif", "image/jpeg"),
            (b"\x89PNG\r\n\x1a\n", "image/png"),
            (b"RIFF\x04\0\0\0WEBP", "image/webp"),
        ):
            with self.subTest(mime=mime), self.assertRaises(ValueError):
                strip_image_metadata(data, mime)
        with self.assertRaises(ValueError):
            validate_attachments([_upload(b"\xff\xd8\xff\xe1\x00\x40Exif", "p.jpg")])

    def test_request_carries_the_stripped_image_only(self):
        for data, name in (
            (_jpeg_bytes(), "photo.jpg"),
            (_png_bytes(), "photo.png"),
            (_webp_bytes(), "photo.webp"),
        ):
            with self.subTest(name=name):
                attachments = validate_attachments([_upload(data, name)])
                part = model_input("Look", attachments)[0]["content"][-1]
                sent = base64.b64decode(part["image_url"].split(",", 1)[1])
                self.assertNotIn(b"SYNTHETIC", sent)
                # The stored attachment keeps the athlete's original bytes.
                self.assertIn(b"SYNTHETIC", base64.b64decode(attachments[0]["data"]))


if __name__ == "__main__":
    unittest.main()
