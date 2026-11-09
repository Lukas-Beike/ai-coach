"""Sensor sources of a FIT activity file, read from its device information.

Message 23 (``device_info``) lists the recording device and every sensor it
paired with: device_index (0), device_type (1), manufacturer (2), serial_number
(3), product (4) and source_type (25). Values follow the Garmin FIT SDK profile:
``source_type`` 0 ant, 1 antplus, 2 bluetooth, 3 bluetooth_low_energy, 4 wifi,
5 local; field 1 is the ``antplus_device_type`` for source type antplus (or
when the file names no source type) and the ``ble_device_type`` for Bluetooth LE
(0 connected_gps, 1 heart_rate, 2 bike_power, 3 bike_speed_cadence, 4
bike_speed, 5 bike_cadence, 6 footpod, 7 bike_trainer). A strap paired to a
watch appears here as its own external device, which the activity summary does
not show.

Classification, a documented heuristic rather than a vendor guarantee:

* heart rate: an external heart rate device (ANT+ type 120, BLE type 1) is a
  ``chest_strap``; without one, a Garmin file that lists its devices and has heart rate records names the
  recording device's own ``optical`` sensor; anything else is ``unknown``;
* power: an external power device (ANT+ type 11, BLE type 2) is a
  ``power_meter``, ANT+ type 17 (fitness equipment) or BLE type 7 a ``trainer``;
  power records with devices listed but no such sensor from Garmin are ``estimated`` (a watch's running power); anything else is
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
_ANTPLUS: Final = 1
_BLE: Final = 3
_BLE_HEART_RATE: Final = 1
_BLE_POWER: Final = 2
_BLE_TRAINER: Final = 7
_BLE_ROLES: Final[Mapping[int, SensorRole]] = {
    _BLE_HEART_RATE: SensorRole.HEART_RATE,
    _BLE_POWER: SensorRole.POWER_METER,
    _BLE_TRAINER: SensorRole.TRAINER,
}
_ROLES: Final[Mapping[int, SensorRole]] = {
    _ANTPLUS_HEART_RATE: SensorRole.HEART_RATE,
    _ANTPLUS_BIKE_POWER: SensorRole.POWER_METER,
    _ANTPLUS_FITNESS_EQUIPMENT: SensorRole.TRAINER,
}
_CONNECTIONS: Final[Mapping[int, str]] = {
    0: "ant",
    1: "antplus",
    2: "bluetooth",
    3: "bluetooth_low_energy",
    4: "wifi",
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
        roles = _roles_for(_whole(fields.get(_SOURCE_TYPE_FIELD)))
        role = None if device_type is None else roles.get(device_type)
        if role is None or not _external(fields):
            continue
        strap = strap or role is SensorRole.HEART_RATE
        meter = meter or role is SensorRole.POWER_METER
        trainer = trainer or role is SensorRole.TRAINER
        sensor = _sensor(fields, role)
        if sensor is not None and len(sensors) < MAX_SENSORS:
            sensors.setdefault(f"{role.value}:{sensor.key}", sensor)
    garmin_device = bool(devices) and provider is ProviderId.GARMIN
    hr_source = (
        _heart_rate_source(strap=strap, garmin_device=garmin_device)
        if has_heart_rate
        else None
    )
    power_source = (
        _power_source(meter=meter, trainer=trainer, garmin_device=garmin_device)
        if has_power
        else None
    )
    return hr_source, power_source, tuple(sensors.values())


def _heart_rate_source(*, strap: bool, garmin_device: bool) -> HeartRateSource:
    if strap:
        return HeartRateSource.CHEST_STRAP
    if garmin_device:
        return HeartRateSource.OPTICAL
    return HeartRateSource.UNKNOWN


def _power_source(*, meter: bool, trainer: bool, garmin_device: bool) -> PowerSource:
    if meter:
        return PowerSource.POWER_METER
    if trainer:
        return PowerSource.TRAINER
    if garmin_device:
        return PowerSource.ESTIMATED
    return PowerSource.UNKNOWN


def sensor_key(manufacturer: int | None, product: int | None, serial: int) -> str:
    """The hash that identifies one physical sensor without exposing its serial."""
    text = f"pacecraft-sensor:{manufacturer}:{product}:{serial}"
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _roles_for(source: int | None) -> Mapping[int, SensorRole]:
    """The device type table the source type selects; other sources name no roles."""
    if source == _BLE:
        return _BLE_ROLES
    return _ROLES if source is None or source == _ANTPLUS else {}


def _external(fields: Mapping[int, object]) -> bool:
    source = _whole(fields.get(_SOURCE_TYPE_FIELD))
    connection = None if source is None else _CONNECTIONS.get(source)
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
