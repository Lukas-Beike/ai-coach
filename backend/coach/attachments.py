"""Bounded, untrusted Coach attachments; no filesystem or network access."""
import base64
import binascii
from datetime import datetime, timedelta, timezone
import json
import math
import struct
import xml.etree.ElementTree as ET

MAX_FILE_BYTES = 5_000_000
MAX_FILES = 4
MAX_REQUEST_BYTES = 28_000_000
# Gemini accepts at most 20 MB per inline request.  Leave room for the route
# summary, instructions and the surrounding JSON framing.
MAX_GEMINI_INLINE_IMAGE_BYTES = 16_000_000
# Keep encrypted database backups usable even when many turns contain images.
# This leaves headroom below the application's 100 MB backup limit.
# Keep room for provider conversation copies and SQLite page overhead inside
# the existing 100 MB encrypted-backup limit.
MAX_ATTACHMENT_STORAGE_BYTES = 40_000_000
FIT_SIGNATURE = b".FIT"
FIT_EPOCH = datetime(1989, 12, 31, tzinfo=timezone.utc)

# FIT base types used by the profile.  Unknown fields are still skipped safely,
# but an unknown base type makes the file structurally ambiguous and is rejected.
_FIT_BASE_TYPE_SIZES = {
    0: 1, 1: 1, 2: 1, 3: 2, 4: 2, 5: 4, 6: 4, 7: 1, 8: 4,
    9: 8, 10: 1, 11: 2, 12: 4, 13: 1, 14: 8, 15: 8, 16: 8,
}
_FIT_FIELD_SCALES = {
    # record message
    (20, 0): ("timestamp", 1, 0), (20, 1): ("position_lat", 1, 0),
    (20, 2): ("position_long", 1, 0), (20, 3): ("altitude_m", 5, -500),
    (20, 4): ("heart_rate_bpm", 1, 0), (20, 5): ("cadence_rpm", 1, 0),
    (20, 6): ("distance_m", 100, 0), (20, 7): ("speed_m_s", 1000, 0),
    (20, 13): ("temperature_c", 1, 0),
    # session message
    (18, 2): ("timestamp", 1, 0), (18, 7): ("elapsed_time_s", 1000, 0),
    (18, 8): ("timer_time_s", 1000, 0), (18, 9): ("distance_m", 100, 0),
    (18, 14): ("avg_speed_m_s", 1000, 0), (18, 15): ("max_speed_m_s", 1000, 0),
    (18, 16): ("avg_heart_rate_bpm", 1, 0), (18, 17): ("max_heart_rate_bpm", 1, 0),
    (18, 18): ("avg_cadence_rpm", 1, 0), (18, 19): ("max_cadence_rpm", 1, 0),
    (18, 20): ("avg_power_w", 1, 0), (18, 21): ("max_power_w", 1, 0),
    (18, 22): ("total_ascent_m", 1, 0), (18, 23): ("total_descent_m", 1, 0),
    (18, 34): ("normalized_power_w", 1, 0), (18, 35): ("training_stress_score", 10, 0),
    (18, 36): ("intensity_factor", 1000, 0),
}
_FIT_SPORTS = {
    0: "generic", 1: "running", 2: "cycling", 3: "transition", 4: "fitness_equipment",
    5: "swimming", 6: "walking", 7: "sedentary", 8: "all", 9: "ultra_run",
}


def _fit_value(raw, base_type, architecture):
    """Decode one bounded FIT field, returning None for FIT invalid values."""
    type_num = base_type & 0x1F
    size = _FIT_BASE_TYPE_SIZES.get(type_num)
    if size is None:
        raise ValueError("Unsupported FIT base type")
    if type_num == 7:
        return raw.rstrip(b"\x00").decode("utf-8", "replace")
    if type_num == 13:
        return raw
    if len(raw) % size:
        raise ValueError("Invalid FIT field size")
    endian = "<" if architecture == 0 else ">"
    formats = {0: "B", 1: "b", 2: "B", 3: "h", 4: "H", 5: "i", 6: "I", 8: "f", 9: "d", 10: "B", 11: "H", 12: "I", 14: "q", 15: "Q", 16: "Q"}
    fmt = formats.get(type_num)
    if not fmt:
        raise ValueError("Unsupported FIT base type")
    values = [struct.unpack(endian + fmt, raw[index:index + size])[0] for index in range(0, len(raw), size)]
    invalid = {
        0: 0xFF, 1: -0x80, 2: 0xFF, 3: -0x8000, 4: 0xFFFF,
        5: -0x80000000, 6: 0xFFFFFFFF, 8: float("nan"), 9: float("nan"),
        10: 0, 11: 0, 12: 0, 14: -0x8000000000000000,
        15: 0xFFFFFFFFFFFFFFFF, 16: 0xFFFFFFFFFFFFFFFF,
    }.get(type_num)
    def usable(value):
        if invalid is None:
            return value
        if isinstance(invalid, float) and math.isnan(invalid):
            return None if isinstance(value, float) and math.isnan(value) else value
        return None if value == invalid else value

    filtered = [usable(value) for value in values]
    if len(filtered) == 1:
        return filtered[0]
    return filtered


