import unittest
from datetime import date, datetime, timedelta, timezone
from unittest.mock import patch
from zoneinfo import ZoneInfo

from backend.errors import AppError
from backend.providers import calendar as calendar_provider
from backend.providers.calendar import (
    EXTERNAL_CALENDAR_WINDOW_DAYS,
    MAX_EXTERNAL_CALENDAR_BYTES,
    ical_duration,
    ical_no_intensity,
    ical_short_only,
    ical_training_impact,
    ical_training_relevant,
    parse_ical_calendar,
    parse_ics_date,
    parse_ics_value,
    unfold_ical,
)


def feed(*events: str) -> bytes:
    return ("BEGIN:VCALENDAR\r\nVERSION:2.0\r\n" + "".join(f"BEGIN:VEVENT\r\n{event}\r\nEND:VEVENT\r\n" for event in events) + "END:VCALENDAR\r\n").encode()


def parse(payload: bytes, *, start=date(2026, 9, 1), end=None, zone=timezone.utc):
    end = end or start + timedelta(days=EXTERNAL_CALENDAR_WINDOW_DAYS)
    return parse_ical_calendar(payload, local_zone=zone, today=start, window_start=start, window_end=end)


class CalendarProviderTests(unittest.TestCase):
    def test_timing_default_relevance_and_description_markers(self):
        events = parse(
            feed(
                "UID:family-1\r\nDTSTART;TZID=Europe/Berlin:20260902T100000\r\n"
                "DTEND;TZID=Europe/Berlin:20260902T130000\r\nSUMMARY:Family appointment",
                "UID:all-day\r\nDTSTART;VALUE=DATE:20260903\r\n"
                "DTEND;VALUE=DATE:20260904\r\nSUMMARY:Travel",
                "UID:info-only\r\nDTSTART;VALUE=DATE:20260904\r\n"
                "SUMMARY:Team info\r\nDESCRIPTION: [NO_TRAINING] Nur zur Information",
                "UID:no-intensity\r\nDTSTART;VALUE=DATE:20260905\r\n"
                "SUMMARY:Evening event\r\nDESCRIPTION: [NO_INTENSITY] Training remains possible, but easy",
                "UID:other-marker\r\nDTSTART;VALUE=DATE:20260906\r\n"
                "SUMMARY:Other marker\r\nDESCRIPTION: [OTHER_TAG] Keine besondere Wirkung",
            ),
            start=date(2026, 9, 2),
            end=date(2026, 9, 8),
            zone=ZoneInfo("Europe/Berlin"),
        )
        self.assertEqual(events[0]["duration_minutes"], 180)
        self.assertEqual(events[0]["event_date"], "2026-09-02")
        self.assertFalse(events[0]["all_day"])
        self.assertEqual(events[1]["duration_minutes"], 1440)
        self.assertTrue(events[1]["all_day"])
        self.assertFalse(events[0]["training_relevant"])
        self.assertFalse(events[1]["training_relevant"])
        self.assertFalse(events[2]["training_relevant"])
        self.assertTrue(events[3]["no_intensity"])
        self.assertTrue(events[3]["training_relevant"])
        self.assertFalse(events[3]["short_only"])
        self.assertFalse(events[4]["no_intensity"])
        self.assertTrue(events[4]["training_relevant"])
        self.assertFalse(events[4]["training_impact"])

    def test_training_markers_are_contains_matched_in_description_only(self):
        events = parse(
            feed(
                "UID:summary-only\r\nDTSTART;VALUE=DATE:20260907\r\n"
                "SUMMARY:[SHORT_ONLY] Summary only\r\nDESCRIPTION:family appointment",
                "UID:description\r\nDTSTART;VALUE=DATE:20260908\r\n"
                "SUMMARY:Family appointment\r\nDESCRIPTION:Please keep it [short_only] today",
            ),
            start=date(2026, 9, 7),
            end=date(2026, 9, 8),
        )
        self.assertFalse(events[0]["training_impact"])
        self.assertTrue(events[1]["training_impact"])
        self.assertTrue(events[1]["short_only"])

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
        self.assertEqual(len(parse_ical_calendar(feed("UID:x\r\nDTSTART:20260901T100000Z"), local_zone=timezone.utc, today=date(2026, 9, 1), window_start=date(2026, 9, 1), window_end=date(2026, 10, 27))), 1)
        with self.assertRaisesRegex(AppError, "fenster"):
            parse_ical_calendar(feed("UID:x\r\nDTSTART:20260901T100000Z"), local_zone=timezone.utc, today=date(2026, 9, 1), window_start=date(2026, 9, 1), window_end=date(2026, 10, 28))
        with self.assertRaisesRegex(AppError, "UID und DTSTART"):
            parse(feed("UID:missing"))

    def test_unfold_default_and_configurable_payload_limit(self):
        payload = b"BEGIN:VCALENDAR\r\nEND:VCALENDAR\r\n"
        self.assertEqual(MAX_EXTERNAL_CALENDAR_BYTES, 5_000_000)
        self.assertEqual(unfold_ical(payload)[0], "BEGIN:VCALENDAR")
        with self.assertRaisesRegex(AppError, "zu groß"):
            unfold_ical(payload, max_bytes=len(payload) - 1)
        folded = b"BEGIN:VCALENDAR\r\nDESCRIPTION:First\r\n continuation\r\nEND:VCALENDAR\r\n"
        self.assertIn("DESCRIPTION:Firstcontinuation", unfold_ical(folded))
        self.assertEqual(parse_ics_value(r"Name\, with\; escaped\\text"), "Name, with; escaped\\text")
        self.assertEqual(parse_ics_date("VALUE=DATE:20260901"), "2026-09-01")
        self.assertEqual(ical_duration("PT1H30M"), timedelta(hours=1, minutes=30))

    def test_daily_weekly_and_dst_keep_local_wall_time(self):
        daily = parse(feed("UID:daily\r\nDTSTART;TZID=Europe/Berlin:20261024T080000\r\nRRULE:FREQ=DAILY;COUNT=4"), start=date(2026, 10, 24), end=date(2026, 10, 30), zone=ZoneInfo("Europe/Berlin"))
        self.assertEqual([item["start_local"] for item in daily], [
            "2026-10-24T08:00:00+02:00", "2026-10-25T08:00:00+01:00", "2026-10-26T08:00:00+01:00", "2026-10-27T08:00:00+01:00"
        ])
        weekly = parse(feed("UID:weekly\r\nDTSTART:20260901T100000Z\r\nRRULE:FREQ=WEEKLY;BYDAY=MO,WE;COUNT=4"), end=date(2026, 9, 20))
        self.assertEqual([item["event_date"] for item in weekly], ["2026-09-02", "2026-09-07", "2026-09-09", "2026-09-14"])

    def test_monthly_yearly_filters_and_bounds(self):
        monthly = parse(feed("UID:monthly\r\nDTSTART:20260101T100000Z\r\nRRULE:FREQ=MONTHLY;BYDAY=MO;BYSETPOS=1;COUNT=3"), start=date(2026, 1, 1), end=date(2026, 2, 26))
        self.assertEqual([item["event_date"] for item in monthly], ["2026-01-05", "2026-02-02"])
        yearly = parse(feed("UID:yearly\r\nDTSTART:20260101T100000Z\r\nRRULE:FREQ=YEARLY;BYMONTH=9;BYMONTHDAY=15;COUNT=2"), start=date(2026, 9, 1), end=date(2026, 10, 27))
        self.assertEqual([item["event_date"] for item in yearly], ["2026-09-15"])
        over = feed("UID:many\r\nDTSTART:20260901T100000Z\r\nRRULE:FREQ=DAILY;COUNT=1001")
        with self.assertRaisesRegex(AppError, "COUNT.*zwischen"):
            parse(over, start=date(2026, 9, 1), end=date(2026, 10, 27))

    def test_week_start_and_malformed_byday_contract(self):
        weekly = feed(
            "UID:recurring\r\nDTSTART;VALUE=DATE:20260901\r\n"
            "RRULE:FREQ=WEEKLY;WKST=SU;BYDAY=TU,TH\r\nSUMMARY:Repeated"
        )
        events = parse(weekly, start=date(2026, 9, 1), end=date(2026, 9, 14))
        self.assertEqual(
            [event["event_date"] for event in events],
            ["2026-09-01", "2026-09-03", "2026-09-08", "2026-09-10"],
        )
        for malformed in (b"BYDAY=MO,", b"BYDAY=MO,,TU", b"BYDAY=,"):
            with self.assertRaises(AppError):
                parse(weekly.replace(b"BYDAY=TU,TH", malformed))

    def test_rdate_exdate_recurrence_id_and_cancelled(self):
        events = parse(feed(
            "UID:r\r\nDTSTART:20260901T100000Z\r\nRRULE:FREQ=DAILY;COUNT=4\r\nEXDATE:20260902T100000Z\r\nRDATE:20260910T100000Z",
            "UID:r\r\nRECURRENCE-ID:20260903T100000Z\r\nDTSTART:20260905T100000Z\r\nSUMMARY:moved",
            "UID:r\r\nRECURRENCE-ID:20260901T100000Z\r\nSTATUS:CANCELLED",
        ), start=date(2026, 9, 1), end=date(2026, 9, 12))
        self.assertEqual([(item["event_date"], item["name"]) for item in events], [("2026-09-04", "Privater Kalendereintrag"), ("2026-09-05", "moved"), ("2026-09-10", "Privater Kalendereintrag")])

    def test_overlapping_multiday_event_and_nested_alarm(self):
        payload = feed(
            "UID:trip\r\nDTSTART;VALUE=DATE:20260906\r\nDTEND;VALUE=DATE:20260909\r\n"
            "SUMMARY:Trip\r\nDESCRIPTION:[SHORT_ONLY]\r\nBEGIN:VALARM\r\n"
            "ACTION:DISPLAY\r\nDESCRIPTION:Reminder\r\nTRIGGER:-PT15M\r\nEND:VALARM"
        )
        events = parse(payload, start=date(2026, 9, 7), end=date(2026, 9, 10))
        self.assertEqual(len(events), 1)
        self.assertTrue(events[0]["short_only"])
        self.assertEqual(events[0]["event_date"], "2026-09-06")
        self.assertEqual(parse(payload, start=date(2026, 9, 9), end=date(2026, 9, 10)), [])

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

    def test_recurrence_iteration_caps_are_fixed_not_tautological(self):
        base = datetime(1900, 1, 1, tzinfo=timezone.utc)
        daily_rule = {"count": None, "interval": 1, "bymonth": [], "bymonthday": [], "bydays": [], "until": None}
        with patch.object(calendar_provider, "ICAL_MAX_RECURRENCE_COUNT", 2), patch.object(calendar_provider, "_ical_matches_date_filters", return_value=False):
            daily_calls = 0

            def counted_daily_shift(value, days):
                nonlocal daily_calls
                daily_calls += 1
                if daily_calls > 2 * 366 + 1:
                    raise AssertionError("daily recurrence exceeded its fixed bound")
                return value

            with patch.object(calendar_provider, "_ical_shift_local", side_effect=counted_daily_shift):
                self.assertEqual(calendar_provider._ical_daily(base, daily_rule, date(1900, 1, 1), date(9999, 12, 31)), [])
            self.assertEqual(daily_calls, 2 * 366 + 1)

        weekly_rule = {"count": None, "interval": 1, "bymonth": [], "bymonthday": [], "bydays": [], "wkst": 0, "until": None}
        with patch.object(calendar_provider, "ICAL_MAX_RECURRENCE_PERIODS", 2):
            weekly_calls = 0

            def counted_weekly_filter(*args):
                nonlocal weekly_calls
                weekly_calls += 1
                if weekly_calls > 3:
                    raise AssertionError("weekly recurrence exceeded its fixed bound")
                return False

            with patch.object(calendar_provider, "_ical_matches_date_filters", side_effect=counted_weekly_filter):
                self.assertEqual(calendar_provider._ical_weekly(base, weekly_rule, date(1900, 1, 1), date(9999, 12, 31)), [])
            self.assertEqual(weekly_calls, 3)

        period_rule = {"frequency": "MONTHLY", "count": None, "interval": 1, "bymonth": [], "bymonthday": [], "bydays": [], "bysetpos": [], "until": None}
        with patch.object(calendar_provider, "ICAL_MAX_RECURRENCE_PERIODS", 2):
            period_calls = 0

            def counted_period_dates(*args):
                nonlocal period_calls
                period_calls += 1
                if period_calls > 3:
                    raise AssertionError("period recurrence exceeded its fixed bound")
                return []

            with patch.object(calendar_provider, "_ical_period_dates", side_effect=counted_period_dates):
                self.assertEqual(calendar_provider._ical_period(base, period_rule, date(1900, 1, 1), date(9999, 12, 31)), [])
            self.assertEqual(period_calls, 3)


if __name__ == "__main__":
    unittest.main()
