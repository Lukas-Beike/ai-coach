"""Bounded, untrusted Coach attachments; no filesystem or network access."""

import base64
import binascii
import itertools
import json
import math
import struct
import xml.etree.ElementTree as ET

from backend.providers.fit_file import (
    fit_messages,
    fit_metric,
    fit_scaled,
    fit_timestamp_iso,
)

MAX_FILE_BYTES = 5_000_000
MAX_FILES = 4
MAX_REQUEST_BYTES = 28_000_000
# Keep encrypted database backups usable even when many turns contain images.
# This leaves headroom below the application's 100 MB backup limit.
# Keep room for application state and SQLite page overhead inside
# the existing 100 MB encrypted-backup limit.
MAX_ATTACHMENT_STORAGE_BYTES = 40_000_000
_FIT_SPORTS = {
    0: "generic",
    1: "running",
    2: "cycling",
    3: "transition",
    4: "fitness_equipment",
    5: "swimming",
    6: "basketball",
    7: "soccer",
    8: "tennis",
    9: "american_football",
    10: "training",
    11: "walking",
    12: "cross_country_skiing",
    13: "alpine_skiing",
    14: "snowboarding",
    15: "rowing",
    16: "mountaineering",
    17: "hiking",
    18: "multisport",
    19: "paddling",
    20: "flying",
    21: "e_biking",
    22: "motorcycling",
    23: "boating",
    24: "driving",
    25: "golf",
    26: "hang_gliding",
    27: "horseback_riding",
    28: "hunting",
    29: "fishing",
    30: "inline_skating",
    31: "rock_climbing",
    32: "sailing",
    41: "kayaking",
    42: "rafting",
    254: "all",
}


_FIT_SESSION_METRICS = {
    "duration_s": (18, 7, 1),
    "timer_time_s": (18, 8, 1),
    "distance_km": (18, 9, 1000),
    "avg_speed_kmh": (18, 14, 1 / 3.6),
    "max_speed_kmh": (18, 15, 1 / 3.6),
    "avg_heart_rate_bpm": (18, 16, 1),
    "max_heart_rate_bpm": (18, 17, 1),
    "avg_cadence_rpm": (18, 18, 1),
    "max_cadence_rpm": (18, 19, 1),
    "avg_power_w": (18, 20, 1),
    "max_power_w": (18, 21, 1),
    "ascent_m": (18, 22, 1),
    "descent_m": (18, 23, 1),
    "normalized_power_w": (18, 34, 1),
    "training_stress_score": (18, 35, 1),
    "intensity_factor": (18, 36, 1),
}
_FIT_SESSION_TOTALS = {
    "duration_s",
    "timer_time_s",
    "distance_km",
    "ascent_m",
    "descent_m",
    "training_stress_score",
}
_FIT_SESSION_MAXIMA = {
    "max_speed_kmh",
    "max_heart_rate_bpm",
    "max_cadence_rpm",
    "max_power_w",
}
_FIT_SESSION_WEIGHTED_AVERAGES = {
    "avg_speed_kmh",
    "avg_heart_rate_bpm",
    "avg_cadence_rpm",
    "avg_power_w",
    "normalized_power_w",
    "intensity_factor",
}


def _fit_session_metric_value(key, values, durations, divisor):
    if key in _FIT_SESSION_TOTALS:
        return sum(values) / divisor
    if key in _FIT_SESSION_MAXIMA:
        return max(values) / divisor
    if (
        key in _FIT_SESSION_WEIGHTED_AVERAGES
        and len(values) == len(durations)
        and sum(durations) > 0
    ):
        if key == "normalized_power_w":
            return (
                sum(
                    max(0, metric) ** 4 * duration
                    for metric, duration in zip(values, durations)
                )
                / sum(durations)
            ) ** 0.25 / divisor
        return (
            sum(metric * duration for metric, duration in zip(values, durations))
            / sum(durations)
            / divisor
        )
    if key in _FIT_SESSION_WEIGHTED_AVERAGES:
        return sum(values) / len(values) / divisor
    return values[0] / divisor


def _fit_session_summary(messages, sessions, records):
    session = sessions[0] if sessions else {}
    summary = {
        "source": "uploaded_fit",
        "record_count": len(records),
        "session_count": len(sessions),
    }
    start = fit_timestamp_iso(session.get(2)) or next(
        (
            value
            for value in (fit_timestamp_iso(item.get(253)) for item in records)
            if value
        ),
        None,
    )
    if start:
        summary["start_time_utc"] = start
    sports = {
        _FIT_SPORTS[sport]
        for sport in (item.get(5) for item in sessions)
        if sport in _FIT_SPORTS
    }
    if len(sports) > 1:
        summary["sport"] = "multisport"
    elif sports:
        summary["sport"] = next(iter(sports))
    durations = fit_scaled(messages, 18, 8) or fit_scaled(messages, 18, 7)
    for key, (message_number, field_number, divisor) in _FIT_SESSION_METRICS.items():
        values = fit_scaled(messages, message_number, field_number)
        if not values:
            continue
        value = _fit_session_metric_value(key, values, durations, divisor)
        summary[key] = round(value, 3) if isinstance(value, float) else value
    return summary


