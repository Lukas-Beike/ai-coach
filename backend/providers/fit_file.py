"""Hardened stdlib decoder for Garmin FIT files.

Provider and upload bytes are untrusted: every reader bounds its work, verifies
the header and file CRCs, and raises ``ValueError`` on malformed input. Field
numbers follow the FIT SDK profile. Values are returned raw unless a scale is
registered in ``_FIT_FIELD_SCALES``; FIT invalid sentinels decode to ``None``.
This module must not import application domains such as ``backend.coach``.
"""

from __future__ import annotations

import math
import struct
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from typing import Final

type _FitField = tuple[int, int, int]
type _FitDefinition = tuple[int, int, list[_FitField], list[_FitField]]
type FitMessage = tuple[int, dict[int, object]]

MAX_FIT_MESSAGES: Final = 100_000
FIT_SIGNATURE: Final = b".FIT"
FIT_EPOCH: Final = datetime(1989, 12, 31, tzinfo=UTC)
_UNSUPPORTED_FIT_BASE_TYPE: Final = "Unsupported FIT base type"
_FIT_CRC_TABLE: Final[tuple[int, ...]] = (
    0x0000,
    0xCC01,
    0xD801,
    0x1400,
    0xF001,
    0x3C00,
    0x2800,
    0xE401,
    0xA001,
    0x6C00,
    0x7800,
    0xB401,
    0x5000,
    0x9C01,
    0x8801,
    0x4400,
)

