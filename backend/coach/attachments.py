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
MAX_FIT_MESSAGES = 100_000
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
_UNSUPPORTED_FIT_BASE_TYPE = "Unsupported FIT base type"
_FIT_CRC_TABLE = (
    0x0000, 0xCC01, 0xD801, 0x1400, 0xF001, 0x3C00, 0x2800, 0xE401,
    0xA001, 0x6C00, 0x7800, 0xB401, 0x5000, 0x9C01, 0x8801, 0x4400,
)

# FIT base types used by the profile.  Unknown fields are still skipped safely,
# but an unknown base type makes the file structurally ambiguous and is rejected.
_FIT_BASE_TYPE_SIZES = {
    0: 1, 1: 1, 2: 1, 3: 2, 4: 2, 5: 4, 6: 4, 7: 1, 8: 4,
    9: 8, 10: 1, 11: 2, 12: 4, 13: 1, 14: 8, 15: 8, 16: 8,
}
_FIT_FIELD_SCALES = {
    # record message
    (20, 253): ("timestamp", 1, 0), (20, 0): ("position_lat", 1, 0),
    (20, 1): ("position_long", 1, 0), (20, 2): ("altitude_m", 5, -500),
    (20, 3): ("heart_rate_bpm", 1, 0), (20, 4): ("cadence_rpm", 1, 0),
    (20, 5): ("distance_m", 100, 0), (20, 6): ("speed_m_s", 1000, 0),
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
    5: "swimming", 6: "basketball", 7: "soccer", 8: "tennis", 9: "american_football",
    10: "training", 11: "walking", 12: "cross_country_skiing", 13: "alpine_skiing",
    14: "snowboarding", 15: "rowing", 16: "mountaineering", 17: "hiking", 18: "multisport",
    19: "paddling", 20: "flying", 21: "e_biking", 22: "motorcycling", 23: "boating",
    24: "driving", 25: "golf", 26: "hang_gliding", 27: "horseback_riding",
    28: "hunting", 29: "fishing", 30: "inline_skating", 31: "rock_climbing", 32: "sailing",
    41: "kayaking", 42: "rafting", 254: "all",
}
_FIT_BASE_TYPE_FORMATS = {
    0: "B", 1: "b", 2: "B", 3: "h", 4: "H", 5: "i", 6: "I", 8: "f", 9: "d",
    10: "B", 11: "H", 12: "I", 14: "q", 15: "Q", 16: "Q",
}
_FIT_INVALID_VALUES = {
    0: 0xFF, 1: -0x80, 2: 0xFF, 3: -0x8000, 4: 0xFFFF,
    5: -0x80000000, 6: 0xFFFFFFFF, 8: float("nan"), 9: float("nan"),
    10: 0, 11: 0, 12: 0, 14: -0x8000000000000000,
    15: 0xFFFFFFFFFFFFFFFF, 16: 0xFFFFFFFFFFFFFFFF,
}


def _fit_usable(value, invalid):
    if invalid is None:
        return value
    if isinstance(invalid, float) and math.isnan(invalid):
        return None if isinstance(value, float) and math.isnan(value) else value
    return None if value == invalid else value


def _fit_crc16(data):
    crc = 0
    for byte in data:
        crc = (crc >> 4) ^ _FIT_CRC_TABLE[(crc ^ byte) & 0x0F]
        crc = (crc >> 4) ^ _FIT_CRC_TABLE[(crc ^ (byte >> 4)) & 0x0F]
    return crc


def _fit_validate_checksums(data, header_size, data_end):
    if header_size > 12:
        if header_size < 14:
            raise ValueError("Invalid FIT header size")
        header_crc_offset = header_size - 2
        expected = struct.unpack_from("<H", data, header_crc_offset)[0]
        if _fit_crc16(data[:header_crc_offset]) != expected:
            raise ValueError("Invalid FIT header CRC")
    trailer_size = len(data) - data_end
    if trailer_size not in {0, 2}:
        raise ValueError("Invalid FIT file CRC length")
    if trailer_size == 2:
        expected = struct.unpack_from("<H", data, data_end)[0]
        if _fit_crc16(data[:data_end]) != expected:
            raise ValueError("Invalid FIT file CRC")


def _fit_decode_values(raw, base_type, architecture, size):
    if len(raw) % size:
        raise ValueError("Invalid FIT field size")
    fmt = _FIT_BASE_TYPE_FORMATS.get(base_type)
    if not fmt:
        raise ValueError(_UNSUPPORTED_FIT_BASE_TYPE)
    endian = "<" if architecture == 0 else ">"
    values = [struct.unpack(endian + fmt, raw[index:index + size])[0] for index in range(0, len(raw), size)]
    invalid = _FIT_INVALID_VALUES.get(base_type)
    filtered = [_fit_usable(value, invalid) for value in values]
    return filtered[0] if len(filtered) == 1 else filtered