def _fit_add_record_timing(messages, summary):
    record_timestamps = fit_scaled(messages, 20, 253)
    if not record_timestamps:
        return
    first, last = min(record_timestamps), max(record_timestamps)
    if "duration_s" not in summary:
        summary["duration_s"] = round(max(0, last - first), 3)
    if "start_time_utc" not in summary:
        summary["start_time_utc"] = fit_timestamp_iso(first)


def _fit_add_record_distance(messages, summary):
    if "distance_km" in summary:
        return
    distances = fit_scaled(messages, 20, 5)
    if distances:
        summary["distance_km"] = round(max(distances) / 1000, 3)


def _fit_add_record_extrema(messages, summary):
    for key, field_number in (
        ("max_heart_rate_bpm", 3),
        ("max_cadence_rpm", 4),
        ("max_power_w", 7),
    ):
        if key in summary:
            continue
        values = fit_metric(messages, 20, field_number)
        if values:
            summary[key] = max(values)


def _fit_add_record_max_speed(messages, summary):
    # Only the maximum is taken from records; average speed needs even sampling.
    if "max_speed_kmh" in summary:
        return
    speeds = fit_scaled(messages, 20, 6)
    if speeds:
        summary["max_speed_kmh"] = round(max(speeds) * 3.6, 3)


def _fit_add_record_elevation(messages, summary):
    if "ascent_m" in summary and "descent_m" in summary:
        return
    elevations = fit_scaled(messages, 20, 2)
    if not elevations:
        return
    ascent = sum(
        max(0, current - previous)
        for previous, current in itertools.pairwise(elevations)
    )
    descent = sum(
        max(0, previous - current)
        for previous, current in itertools.pairwise(elevations)
    )
    summary.setdefault("ascent_m", round(ascent))
    summary.setdefault("descent_m", round(descent))


def fit_summary(data):
    messages = fit_messages(data)
    sessions = [fields for number, fields in messages if number == 18]
    records = [fields for number, fields in messages if number == 20]
    if not messages:
        raise ValueError("FIT contains no messages")
    summary = _fit_session_summary(messages, sessions, records)

    _fit_add_record_timing(messages, summary)
    _fit_add_record_distance(messages, summary)
    _fit_add_record_extrema(messages, summary)
    _fit_add_record_max_speed(messages, summary)
    _fit_add_record_elevation(messages, summary)
    summary["note"] = (
        "FIT-Werte stammen aus der hochgeladenen Aktivitätsdatei; fehlende Messwerte sind nicht verfügbar."
    )
    return summary


def _gpx_local_name(tag):
    return tag.rsplit("}", 1)[-1]


def _gpx_point(node):
    lat, lon = float(node.attrib["lat"]), float(node.attrib["lon"])
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise ValueError("Invalid coordinates")
    elevation = next(
        (float(child.text) for child in node if _gpx_local_name(child.tag) == "ele"),
        None,
    )
    if elevation is not None and (
        not math.isfinite(elevation) or abs(elevation) > 20000
    ):
        raise ValueError("Invalid elevation")
    return [lat, lon, elevation]


def _gpx_segment_stats(group):
    distance = ascent = descent = 0.0
    points = []
    previous = None
    for node in group:
        if _gpx_local_name(node.tag) not in {"trkpt", "rtept"}:
            continue
        point = _gpx_point(node)
        if previous:
            a, b = math.radians(previous[0]), math.radians(point[0])
            h = (
                math.sin((b - a) / 2) ** 2
                + math.cos(a)
                * math.cos(b)
                * math.sin(math.radians(point[1] - previous[1]) / 2) ** 2
            )
            distance += 6371000 * 2 * math.asin(math.sqrt(min(1, max(0, h))))
            if point[2] is not None and previous[2] is not None:
                difference = point[2] - previous[2]
                ascent += max(0, difference)
                descent += max(0, -difference)
        points.append(point)
        previous = point
    return distance, ascent, descent, points


def gpx_summary(data):
    text = data.decode("utf-8-sig")
    if "<!DOCTYPE" in text.upper() or "<!ENTITY" in text.upper():
        raise ValueError("XML declarations are forbidden")
    root = ET.fromstring(text)
    if _gpx_local_name(root.tag) != "gpx":
        raise ValueError("Not GPX")
    groups = [
        node for node in root.iter() if _gpx_local_name(node.tag) in {"trkseg", "rte"}
    ]
    distance = ascent = descent = 0.0
    points = []
    for group in groups:
        segment_distance, segment_ascent, segment_descent, segment_points = (
            _gpx_segment_stats(group)
        )
        distance += segment_distance
        ascent += segment_ascent
        descent += segment_descent
        points.extend(segment_points)
    if not points:
        raise ValueError("No route or track points")
    stride = max(1, math.ceil(len(points) / 200))
    return {
        "source": "uploaded_gpx",
        "point_count": len(points),
        "distance_km": round(distance / 1000, 3),
        "ascent_m_raw": round(ascent),
        "descent_m_raw": round(descent),
        "elevation_point_count": sum(p[2] is not None for p in points),
        "note": "Distance and elevation are GPS estimates; elevation is unsmoothed. Coordinates are sampled.",
        "sampled_coordinates_lat_lon_ele": points[::stride],
        "end": points[-1],
    }


