"""Sensor sources of a FIT activity file, read from its device information.

Message 23 (``device_info``) lists the recording device and every sensor it
paired with: device_index (0), device_type (1), manufacturer (2), serial_number
(3), product (4) and source_type (25: 1 antplus, 2 ant, 3 bluetooth, 4
bluetooth_low_energy, 5 local). The device type is the ANT+ device type, except
for a Bluetooth LE sensor, where it is the FIT ``ble_device_type`` (2 heart rate,
3 power meter). A strap paired to a watch appears
here as its own external device, which the activity summary does not show.

Classification, a documented heuristic rather than a vendor guarantee:

* heart rate: an external heart rate device (ANT+ type 120, BLE type 2) is a
  ``chest_strap``; without
  one, a Garmin file that lists its devices and has heart rate records names the
  recording device's own ``optical`` sensor; anything else is ``unknown``;
* power: an external power device (ANT+ type 11, BLE type 3) is a
  ``power_meter``, ANT+ type 17 (fitness equipment) a ``trainer``; power records with devices listed but no such sensor
  from Garmin are ``estimated`` (a watch's running power); anything else is
  ``unknown``.

Serial numbers are hashed with the manufacturer and product and never kept.
The module is pure and never raises for malformed content.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from typing import Final

from backend.canonical.activity_detail import MAX_SENSORS, ActivitySensor
from backend.canonical.vocabulary import (
    HeartRateSource,
    PowerSource,
    ProviderId,
    SensorRole,
)
from backend.providers.fit_file import FitMessage

DEVICE_INFO_MESSAGE: Final = 23
_DEVICE_INDEX_FIELD: Final = 0
_DEVICE_TYPE_FIELD: Final = 1
_MANUFACTURER_FIELD: Final = 2
_SERIAL_FIELD: Final = 3
_PRODUCT_FIELD: Final = 4
_SOURCE_TYPE_FIELD: Final = 25
_ANTPLUS_HEART_RATE: Final = 120
_ANTPLUS_BIKE_POWER: Final = 11
_ANTPLUS_FITNESS_EQUIPMENT: Final = 17
_BLE: Final = 4
_BLE_HEART_RATE: Final = 2
_BLE_POWER: Final = 3
_BLE_ROLES: Final[Mapping[int, SensorRole]] = {
    _BLE_HEART_RATE: SensorRole.HEART_RATE,
    _BLE_POWER: SensorRole.POWER_METER,
}
_ROLES: Final[Mapping[int, SensorRole]] = {
    _ANTPLUS_HEART_RATE: SensorRole.HEART_RATE,
    _ANTPLUS_BIKE_POWER: SensorRole.POWER_METER,
    _ANTPLUS_FITNESS_EQUIPMENT: SensorRole.TRAINER,
}
_CONNECTIONS: Final[Mapping[int, str]] = {
    1: "antplus",
    2: "ant",
    3: "bluetooth",
    4: "bluetooth_low_energy",
    5: "local",
}
_LOCAL: Final = "local"


def sensor_profile(
    messages: list[FitMessage],
    *,
    provider: ProviderId | None,
    has_heart_rate: bool,
    has_power: bool,
) -> tuple[HeartRateSource | None, PowerSource | None, tuple[ActivitySensor, ...]]:
    """Return the heart rate source, power source and external sensors of a file.

    A source is None when its channel is absent.
    """
    devices = [fields for number, fields in messages if number == DEVICE_INFO_MESSAGE]
    sensors: dict[str, ActivitySensor] = {}
    strap = meter = trainer = False
    for fields in devices:
        device_type = _whole(fields.get(_DEVICE_TYPE_FIELD))
        roles = _BLE_ROLES if _whole(fields.get(_SOURCE_TYPE_FIELD)) == _BLE else _ROLES
        role = None if device_type is None else roles.get(device_type)
        if role is None or not _external(fields):
            continue
        strap = strap or role is SensorRole.HEART_RATE
        meter = meter or role is SensorRole.POWER_METER
        trainer = trainer or role is SensorRole.TRAINER
        sensor = _sensor(fields, role)
        if sensor is not None and len(sensors) < MAX_SENSORS:
            sensors.setdefault(f"{role.value}:{sensor.key}", sensor)
    hr_source: HeartRateSource | None = None
    if has_heart_rate:
        if strap:
            hr_source = HeartRateSource.CHEST_STRAP
        elif devices and provider is ProviderId.GARMIN:
            hr_source = HeartRateSource.OPTICAL
        else:
            hr_source = HeartRateSource.UNKNOWN
    power_source: PowerSource | None = None
    if has_power:
        if meter:
            power_source = PowerSource.POWER_METER
        elif trainer:
            power_source = PowerSource.TRAINER
        elif devices and provider is ProviderId.GARMIN:
            power_source = PowerSource.ESTIMATED
        else:
            power_source = PowerSource.UNKNOWN
    return hr_source, power_source, tuple(sensors.values())


def sensor_key(manufacturer: int | None, product: int | None, serial: int) -> str:
    """The hash that identifies one physical sensor without exposing its serial."""
    text = f"pacecraft-sensor:{manufacturer}:{product}:{serial}"
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _external(fields: Mapping[int, object]) -> bool:
    connection = _CONNECTIONS.get(_whole(fields.get(_SOURCE_TYPE_FIELD)) or -1)
    if connection == _LOCAL:
        return False
    # Without a source type, the creator is device index 0 and sensors are not.
    index = _whole(fields.get(_DEVICE_INDEX_FIELD))
    return connection is not None or (index is not None and index != 0)


def _sensor(fields: Mapping[int, object], role: SensorRole) -> ActivitySensor | None:
    serial = _whole(fields.get(_SERIAL_FIELD))
    if serial is None or serial <= 0:
        return None
    manufacturer = _small(fields.get(_MANUFACTURER_FIELD))
    product = _small(fields.get(_PRODUCT_FIELD))
    source = _whole(fields.get(_SOURCE_TYPE_FIELD))
    return ActivitySensor(
        role=role,
        key=sensor_key(manufacturer, product, serial),
        connection=_CONNECTIONS.get(source) if source is not None else None,
        manufacturer=manufacturer,
        product=product,
    )


def _whole(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _small(value: object) -> int | None:
    number = _whole(value)
    return number if number is not None and 0 <= number <= 65_535 else None
