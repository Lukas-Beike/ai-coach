"""Remove metadata (EXIF, XMP, text chunks) from JPEG, PNG and WebP bytes.

Only the container is rewritten; pixel data is copied unchanged. Anything that
cannot be parsed raises ``ValueError``, so unparsed bytes are never sent on.
"""

from __future__ import annotations

import struct

_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
# Chunks that decode the image or tint it; every other chunk (text, EXIF, time,
# unknown ancillary data) is dropped.
_PNG_KEPT_CHUNKS = {
    b"IHDR",
    b"PLTE",
    b"IDAT",
    b"IEND",
    b"tRNS",
    b"gAMA",
    b"cHRM",
    b"sRGB",
    b"iCCP",
    b"sBIT",
    b"bKGD",
    b"pHYs",
    b"acTL",
    b"fcTL",
    b"fdAT",
}
# JFIF header and Adobe colour transform are needed to decode correctly.
_JPEG_KEPT_APP = {0xE0, 0xEE}
_WEBP_DROPPED_CHUNKS = {b"EXIF", b"XMP "}
_WEBP_EXIF_AND_XMP_FLAGS = 0x08 | 0x04


def _jpeg_segment_kept(marker: int, segment: bytes) -> bool:
    if marker == 0xE2:  # only the colour profile of the APP2 segments
        return segment[4:16] == b"ICC_PROFILE\x00"
    if marker == 0xFE:  # comment
        return False
    return marker not in range(0xE0, 0xF0) or marker in _JPEG_KEPT_APP


def _jpeg_marker(data: bytes, offset: int) -> int:
    if data[offset] != 0xFF:
        raise ValueError("Invalid JPEG marker")
    return data[offset + 1] if offset + 1 < len(data) else 0


def _jpeg_segment_end(data: bytes, offset: int) -> int:
    if offset + 4 > len(data):
        raise ValueError("Truncated JPEG segment")
    length = struct.unpack_from(">H", data, offset + 2)[0]
    end = offset + 2 + length
    if length < 2 or end > len(data):
        raise ValueError("Truncated JPEG segment")
    return end


def _strip_jpeg(data: bytes) -> bytes:
    if not data.startswith(b"\xff\xd8"):
        raise ValueError("Invalid JPEG")
    out = bytearray(b"\xff\xd8")
    offset = 2
    while offset < len(data):
        marker = _jpeg_marker(data, offset)
        if marker == 0xFF:  # fill byte
            offset += 1
        elif marker == 0x01 or 0xD0 <= marker <= 0xD8:  # markers without length
            out += data[offset : offset + 2]
            offset += 2
        elif marker == 0xD9:
            return bytes(out + data[offset:])
        else:
            end = _jpeg_segment_end(data, offset)
            if marker == 0xDA:  # entropy-coded image data follows unchanged
                return bytes(out + data[offset:])
            segment = data[offset:end]
            if _jpeg_segment_kept(marker, segment):
                out += segment
            offset = end
    raise ValueError("JPEG has no image data")


def _strip_png(data: bytes) -> bytes:
    if not data.startswith(_PNG_SIGNATURE):
        raise ValueError("Invalid PNG")
    out = bytearray(_PNG_SIGNATURE)
    offset = len(_PNG_SIGNATURE)
    while offset < len(data):
        if offset + 8 > len(data):
            raise ValueError("Truncated PNG chunk")
        length = struct.unpack_from(">I", data, offset)[0]
        end = offset + 12 + length
        if end > len(data):
            raise ValueError("Truncated PNG chunk")
        kind = data[offset + 4 : offset + 8]
        if kind in _PNG_KEPT_CHUNKS:
            out += data[offset:end]
        offset = end
        if kind == b"IEND":
            return bytes(out)
    raise ValueError("PNG has no end")


def _webp_chunk_bounds(data: bytes, offset: int, riff_end: int) -> tuple[bytes, int]:
    """The chunk's kind and payload size; the chunk must lie inside the file."""
    if offset + 8 > riff_end:
        raise ValueError("Truncated WebP chunk")
    size = struct.unpack_from("<I", data, offset + 4)[0]
    if offset + 8 + size > riff_end:
        raise ValueError("Truncated WebP chunk")
    return data[offset : offset + 4], size


def _webp_kept_chunk(data: bytes, offset: int, kind: bytes, size: int) -> bytes:
    chunk = bytearray(data[offset : offset + 8 + size])
    if kind == b"VP8X" and size >= 1:
        chunk[8] &= ~_WEBP_EXIF_AND_XMP_FLAGS & 0xFF
    return bytes(chunk) + (b"\x00" if size & 1 else b"")


def _strip_webp(data: bytes) -> bytes:
    if len(data) < 12 or data[:4] != b"RIFF" or data[8:12] != b"WEBP":
        raise ValueError("Invalid WebP")
    riff_end = 8 + struct.unpack_from("<I", data, 4)[0]
    if riff_end > len(data) or riff_end < 12:
        raise ValueError("Truncated WebP")
    body = bytearray()
    offset = 12
    while offset < riff_end:
        kind, size = _webp_chunk_bounds(data, offset, riff_end)
        if kind not in _WEBP_DROPPED_CHUNKS:
            body += _webp_kept_chunk(data, offset, kind, size)
        offset += 8 + size + (size & 1)
    if not body:
        raise ValueError("WebP has no image data")
    return b"RIFF" + struct.pack("<I", 4 + len(body)) + b"WEBP" + bytes(body)


def strip_image_metadata(data: bytes, mime: str) -> bytes:
    """Return the image without EXIF, XMP, text or other metadata."""
    if mime == "image/jpeg":
        return _strip_jpeg(data)
    if mime == "image/png":
        return _strip_png(data)
    if mime == "image/webp":
        return _strip_webp(data)
    raise ValueError("Unsupported image type")