def _decode_attachment(item):
    if not isinstance(item, dict):
        raise ValueError("Invalid attachment")  # noqa: TRY004 - Preserve the validation ValueError contract.
    name, encoded = item.get("name"), item.get("data")
    if (
        not isinstance(name, str)
        or not 1 <= len(name) <= 160
        or any(ord(c) < 32 for c in name)
        or "/" in name
        or "\\" in name
    ):
        raise ValueError("Invalid filename")
    if not isinstance(encoded, str) or len(encoded) > 4 * math.ceil(MAX_FILE_BYTES / 3):
        raise ValueError("Attachment too large")
    try:
        data = base64.b64decode(encoded, validate=True)
    except binascii.Error:
        raise ValueError("Invalid attachment encoding") from None
    if not data or len(data) > MAX_FILE_BYTES:
        raise ValueError("Invalid attachment size")
    return name, encoded, data


def _structured_attachment(name, encoded, data):
    if name.lower().endswith(".gpx"):
        try:
            summary = gpx_summary(data)
        except ValueError, KeyError, TypeError, ET.ParseError:
            raise ValueError("Invalid GPX") from None
        return {
            "name": name,
            "type": "gpx",
            "mime": "application/gpx+xml",
            "data": encoded,
            "summary": summary,
        }
    if name.lower().endswith(".fit"):
        try:
            summary = fit_summary(data)
        except ValueError, KeyError, TypeError, struct.error, UnicodeError:
            raise ValueError("Invalid FIT") from None
        return {
            "name": name,
            "type": "fit",
            "mime": "application/octet-stream",
            "data": encoded,
            "summary": summary,
        }
    return None


def _image_mime(name, data):
    signatures = (
        (b"\x89PNG\r\n\x1a\n", (".png",), "image/png"),
        (b"\xff\xd8\xff", (".jpg", ".jpeg"), "image/jpeg"),
        (b"RIFF", (".webp",), "image/webp"),
    )
    for signature, suffixes, mime in signatures:
        if (
            data.startswith(signature)
            and name.lower().endswith(suffixes)
            and (mime != "image/webp" or data[8:12] == b"WEBP")
        ):
            return mime
    return None


def _validated_attachment(item):
    name, encoded, data = _decode_attachment(item)
    structured = _structured_attachment(name, encoded, data)
    if structured:
        return structured
    mime = _image_mime(name, data)
    if not mime:
        raise ValueError("Unsupported attachment")
    return {"name": name, "type": "image", "mime": mime, "data": encoded}


class AttachmentRequestTooLarge(ValueError):
    """Validated attachments exceed the outgoing provider request budget."""


def validate_attachments(value):
    if value is None:
        return []
    if not isinstance(value, list) or len(value) > MAX_FILES:
        raise ValueError("Too many attachments")
    attachments = [_validated_attachment(item) for item in value]
    # FIT uploads are re-encoded for the provider, so the outgoing payload can be
    # larger than the uploaded bytes; the request budget applies to what is sent.
    outgoing_bytes = sum(len(openai_attachment_data(item)[0]) for item in attachments)
    if outgoing_bytes > MAX_REQUEST_BYTES:
        raise AttachmentRequestTooLarge("Attachment request too large")
    return attachments


def model_input(text, attachments):
    if not attachments:
        return text
    parts = [{"type": "input_text", "text": text}]
    for item in attachments:
        summary_key = item["type"] if item["type"] in {"gpx", "fit"} else None
        evidence = {"untrusted_attachment_name": item["name"]}
        if summary_key:
            evidence[summary_key] = item.get("summary")
        parts.append(
            {"type": "input_text", "text": json.dumps(evidence, ensure_ascii=False)}
        )
        if item["type"] in {"gpx", "fit"}:
            data, mime = openai_attachment_data(item)
            filename = item["name"] + ".json" if item["type"] == "fit" else item["name"]
            parts.append(
                {
                    "type": "input_file",
                    "filename": filename,
                    "file_data": f"data:{mime};base64,{data}",
                }
            )
        elif item["type"] == "image":
            parts.append(
                {
                    "type": "input_image",
                    "image_url": f"data:{item['mime']};base64,{item['data']}",
                    "detail": "auto",
                }
            )
    return [{"role": "user", "content": parts}]


def openai_attachment_data(item):
    """Return a provider-safe representation without changing persisted bytes."""
    data = str(item.get("data") or "")
    if item.get("type") != "fit":
        return data, str(item.get("mime") or "")
    document = {
        "format": "FIT",
        "filename": str(item.get("name") or "activity.fit"),
        "summary": item.get("summary") if isinstance(item.get("summary"), dict) else {},
        # This is the exact original upload, encoded as a valid JSON string so
        # providers do not have to interpret binary bytes as text.
        "raw_base64": data,
    }
    encoded = base64.b64encode(
        json.dumps(document, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ).decode("ascii")
    return encoded, "application/json"