def _fit_value(raw, base_type, architecture):
    """Decode one bounded FIT field, returning None for FIT invalid values."""
    type_num = base_type & 0x1F
    size = _FIT_BASE_TYPE_SIZES.get(type_num)
    if size is None:
        raise ValueError(_UNSUPPORTED_FIT_BASE_TYPE)
    if type_num == 7:
        return raw.rstrip(b"\x00").decode("utf-8", "replace")
    if type_num == 13:
        return raw
    return _fit_decode_values(raw, type_num, architecture, size)


def _fit_definition(data, offset, record_header, data_end):
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
        if size <= 0:
            raise ValueError("Invalid FIT field size")
        if base_type & 0x1F not in _FIT_BASE_TYPE_SIZES:
            raise ValueError(_UNSUPPORTED_FIT_BASE_TYPE)
        fields.append((number, size, base_type))
        offset += 3
    developer_fields = _fit_developer_definition(data, offset, record_header, data_end)
    offset += developer_fields[0]
    if not fields and not developer_fields[1]:
        raise ValueError("FIT definition has no fields")
    return offset, (architecture, global_number, fields, developer_fields[1])


def _fit_developer_definition(data, offset, record_header, data_end):
    if not record_header & 0x20:
        return 0, []
    if offset >= data_end:
        raise ValueError("Truncated FIT developer definition")
    start_offset = offset
    developer_count = data[offset]
    offset += 1
    developer_fields = []
    for _ in range(developer_count):
        if offset + 3 > data_end:
            raise ValueError("Truncated FIT developer definition")
        size, developer_index = data[offset + 1:offset + 3]
        if size <= 0:
            raise ValueError("Invalid FIT developer field size")
        developer_fields.append((developer_index, size, 13))
        offset += 3
    return offset - start_offset, developer_fields


def _fit_data_record(data, offset, record_header, definition, data_end, last_timestamp):
    compressed = bool(record_header & 0x80)
    if definition is None:
        raise ValueError("FIT data has no definition")
    architecture, global_number, fields, developer_fields = definition
    record_fields = [field for field in fields if not (compressed and field[0] == 253)]
    developer_size = sum(field[1] for field in developer_fields)
    total_size = sum(field[1] for field in record_fields)
    if offset + total_size + developer_size > data_end:
        raise ValueError("Truncated FIT data record")
    values = {}
    for number, size, base_type in record_fields:
        values[number] = _fit_value(data[offset:offset + size], base_type, architecture)
        offset += size
    offset += developer_size
    has_timestamp = any(number == 253 for number, _, _ in fields)
    if compressed and has_timestamp and isinstance(last_timestamp, int):
        timestamp_offset = record_header & 0x1F
        last_timestamp += (timestamp_offset - (last_timestamp & 0x1F)) & 0x1F
        values.setdefault(253, last_timestamp)
    if has_timestamp and isinstance(values.get(253), int):
        last_timestamp = values[253]
    return offset, last_timestamp, (global_number, values)


def _fit_record_is_definition(record_header):
    return bool(record_header & 0x40) and not bool(record_header & 0x80)


def _fit_local_number(record_header):
    return ((record_header >> 5) & 0x03) if record_header & 0x80 else (record_header & 0x0F)


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
    _fit_validate_checksums(data, header_size, data_end)
    definitions, messages = {}, []
    offset, last_timestamp = header_size, None
    while offset < data_end:
        record_header = data[offset]
        offset += 1
        if _fit_record_is_definition(record_header):
            offset, definition = _fit_definition(data, offset, record_header, data_end)
            definitions[record_header & 0x0F] = definition
            continue
        if len(messages) >= MAX_FIT_MESSAGES:
            raise ValueError("Too many FIT records")
        local_number = _fit_local_number(record_header)
        offset, last_timestamp, message = _fit_data_record(
            data, offset, record_header, definitions.get(local_number), data_end, last_timestamp
        )
        messages.append(message)
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


_FIT_SESSION_METRICS = {
    "duration_s": (18, 7, 1), "timer_time_s": (18, 8, 1), "distance_km": (18, 9, 1000),
    "avg_speed_kmh": (18, 14, 1 / 3.6), "max_speed_kmh": (18, 15, 1 / 3.6),
    "avg_heart_rate_bpm": (18, 16, 1), "max_heart_rate_bpm": (18, 17, 1),
    "avg_cadence_rpm": (18, 18, 1), "max_cadence_rpm": (18, 19, 1),
    "avg_power_w": (18, 20, 1), "max_power_w": (18, 21, 1),
    "ascent_m": (18, 22, 1), "descent_m": (18, 23, 1),
    "normalized_power_w": (18, 34, 1), "training_stress_score": (18, 35, 1),
    "intensity_factor": (18, 36, 1),
}
_FIT_SESSION_TOTALS = {"duration_s", "timer_time_s", "distance_km", "ascent_m", "descent_m", "training_stress_score"}
_FIT_SESSION_MAXIMA = {"max_speed_kmh", "max_heart_rate_bpm", "max_cadence_rpm", "max_power_w"}
_FIT_SESSION_WEIGHTED_AVERAGES = {
    "avg_speed_kmh", "avg_heart_rate_bpm", "avg_cadence_rpm", "avg_power_w", "normalized_power_w", "intensity_factor"
}


