"""Heart rate and power sources from FIT device information (#1869).

Synthetic FIT files come from the struct-based builder in ``test_fit_file``.
"""

import unittest
from datetime import UTC, datetime

from backend.canonical.activity_detail import ActivityStreamSet
from backend.canonical.records import Provenance
from backend.canonical.vocabulary import (
    HeartRateSource,
    PowerSource,
    ProviderId,
    RecordingOrigin,
    SensorRole,
    SourceKind,
)
from backend.providers.fit_activity_detail_mapping import map_fit_activity_detail
from backend.providers.fit_sensor_mapping import sensor_key
from tests import test_fit_file as fit_builder

ENUM, UINT8, UINT16, UINT32 = (
    fit_builder.ENUM,
    fit_builder.UINT8,
    fit_builder.UINT16,
    fit_builder.UINT32,
)
RECORD = [(253, UINT32), (3, UINT8), (7, UINT16)]
DEVICE = [
    (0, UINT8),
    (1, UINT8),
    (2, UINT16),
    (3, UINT32),
    (4, UINT16),
    (25, ENUM),
]
SERIAL = 3351234567
ANTPLUS, LOCAL, BLE = 1, 5, 4


def provenance(provider: ProviderId, origin: RecordingOrigin) -> Provenance:
    return Provenance(
        provider=provider,
        source_kind=SourceKind.PROVIDER_REPORTED,
        source_record_id=None,
        recorded_by=origin,
        retrieved_at=datetime(2026, 11, 9, tzinfo=UTC),
        label=None,
    )


GARMIN = provenance(ProviderId.GARMIN, RecordingOrigin.GARMIN)
WAHOO = provenance(ProviderId.WAHOO, RecordingOrigin.WAHOO)


def device(index, kind, manufacturer, serial, product, source):
    return {0: index, 1: kind, 2: manufacturer, 3: serial, 4: product, 25: source}


def fit_file(devices=(), *, heart_rate=True, power=True):
    builder = fit_builder.FitBuilder()
    if devices:
        builder.define(1, 23, DEVICE)
        for row in devices:
            builder.data(1, row)
    builder.define(0, 20, RECORD)
    for second in range(4):
        builder.data(
            0,
            {
                253: 1_000_000 + second,
                3: 140 + second if heart_rate else 0xFF,
                7: 200 + second if power else 0xFFFF,
            },
        )
    return builder.build()


def streams(data, prov=GARMIN) -> ActivityStreamSet:
    result = map_fit_activity_detail(data, provider_activity_id="a1", provenance=prov)
    return next(r for r in result.records if isinstance(r, ActivityStreamSet))