def _fit_messages(data):
    """Read FIT definitions and data records without trusting provider bytes."""
    if len(data) < 12 or data[8:12] != FIT_SIGNATURE:
        raise ValueError("Invalid FIT header")
    header_size = data[0]
    if header_size < 12 or header_size > len(data):
        raise ValueError("Invalid FIT header size")
    data_size = struct.unpack_from("<I", data, 4)[0]
    data_end = header_size + data_size
    if data_end > len(data):
        raise ValueError("Truncated FIT data")
    definitions = {}
    messages = []
    offset = header_size
    last_timestamp = None
    while offset < data_end:
        record_header = data[offset]
        offset += 1
        if record_header & 0x80:
            local_number = record_header & 0x0F
            if offset + 5 > data_end:
                raise ValueError("Truncated FIT definition")
            architecture = data[offset + 1]
            if architecture not in (0, 1):
                raise ValueError("Invalid FIT architecture")
            endian = "<" if architecture == 0 else ">"
            global_number = struct.unpack_from(endian + "H", data, offset + 2)[0]
            field_count = data[offset + 4]
            offset += 5
            fields = []
            for _ in range(field_count):
                if offset + 3 > data_end:
                    raise ValueError("Truncated FIT field definition")
                number, size, base_type = data[offset:offset + 3]
                if base_type & 0x1F not in _FIT_BASE_TYPE_SIZES:
                    raise ValueError("Unsupported FIT base type")
                fields.append((number, size, base_type))
                offset += 3
            developer_fields = []
            if record_header & 0x20:
                if offset >= data_end:
                    raise ValueError("Truncated FIT developer definition")
                developer_count = data[offset]
                offset += 1
                # Developer data is opaque, but its sizes are required to step
                # over each record correctly.  The developer index is ignored.
                developer_fields = []
                for _ in range(developer_count):
                    if offset + 3 > data_end:
                        raise ValueError("Truncated FIT developer definition")
                    _field_number, size, developer_index = data[offset:offset + 3]
                    developer_fields.append((developer_index, size, 13))
                    offset += 3
            definitions[local_number] = (architecture, global_number, fields, developer_fields)
            continue
        compressed = bool(record_header & 0x40)
        local_number = ((record_header >> 5) & 0x03) if compressed else (record_header & 0x0F)
        definition = definitions.get(local_number)
        if not definition:
            raise ValueError("FIT data has no definition")
        architecture, global_number, fields, developer_fields = definition
        total_size = sum(field[1] for field in fields)
        if offset + total_size + sum(field[1] for field in developer_fields) > data_end:
            raise ValueError("Truncated FIT data record")
        values = {}
        for number, size, base_type in fields:
            value = _fit_value(data[offset:offset + size], base_type, architecture)
            offset += size
            values[number] = value
        offset += sum(field[1] for field in developer_fields)
        if compressed and global_number == 20 and isinstance(last_timestamp, int):
            timestamp_offset = record_header & 0x1F
            last_timestamp += (timestamp_offset - (last_timestamp & 0x1F)) & 0x1F
            values.setdefault(253, last_timestamp)
        if global_number == 20 and isinstance(values.get(253), int):
            last_timestamp = values[253]
        messages.append((global_number, values))
    return messages


def _fit_timestamp(value):
    if not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
        return None
    try:
        return (FIT_EPOCH + timedelta(seconds=float(value))).isoformat().replace("+00:00", "Z")
    except (OverflowError, ValueError):
        return None


def _fit_metric(messages, message_number, field_number):
    values = [fields.get(field_number) for number, fields in messages if number == message_number]
    return [value for value in values if isinstance(value, (int, float)) and math.isfinite(value)]