def _fit_session_metric_value(key, values, durations, divisor):
    if key in _FIT_SESSION_TOTALS:
        return sum(values) / divisor
    if key in _FIT_SESSION_MAXIMA:
        return max(values) / divisor
    if key in _FIT_SESSION_WEIGHTED_AVERAGES and len(values) == len(durations) and sum(durations) > 0:
        if key == "normalized_power_w":
            return (sum(max(0, metric) ** 4 * duration for metric, duration in zip(values, durations))
                    / sum(durations)) ** 0.25 / divisor
        return sum(metric * duration for metric, duration in zip(values, durations)) / sum(durations) / divisor
    if key in _FIT_SESSION_WEIGHTED_AVERAGES:
        return sum(values) / len(values) / divisor
    return values[0] / divisor


def _fit_session_summary(messages, sessions, records):
    session = sessions[0] if sessions else {}
    summary = {"source": "uploaded_fit", "record_count": len(records), "session_count": len(sessions)}
    start = _fit_timestamp(session.get(2)) or next(
        (value for value in (_fit_timestamp(item.get(253)) for item in records) if value), None
    )
    if start:
        summary["start_time_utc"] = start
    sports = {_FIT_SPORTS[sport] for sport in (item.get(5) for item in sessions) if sport in _FIT_SPORTS}
    if len(sports) > 1:
        summary["sport"] = "multisport"
    elif sports:
        summary["sport"] = next(iter(sports))
    durations = _fit_scaled(messages, 18, 8) or _fit_scaled(messages, 18, 7)
    for key, (message_number, field_number, divisor) in _FIT_SESSION_METRICS.items():
        values = _fit_scaled(messages, message_number, field_number)
        if not values:
            continue
        value = _fit_session_metric_value(key, values, durations, divisor)
        summary[key] = round(value, 3) if isinstance(value, float) else value
    return summary


def _fit_add_record_timing(messages, summary):
    record_timestamps = _fit_scaled(messages, 20, 253)
    if not record_timestamps:
        return
    first, last = min(record_timestamps), max(record_timestamps)
    if "duration_s" not in summary:
        summary["duration_s"] = round(max(0, last - first), 3)
    if "start_time_utc" not in summary:
        summary["start_time_utc"] = _fit_timestamp(first)


def _fit_add_record_distance(messages, summary):
    if "distance_km" in summary:
        return
    distances = _fit_scaled(messages, 20, 5)
    if distances:
        summary["distance_km"] = round(max(distances) / 1000, 3)


def _fit_add_record_extrema(messages, summary):
    for key, field_number in (("max_heart_rate_bpm", 3), ("max_cadence_rpm", 4), ("max_power_w", 7)):
        if key in summary:
            continue
        values = _fit_metric(messages, 20, field_number)
        if values:
            summary[key] = max(values)


def _fit_add_record_elevation(messages, summary):
    if "ascent_m" in summary and "descent_m" in summary:
        return
    elevations = _fit_scaled(messages, 20, 2)
    if not elevations:
        return
    ascent = sum(max(0, current - previous) for previous, current in zip(elevations, elevations[1:]))
    descent = sum(max(0, previous - current) for previous, current in zip(elevations, elevations[1:]))
    summary.setdefault("ascent_m", round(ascent))
    summary.setdefault("descent_m", round(descent))


def fit_summary(data):
    messages = _fit_messages(data)
    sessions = [fields for number, fields in messages if number == 18]
    records = [fields for number, fields in messages if number == 20]
    if not messages:
        raise ValueError("FIT contains no messages")
    summary = _fit_session_summary(messages, sessions, records)

    _fit_add_record_timing(messages, summary)
    _fit_add_record_distance(messages, summary)
    _fit_add_record_extrema(messages, summary)
    _fit_add_record_elevation(messages, summary)
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
            data, mime = provider_attachment_data(item)
            filename = item["name"] + ".json" if item["type"] == "fit" else item["name"]
            parts.append({"type": "input_file", "filename": filename,
                          "file_data": f"data:{mime};base64,{data}"})
        elif item["type"] == "image":
            parts.append({"type": "input_image", "image_url": f"data:{item['mime']};base64,{item['data']}", "detail": "auto"})
    return [{"role": "user", "content": parts}]


def gemini_inline_image_bytes(attachments):
    return sum(len(provider_attachment_data(item)[0]) for item in attachments if item.get("type") in {"image", "gpx", "fit"})


def provider_attachment_data(item):
    """Return a provider-safe representation without changing persisted bytes."""
    data = str(item.get("data") or "")
    if item.get("type") != "fit":
        return data, str(item.get("gemini_mime") or item.get("mime") or "")
    document = {
        "format": "FIT",
        "filename": str(item.get("name") or "activity.fit"),
        "summary": item.get("summary") if isinstance(item.get("summary"), dict) else {},
        # This is the exact original upload, encoded as a valid JSON string so
        # providers do not have to interpret binary bytes as text.
        "raw_base64": data,
    }
    encoded = base64.b64encode(json.dumps(document, ensure_ascii=False, separators=(",", ":")).encode("utf-8")).decode("ascii")
    return encoded, "application/json"