# FIT base types used by the profile.  Unknown fields are still skipped safely,
# but an unknown base type makes the file structurally ambiguous and is rejected.
_FIT_BASE_TYPE_SIZES: Final[Mapping[int, int]] = {
    0: 1,
    1: 1,
    2: 1,
    3: 2,
    4: 2,
    5: 4,
    6: 4,
    7: 1,
    8: 4,
    9: 8,
    10: 1,
    11: 2,
    12: 4,
    13: 1,
    14: 8,
    15: 8,
    16: 8,
}
# (message number, field number) -> (name, divisor, offset). The value is
# value / divisor + offset. Fields outside this table are returned raw.
_FIT_FIELD_SCALES: Final[Mapping[tuple[int, int], tuple[str, int, int]]] = {
    # record message
    (20, 253): ("timestamp", 1, 0),
    (20, 0): ("position_lat", 1, 0),
    (20, 1): ("position_long", 1, 0),
    (20, 2): ("altitude_m", 5, -500),
    (20, 3): ("heart_rate_bpm", 1, 0),
    (20, 4): ("cadence_rpm", 1, 0),
    (20, 5): ("distance_m", 100, 0),
    (20, 6): ("speed_m_s", 1000, 0),
    (20, 7): ("power_w", 1, 0),
    (20, 13): ("temperature_c", 1, 0),
    (20, 53): ("fractional_cadence_rpm", 128, 0),
    (20, 73): ("enhanced_speed_m_s", 1000, 0),
    (20, 78): ("enhanced_altitude_m", 5, -500),
    # lap message
    (19, 2): ("start_time", 1, 0),
    (19, 7): ("total_elapsed_time_s", 1000, 0),
    (19, 8): ("total_timer_time_s", 1000, 0),
    (19, 9): ("total_distance_m", 100, 0),
    (19, 13): ("avg_speed_m_s", 1000, 0),
    (19, 15): ("avg_heart_rate_bpm", 1, 0),
    (19, 16): ("max_heart_rate_bpm", 1, 0),
    (19, 17): ("avg_cadence_rpm", 1, 0),
    (19, 19): ("avg_power_w", 1, 0),
    (19, 20): ("max_power_w", 1, 0),
    (19, 21): ("total_ascent_m", 1, 0),
    (19, 33): ("normalized_power_w", 1, 0),
    (19, 110): ("enhanced_avg_speed_m_s", 1000, 0),
    # session message
    (18, 2): ("timestamp", 1, 0),
    (18, 7): ("elapsed_time_s", 1000, 0),
    (18, 8): ("timer_time_s", 1000, 0),
    (18, 9): ("distance_m", 100, 0),
    (18, 14): ("avg_speed_m_s", 1000, 0),
    (18, 15): ("max_speed_m_s", 1000, 0),
    (18, 16): ("avg_heart_rate_bpm", 1, 0),
    (18, 17): ("max_heart_rate_bpm", 1, 0),
    (18, 18): ("avg_cadence_rpm", 1, 0),
    (18, 19): ("max_cadence_rpm", 1, 0),
    (18, 20): ("avg_power_w", 1, 0),
    (18, 21): ("max_power_w", 1, 0),
    (18, 22): ("total_ascent_m", 1, 0),
    (18, 23): ("total_descent_m", 1, 0),
    (18, 34): ("normalized_power_w", 1, 0),
    (18, 35): ("training_stress_score", 10, 0),
    (18, 36): ("intensity_factor", 1000, 0),
    (18, 124): ("enhanced_avg_speed_m_s", 1000, 0),
    (18, 125): ("enhanced_max_speed_m_s", 1000, 0),
}
# Ordered candidates per base field: the FIT enhanced field is preferred per
# message; invalid sentinels decode to None and fall through to the base field.
_FIT_FIELD_PREFERENCES: Final[Mapping[tuple[int, int], tuple[int, ...]]] = {
    (20, 2): (78, 2),
    (20, 6): (73, 6),
    (18, 14): (124, 14),
    (18, 15): (125, 15),
    (19, 13): (110, 13),
}
_FIT_BASE_TYPE_FORMATS: Final[Mapping[int, str]] = {
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
# Sentinels follow the FIT SDK base type table; signed types use their maximum.
_FIT_INVALID_VALUES: Final[Mapping[int, float | int]] = {
    0: 0xFF,
    1: 0x7F,
    2: 0xFF,
    3: 0x7FFF,
    4: 0xFFFF,
    5: 0x7FFFFFFF,
    6: 0xFFFFFFFF,
    8: float("nan"),
    9: float("nan"),
    10: 0,
    11: 0,
    12: 0,
    14: 0x7FFFFFFFFFFFFFFF,
    15: 0xFFFFFFFFFFFFFFFF,
    16: 0,
}


def _fit_usable(value: object, invalid: object) -> object:
    if invalid is None:
        return value
    if isinstance(invalid, float) and math.isnan(invalid):
        return None if isinstance(value, float) and math.isnan(value) else value
    return None if value == invalid else value


def _fit_crc16(data: bytes) -> int:
    crc = 0
    for byte in data:
        crc = (crc >> 4) ^ _FIT_CRC_TABLE[(crc ^ byte) & 0x0F]
        crc = (crc >> 4) ^ _FIT_CRC_TABLE[(crc ^ (byte >> 4)) & 0x0F]
    return crc


def _fit_validate_checksums(data: bytes, header_size: int, data_end: int) -> None:
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


def _fit_decode_values(
    raw: bytes, base_type: int, architecture: int, size: int
) -> object:
    if len(raw) % size:
        # A width that does not fit the base type (for example a newer profile
        # extension) is kept as bytes, as in the FIT SDK, so the rest of the file
        # still decodes.
        return raw
    fmt = _FIT_BASE_TYPE_FORMATS.get(base_type)
    if not fmt:
        raise ValueError(_UNSUPPORTED_FIT_BASE_TYPE)
    endian = "<" if architecture == 0 else ">"
    values = [
        struct.unpack(endian + fmt, raw[index : index + size])[0]
        for index in range(0, len(raw), size)
    ]
    invalid = _FIT_INVALID_VALUES.get(base_type)
    filtered = [_fit_usable(value, invalid) for value in values]
    return filtered[0] if len(filtered) == 1 else filtered


def _fit_value(raw: bytes, base_type: int, architecture: int) -> object:
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


def _fit_definition(
    data: bytes, offset: int, record_header: int, data_end: int
) -> tuple[int, _FitDefinition]:
    if offset + 5 > data_end:
        raise ValueError("Truncated FIT definition")
    architecture = data[offset + 1]
    if architecture not in (0, 1):
        raise ValueError("Invalid FIT architecture")
    endian = "<" if architecture == 0 else ">"
    global_number = struct.unpack_from(endian + "H", data, offset + 2)[0]
    field_count = data[offset + 4]
    offset += 5
    fields: list[_FitField] = []
    for _ in range(field_count):
        if offset + 3 > data_end:
            raise ValueError("Truncated FIT field definition")
        number, size, base_type = data[offset : offset + 3]
        if size <= 0:
            raise ValueError("Invalid FIT field size")
        if base_type & 0x1F not in _FIT_BASE_TYPE_SIZES:
            raise ValueError(_UNSUPPORTED_FIT_BASE_TYPE)
        fields.append((number, size, base_type))
        offset += 3
    developer_size, developer_fields = _fit_developer_definition(
        data, offset, record_header, data_end
    )
    offset += developer_size
    if not fields and not developer_fields:
        raise ValueError("FIT definition has no fields")
    return offset, (architecture, global_number, fields, developer_fields)


def _fit_developer_definition(
    data: bytes, offset: int, record_header: int, data_end: int
) -> tuple[int, list[_FitField]]:
    if not record_header & 0x20:
        return 0, []
    if offset >= data_end:
        raise ValueError("Truncated FIT developer definition")
    start_offset = offset
    developer_count = data[offset]
    offset += 1
    developer_fields: list[_FitField] = []
    for _ in range(developer_count):
        if offset + 3 > data_end:
            raise ValueError("Truncated FIT developer definition")
        size, developer_index = data[offset + 1 : offset + 3]
        if size <= 0:
            raise ValueError("Invalid FIT developer field size")
        developer_fields.append((developer_index, size, 13))
        offset += 3
    return offset - start_offset, developer_fields


def _fit_data_record(
    data: bytes,
    offset: int,
    record_header: int,
    definition: _FitDefinition | None,
    data_end: int,
    last_timestamp: int | None,
) -> tuple[int, int | None, FitMessage]:
    compressed = bool(record_header & 0x80)
    if definition is None:
        raise ValueError("FIT data has no definition")
    architecture, global_number, fields, developer_fields = definition
    record_fields = [field for field in fields if not (compressed and field[0] == 253)]
    developer_size = sum(field[1] for field in developer_fields)
    total_size = sum(field[1] for field in record_fields)
    if offset + total_size + developer_size > data_end:
        raise ValueError("Truncated FIT data record")
    values: dict[int, object] = {}
    for number, size, base_type in record_fields:
        values[number] = _fit_value(
            data[offset : offset + size], base_type, architecture
        )
        offset += size
    offset += developer_size
    has_timestamp = any(number == 253 for number, _, _ in fields)
    if compressed and has_timestamp and isinstance(last_timestamp, int):
        timestamp_offset = record_header & 0x1F
        last_timestamp += (timestamp_offset - (last_timestamp & 0x1F)) & 0x1F
        values.setdefault(253, last_timestamp)
    timestamp = values.get(253)
    if has_timestamp and isinstance(timestamp, int):
        last_timestamp = timestamp
    return offset, last_timestamp, (global_number, values)


def _fit_record_is_definition(record_header: int) -> bool:
    return bool(record_header & 0x40) and not bool(record_header & 0x80)


def _fit_local_number(record_header: int) -> int:
    return (
        ((record_header >> 5) & 0x03)
        if record_header & 0x80
        else (record_header & 0x0F)
    )


def fit_messages(data: bytes) -> list[FitMessage]:
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
    definitions: dict[int, _FitDefinition] = {}
    messages: list[FitMessage] = []
    offset = header_size
    last_timestamp: int | None = None
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
            data,
            offset,
            record_header,
            definitions.get(local_number),
            data_end,
            last_timestamp,
        )
        messages.append(message)
    return messages