def _fit_scaled(messages, message_number, field_number):
    meta = _FIT_FIELD_SCALES.get((message_number, field_number))
    values = _fit_metric(messages, message_number, field_number)
    if not meta:
        return values
    _, scale, offset = meta
    return [(value / scale) + offset for value in values]


def fit_summary(data):
    messages = _fit_messages(data)
    sessions = [fields for number, fields in messages if number == 18]
    records = [fields for number, fields in messages if number == 20]
    if not messages:
        raise ValueError("FIT contains no messages")
    session = sessions[0] if sessions else {}
    summary = {"source": "uploaded_fit", "record_count": len(records), "session_count": len(sessions)}
    start = _fit_timestamp(session.get(2)) or next((value for value in (_fit_timestamp(item.get(253)) for item in records) if value), None)
    if start:
        summary["start_time_utc"] = start
    sport = session.get(5)
    if isinstance(sport, int) and sport in _FIT_SPORTS:
        summary["sport"] = _FIT_SPORTS[sport]

    metrics = {
        "duration_s": (18, 7, 1), "timer_time_s": (18, 8, 1), "distance_km": (18, 9, 1000),
        "avg_speed_kmh": (18, 14, 1 / 3.6), "max_speed_kmh": (18, 15, 1 / 3.6),
        "avg_heart_rate_bpm": (18, 16, 1), "max_heart_rate_bpm": (18, 17, 1),
        "avg_cadence_rpm": (18, 18, 1), "max_cadence_rpm": (18, 19, 1),
        "avg_power_w": (18, 20, 1), "max_power_w": (18, 21, 1),
        "ascent_m": (18, 22, 1), "descent_m": (18, 23, 1),
        "normalized_power_w": (18, 34, 1), "training_stress_score": (18, 35, 10),
        "intensity_factor": (18, 36, 1000),
    }
    for key, (message_number, field_number, divisor) in metrics.items():
        values = _fit_scaled(messages, message_number, field_number)
        if values:
            value = values[0] / divisor
            summary[key] = round(value, 3) if isinstance(value, float) else value

    record_timestamps = _fit_scaled(messages, 20, 0)
    if record_timestamps:
        first, last = min(record_timestamps), max(record_timestamps)
        if "duration_s" not in summary:
            summary["duration_s"] = round(max(0, last - first), 3)
        if "start_time_utc" not in summary:
            summary["start_time_utc"] = _fit_timestamp(first)
    if "distance_km" not in summary:
        distances = _fit_scaled(messages, 20, 6)
        if distances:
            summary["distance_km"] = round(max(distances) / 1000, 3)
    for key, field_number in (("max_heart_rate_bpm", 4), ("max_cadence_rpm", 5), ("max_power_w", 7)):
        if key not in summary:
            values = _fit_metric(messages, 20, field_number)
            if values:
                summary[key] = max(values)
    if "ascent_m" not in summary or "descent_m" not in summary:
        elevations = _fit_scaled(messages, 20, 3)
        if elevations:
            ascent = sum(max(0, current - previous) for previous, current in zip(elevations, elevations[1:]))
            descent = sum(max(0, previous - current) for previous, current in zip(elevations, elevations[1:]))
            summary.setdefault("ascent_m", round(ascent))
            summary.setdefault("descent_m", round(descent))
    summary["note"] = "FIT-Werte stammen aus der hochgeladenen Aktivitätsdatei; fehlende Messwerte sind nicht verfügbar."
    return summary