class FitSensorMappingTests(unittest.TestCase):
    def test_a_strap_paired_to_a_watch_resolves_to_a_chest_strap(self):
        data = fit_file(
            [
                device(0, 0, 1, 111, 3500, LOCAL),  # the watch itself
                device(1, 120, 1, SERIAL, 2000, ANTPLUS),  # the strap
            ]
        )
        result = streams(data)
        self.assertIs(result.hr_source, HeartRateSource.CHEST_STRAP)
        self.assertEqual(
            [(s.role, s.connection, s.manufacturer, s.product) for s in result.sensors],
            [(SensorRole.HEART_RATE, "antplus", 1, 2000)],
        )

    def test_bluetooth_sensors_use_the_ble_device_types(self):
        data = fit_file(
            [
                device(0, 0, 1, 111, 3500, LOCAL),
                device(1, 2, 107, SERIAL, 12, BLE),  # ble_device_type heart_rate
                device(2, 3, 7, SERIAL + 1, 5, BLE),  # ble_device_type bike_power
            ]
        )
        result = streams(data)
        self.assertIs(result.hr_source, HeartRateSource.CHEST_STRAP)
        self.assertIs(result.power_source, PowerSource.POWER_METER)
        self.assertEqual(
            sorted(s.role.value for s in result.sensors), ["heart_rate", "power_meter"]
        )
        # The ANT+ number 120 is not a heart rate device over Bluetooth.
        other = streams(fit_file([device(1, 120, 1, SERIAL, 2000, BLE)]))
        self.assertIsNot(other.hr_source, HeartRateSource.CHEST_STRAP)
        self.assertEqual(other.sensors, ())

    def test_a_watch_alone_names_its_optical_heart_rate(self):
        result = streams(fit_file([device(0, 0, 1, 111, 3500, LOCAL)]))
        self.assertIs(result.hr_source, HeartRateSource.OPTICAL)
        self.assertEqual(result.sensors, ())

    def test_power_sources_follow_the_antplus_device_type(self):
        meter = streams(fit_file([device(1, 11, 7, SERIAL, 5, ANTPLUS)]))
        self.assertIs(meter.power_source, PowerSource.POWER_METER)
        self.assertEqual(meter.sensors[0].role, SensorRole.POWER_METER)
        trainer = streams(fit_file([device(1, 17, 32, SERIAL, 9, ANTPLUS)]))
        self.assertIs(trainer.power_source, PowerSource.TRAINER)
        self.assertEqual(trainer.sensors[0].role, SensorRole.TRAINER)
        both = streams(
            fit_file(
                [
                    device(1, 17, 32, SERIAL, 9, ANTPLUS),
                    device(2, 3, 7, SERIAL + 1, 5, BLE),
                ]
            )
        )
        self.assertIs(both.power_source, PowerSource.POWER_METER)
        self.assertEqual(len(both.sensors), 2)

    def test_power_without_a_sensor_is_estimated_for_garmin_only(self):
        data = fit_file([device(0, 0, 1, 111, 3500, LOCAL)])
        self.assertIs(streams(data).power_source, PowerSource.ESTIMATED)
        self.assertIs(streams(data, WAHOO).power_source, PowerSource.UNKNOWN)
        self.assertIs(streams(data, WAHOO).hr_source, HeartRateSource.UNKNOWN)

    def test_a_file_without_device_information_says_unknown(self):
        result = streams(fit_file())
        self.assertIs(result.hr_source, HeartRateSource.UNKNOWN)
        self.assertIs(result.power_source, PowerSource.UNKNOWN)
        self.assertEqual(result.sensors, ())

    def test_absent_channels_have_no_source(self):
        data = fit_file(
            [device(1, 120, 1, SERIAL, 2000, ANTPLUS)], heart_rate=False, power=False
        )
        # No usable channel besides time: no stream set at all.
        result = map_fit_activity_detail(
            data, provider_activity_id="a1", provenance=GARMIN
        )
        self.assertFalse(
            [r for r in result.records if isinstance(r, ActivityStreamSet)]
        )
        only_power = streams(
            fit_file([device(1, 11, 7, SERIAL, 5, ANTPLUS)], heart_rate=False)
        )
        self.assertIsNone(only_power.hr_source)
        self.assertIs(only_power.power_source, PowerSource.POWER_METER)

    def test_the_serial_is_only_kept_as_a_hash(self):
        result = streams(fit_file([device(1, 120, 1, SERIAL, 2000, ANTPLUS)]))
        sensor = result.sensors[0]
        self.assertEqual(sensor.key, sensor_key(1, 2000, SERIAL))
        self.assertNotIn(str(SERIAL), repr(result.sensors))

    def test_a_sensor_without_a_serial_cannot_be_identified(self):
        row = device(1, 120, 1, 0xFFFFFFFF, 2000, ANTPLUS)
        result = streams(fit_file([row]))
        self.assertIs(result.hr_source, HeartRateSource.CHEST_STRAP)
        self.assertEqual(result.sensors, ())

    def test_the_same_device_keeps_its_key_across_files(self):
        first = streams(fit_file([device(1, 11, 7, SERIAL, 5, ANTPLUS)]))
        second = streams(fit_file([device(3, 3, 7, SERIAL, 5, BLE)]))
        self.assertEqual(first.sensors[0].key, second.sensors[0].key)
        other = streams(fit_file([device(1, 11, 7, SERIAL + 1, 5, ANTPLUS)]))
        self.assertNotEqual(first.sensors[0].key, other.sensors[0].key)


if __name__ == "__main__":
    unittest.main()