def fit_timestamp_iso(value: object) -> str | None:
    """Return a FIT timestamp as an ISO 8601 UTC string, or None when invalid."""
    if not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
        return None
    try:
        return (
            (FIT_EPOCH + timedelta(seconds=float(value)))
            .isoformat()
            .replace("+00:00", "Z")
        )
    except OverflowError, ValueError:
        return None


def fit_metric(
    messages: Sequence[tuple[int, Mapping[int, object]]],
    message_number: int,
    field_number: int,
) -> list[int | float]:
    """Return raw finite numeric values of one field across matching messages."""
    values: list[int | float] = []
    for number, fields in messages:
        if number != message_number:
            continue
        value = fields.get(field_number)
        if isinstance(value, (int, float)) and math.isfinite(value):
            values.append(value)
    return values


def fit_field(
    fields: Mapping[int, object], message_number: int, field_number: int
) -> float | None:
    """Return one message's scaled value from its first valid candidate field.

    Candidates follow ``_FIT_FIELD_PREFERENCES``: the enhanced field wins when
    it holds a usable value, and an invalid sentinel falls through to the base
    field. Returns None when no candidate is usable.
    """
    candidates = _FIT_FIELD_PREFERENCES.get(
        (message_number, field_number), (field_number,)
    )
    for candidate in candidates:
        value = fields.get(candidate)
        if isinstance(value, (int, float)) and math.isfinite(value):
            _, scale, offset = _FIT_FIELD_SCALES.get(
                (message_number, candidate), ("", 1, 0)
            )
            return (value / scale) + offset
    return None


def fit_scaled(
    messages: Sequence[tuple[int, Mapping[int, object]]],
    message_number: int,
    field_number: int,
) -> list[float]:
    """Return one scaled value per matching message, skipping unusable messages."""
    values: list[float] = []
    for number, fields in messages:
        if number != message_number:
            continue
        value = fit_field(fields, message_number, field_number)
        if value is not None:
            values.append(value)
    return values