def gpx_summary(data):
    text = data.decode("utf-8-sig")
    if "<!DOCTYPE" in text.upper() or "<!ENTITY" in text.upper():
        raise ValueError("XML declarations are forbidden")
    root = ET.fromstring(text)
    local = lambda tag: tag.rsplit("}", 1)[-1]
    if local(root.tag) != "gpx":
        raise ValueError("Not GPX")
    groups = [node for node in root.iter() if local(node.tag) in {"trkseg", "rte"}]
    distance = ascent = descent = 0.0
    points = []
    for group in groups:
        previous = None
        for node in group:
            if local(node.tag) not in {"trkpt", "rtept"}:
                continue
            lat, lon = float(node.attrib["lat"]), float(node.attrib["lon"])
            if not (-90 <= lat <= 90 and -180 <= lon <= 180):
                raise ValueError("Invalid coordinates")
            elevation = next((float(child.text) for child in node if local(child.tag) == "ele"), None)
            if elevation is not None and (not math.isfinite(elevation) or abs(elevation) > 20000):
                raise ValueError("Invalid elevation")
            point = [lat, lon, elevation]
            if previous:
                a, b = math.radians(previous[0]), math.radians(lat)
                h = math.sin((b-a)/2)**2 + math.cos(a)*math.cos(b)*math.sin(math.radians(lon-previous[1])/2)**2
                distance += 6371000 * 2 * math.asin(math.sqrt(min(1, max(0, h))))
                if elevation is not None and previous[2] is not None:
                    difference = elevation - previous[2]
                    ascent += max(0, difference)
                    descent += max(0, -difference)
            points.append(point)
            previous = point
    if not points:
        raise ValueError("No route or track points")
    stride = max(1, math.ceil(len(points)/200))
    return {"source": "uploaded_gpx", "point_count": len(points), "distance_km": round(distance/1000, 3),
            "ascent_m_raw": round(ascent), "descent_m_raw": round(descent),
            "elevation_point_count": sum(p[2] is not None for p in points),
            "note": "Distance and elevation are GPS estimates; elevation is unsmoothed. Coordinates are sampled.",
            "sampled_coordinates_lat_lon_ele": points[::stride], "end": points[-1]}


def validate_attachments(value):
    if value is None:
        return []
    if not isinstance(value, list) or len(value) > MAX_FILES:
        raise ValueError("Too many attachments")
    result = []
    for item in value:
        if not isinstance(item, dict):
            raise ValueError("Invalid attachment")
        name, encoded = item.get("name"), item.get("data")
        if not isinstance(name, str) or not 1 <= len(name) <= 160 or any(ord(c) < 32 for c in name) or "/" in name or "\\" in name:
            raise ValueError("Invalid filename")
        if not isinstance(encoded, str) or len(encoded) > 4 * math.ceil(MAX_FILE_BYTES/3):
            raise ValueError("Attachment too large")
        try:
            data = base64.b64decode(encoded, validate=True)
        except binascii.Error:
            raise ValueError("Invalid attachment encoding") from None
        if not data or len(data) > MAX_FILE_BYTES:
            raise ValueError("Invalid attachment size")
        if name.lower().endswith(".gpx"):
            try:
                summary = gpx_summary(data)
            except (ValueError, KeyError, TypeError, ET.ParseError):
                raise ValueError("Invalid GPX") from None
            result.append({"name": name, "type": "gpx", "mime": "application/gpx+xml", "gemini_mime": "text/xml",
                           "data": encoded, "summary": summary})
            continue
        if name.lower().endswith(".fit"):
            try:
                summary = fit_summary(data)
            except (ValueError, KeyError, TypeError, struct.error, UnicodeError):
                raise ValueError("Invalid FIT") from None
            result.append({"name": name, "type": "fit", "mime": "application/octet-stream", "gemini_mime": "application/octet-stream",
                           "data": encoded, "summary": summary})
            continue
        mime = None
        if data.startswith(b"\x89PNG\r\n\x1a\n") and name.lower().endswith(".png"):
            mime = "image/png"
        elif data.startswith(b"\xff\xd8\xff") and name.lower().endswith((".jpg", ".jpeg")):
            mime = "image/jpeg"
        elif data[:4] == b"RIFF" and data[8:12] == b"WEBP" and name.lower().endswith(".webp"):
            mime = "image/webp"
        if not mime:
            raise ValueError("Unsupported attachment")
        result.append({"name": name, "type": "image", "mime": mime, "data": encoded})
    return result


def model_input(text, attachments):
    if not attachments:
        return text
    parts = [{"type": "input_text", "text": text}]
    for item in attachments:
        summary_key = item["type"] if item["type"] in {"gpx", "fit"} else None
        evidence = {"untrusted_attachment_name": item["name"]}
        if summary_key:
            evidence[summary_key] = item.get("summary")
        parts.append({"type": "input_text", "text": json.dumps(evidence, ensure_ascii=False)})
        if item["type"] in {"gpx", "fit"}:
            parts.append({"type": "input_file", "filename": item["name"],
                          "file_data": f"data:{item['mime']};base64,{item['data']}"})
        elif item["type"] == "image":
            parts.append({"type": "input_image", "image_url": f"data:{item['mime']};base64,{item['data']}", "detail": "auto"})
    return [{"role": "user", "content": parts}]


def gemini_inline_image_bytes(attachments):
    return sum(len(str(item.get("data") or "")) for item in attachments if item.get("type") == "image")
