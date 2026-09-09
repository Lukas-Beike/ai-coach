"""Bounded, untrusted Coach attachments; no filesystem or network access."""
import base64
import binascii
import json
import math
import xml.etree.ElementTree as ET

MAX_FILE_BYTES = 2_000_000
MAX_FILES = 4
MAX_REQUEST_BYTES = 11_000_000
# Keep encrypted database backups usable even when many turns contain images.
# This leaves headroom below the application's 100 MB backup limit.
MAX_ATTACHMENT_STORAGE_BYTES = 50_000_000


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
        except (ValueError, binascii.Error):
            raise ValueError("Invalid attachment encoding") from None
        if not data or len(data) > MAX_FILE_BYTES:
            raise ValueError("Invalid attachment size")
        if name.lower().endswith(".gpx"):
            try:
                summary = gpx_summary(data)
            except (ValueError, KeyError, TypeError, ET.ParseError, UnicodeError):
                raise ValueError("Invalid GPX") from None
            result.append({"name": name, "type": "gpx", "summary": summary})
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
        parts.append({"type": "input_text", "text": json.dumps({"untrusted_attachment_name": item["name"],
                      "gpx": item.get("summary")}, ensure_ascii=False)})
        if item["type"] == "image":
            parts.append({"type": "input_image", "image_url": f"data:{item['mime']};base64,{item['data']}", "detail": "auto"})
    return [{"role": "user", "content": parts}]
