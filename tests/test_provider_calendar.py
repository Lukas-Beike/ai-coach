import unittest
from datetime import date, timedelta, timezone
from zoneinfo import ZoneInfo

from backend.errors import AppError
from backend.providers.calendar import (
    EXTERNAL_CALENDAR_WINDOW_DAYS,
    MAX_EXTERNAL_CALENDAR_BYTES,
    ical_no_intensity,
    ical_short_only,
    ical_training_impact,
    ical_training_relevant,
    parse_ical_calendar,
)


def feed(*events: str) -> bytes:
    return ("BEGIN:VCALENDAR\r\nVERSION:2.0\r\n" + "".join(f"BEGIN:VEVENT\r\n{event}\r\nEND:VEVENT\r\n" for event in events) + "END:VCALENDAR\r\n").encode()


def parse(payload: bytes, *, start=date(2026, 9, 1), end=None, zone=timezone.utc):
    end = end or start + timedelta(days=EXTERNAL_CALENDAR_WINDOW_DAYS)
    return parse_ical_calendar(payload, local_zone=zone, today=start, window_start=start, window_end=end)


class CalendarProviderTests(unittest.TestCase):
    def test_normal_all_day_duration_and_markers(self):
        events = parse(feed(
            "UID:all-day\r\nDTSTART;VALUE=DATE:20260902\r\nDTEND;VALUE=DATE:20260904\r\nSUMMARY:Race\r\nDESCRIPTION:note [NO_INTENSITY] [SHORT_ONLY]",
            "UID:duration\r\nDTSTART:20260903T100000Z\r\nDURATION:PT90M\r\nSUMMARY:Workout\r\nDESCRIPTION:[NO_TRAINING]",
        ))
        self.assertEqual([item["duration_minutes"] for item in events], [2880, 90])
        self.assertTrue(events[0]["all_day"])
        self.assertTrue(events[0]["training_impact"])
        self.assertTrue(events[0]["training_relevant"])
        self.assertTrue(events[0]["no_intensity"])
        self.assertTrue(events[0]["short_only"])
        self.assertFalse(events[1]["training_relevant"])

    def test_timezone_and_unknown_tzid_fallback_to_local_zone(self):
        events = parse(feed(
            "UID:zone\r\nDTSTART;TZID=Europe/Berlin:20260902T100000\r\nDTEND;TZID=Europe/Berlin:20260902T110000\r\nSUMMARY:Berlin",
            "UID:fallback\r\nDTSTART;TZID=Not/AZone:20260902T100000\r\nSUMMARY:Fallback",
        ), zone=ZoneInfo("America/New_York"))
        self.assertEqual(events[0]["start_local"], "2026-09-02T04:00:00-04:00")
        self.assertEqual(events[1]["start_local"], "2026-09-02T10:00:00-04:00")

    def test_malformed_structure_utf8_and_limits(self):
        with self.assertRaisesRegex(AppError, "vollständiges"):
            parse_ical_calendar(b"BEGIN:VCALENDAR\r\n", local_zone=timezone.utc, today=date(2026, 9, 1))
        with self.assertRaisesRegex(AppError, "UTF-8"):
            parse_ical_calendar(b"\xff", local_zone=timezone.utc, today=date(2026, 9, 1))
        with self.assertRaisesRegex(AppError, "zu groß"):
            parse_ical_calendar(b"x" * (MAX_EXTERNAL_CALENDAR_BYTES + 1), local_zone=timezone.utc, today=date(2026, 9, 1))
        with self.assertRaisesRegex(AppError, "fenster"):
            parse_ical_calendar(feed("UID:x\r\nDTSTART:20260901T100000Z"), local_zone=timezone.utc, today=date(2026, 9, 1), window_end=date(2027, 1, 1))
        with self.assertRaisesRegex(AppError, "UID und DTSTART"):
            parse(feed("UID:missing"))

    def test_daily_weekly_and_dst_keep_local_wall_time(self):
        daily = parse(feed("UID:daily\r\nDTSTART;TZID=Europe/Berlin:20261024T080000\r\nRRULE:FREQ=DAILY;COUNT=4"), start=date(2026, 10, 24), end=date(2026, 10, 30), zone=ZoneInfo("Europe/Berlin"))
        self.assertEqual([item["start_local"] for item in daily], [
            "2026-10-24T08:00:00+02:00", "2026-10-25T08:00:00+01:00", "2026-10-26T08:00:00+01:00", "2026-10-27T08:00:00+01:00"
        ])
        weekly = parse(feed("UID:weekly\r\nDTSTART:20260901T100000Z\r\nRRULE:FREQ=WEEKLY;BYDAY=MO,WE;COUNT=4"), end=date(2026, 9, 20))
        self.assertEqual([item["event_date"] for item in weekly], ["2026-09-02", "2026-09-07", "2026-09-09", "2026-09-14"])

    def test_monthly_yearly_filters_and_bounds(self):
        monthly = parse(feed("UID:monthly\r\nDTSTART:20260101T100000Z\r\nRRULE:FREQ=MONTHLY;BYDAY=MO;BYSETPOS=1;COUNT=3"), start=date(2026, 1, 1), end=date(2026, 4, 30))
        self.assertEqual([item["event_date"] for item in monthly], ["2026-01-05", "2026-02-02", "2026-03-02"])
        yearly = parse(feed("UID:yearly\r\nDTSTART:20260101T100000Z\r\nRRULE:FREQ=YEARLY;BYMONTH=9;BYMONTHDAY=15;COUNT=2"), start=date(2026, 9, 1), end=date(2026, 12, 29))
        self.assertEqual([item["event_date"] for item in yearly], ["2026-09-15"])
        over = feed("UID:many\r\nDTSTART:20260901T100000Z\r\nRRULE:FREQ=DAILY;COUNT=1001")
        with self.assertRaisesRegex(AppError, "COUNT.*zwischen"):
            parse(over, start=date(2026, 9, 1), end=date(2026, 12, 1))

    def test_rdate_exdate_recurrence_id_and_cancelled(self):
        events = parse(feed(
            "UID:r\r\nDTSTART:20260901T100000Z\r\nRRULE:FREQ=DAILY;COUNT=4\r\nEXDATE:20260902T100000Z\r\nRDATE:20260910T100000Z",
            "UID:r\r\nRECURRENCE-ID:20260903T100000Z\r\nDTSTART:20260905T100000Z\r\nSUMMARY:moved",
            "UID:r\r\nRECURRENCE-ID:20260901T100000Z\r\nSTATUS:CANCELLED",
        ), start=date(2026, 9, 1), end=date(2026, 9, 12))
        self.assertEqual([(item["event_date"], item["name"]) for item in events], [("2026-09-04", "Privater Kalendereintrag"), ("2026-09-05", "moved"), ("2026-09-10", "Privater Kalendereintrag")])

    def test_unsupported_rules_and_markers(self):
        with self.assertRaisesRegex(AppError, "nicht unterstützt"):
            parse(feed("UID:x\r\nDTSTART:20260901T100000Z\r\nRRULE:FREQ=HOURLY"))
        with self.assertRaisesRegex(AppError, "BYDAY"):
            parse(feed("UID:x\r\nDTSTART:20260901T100000Z\r\nRRULE:FREQ=DAILY;BYDAY=2MO"))
        self.assertTrue(ical_training_impact("before [short_only]"))
        self.assertTrue(ical_training_relevant("anything"))
        self.assertFalse(ical_training_relevant("[NO_TRAINING]"))
        self.assertTrue(ical_no_intensity("x [NO_INTENSITY] y"))
        self.assertFalse(ical_short_only("x"))


if __name__ == "__main__":
    unittest.main()
