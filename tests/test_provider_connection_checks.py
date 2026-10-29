"""Provider connection checks: classification, state, probes and routes."""

import threading
import time
import unittest
from contextlib import contextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import Mock, patch

from backend.errors import AppError
from backend.http_api.provider_connections import (
    ProviderConnectionGetRoutes,
    ProviderConnectionPostRoutes,
)
from backend.providers.connection_check_probes import build_probes
from backend.providers.connection_checks import (
    ProviderConnectionChecks,
    ProviderProbe,
    classify_failure,
    simple_probe,
)
from backend.sync.garmin_assembly import GarminAssembly


def _checks(check, *, configured=True):
    state = {"identity": "a", "configured": configured}
    probe = simple_probe(
        configured=lambda: state["configured"],
        identity=lambda: state["identity"],
        check=check,
        auth_hint="Schlüssel prüfen",
    )
    clock = iter(datetime(2026, 1, 1, 12, minute, tzinfo=UTC) for minute in range(60))
    return ProviderConnectionChecks({"p": probe}, now=lambda: next(clock)), state


class ClassificationTests(unittest.TestCase):
    def test_categories(self):
        cases = [
            (AppError(502, "x", upstream_status=401), "auth_failed"),
            (AppError(502, "x", upstream_status=403), "auth_failed"),
            (AppError(401, "x", reason="reconnect_required"), "auth_failed"),
            (AppError(502, "x", upstream_status=429), "rate_limited"),
            (AppError(429, "x"), "rate_limited"),
            (AppError(502, "x", upstream_status=404), "misconfigured"),
            (AppError(502, "x", reason="check_unsupported"), "unsupported"),
            (AppError(502, "x", reason="check_scope_missing"), "scope_missing"),
            (AppError(400, "x", reason="check_misconfigured"), "misconfigured"),
            (AppError(502, "x", upstream_status=422), "misconfigured"),
            (AppError(502, "x", upstream_status=408), "unavailable"),
            (AppError(503, "x", reason="check_unreadable"), "unknown"),
            (AppError(503, "x", reason="provider_busy"), "busy"),
            (AppError(409, "x", reason="wahoo_reconnect_required"), "auth_failed"),
            (AppError(503, "x", upstream_status=503), "unavailable"),
            (AppError(502, "x", reason="provider_network_error"), "unavailable"),
        ]
        for error, expected in cases:
            with self.subTest(expected=expected, status=error.upstream_status):
                self.assertEqual(classify_failure(error), expected)


class ServiceTests(unittest.TestCase):
    def test_unconfigured_makes_no_request(self):
        check = Mock()
        checks, _ = _checks(check, configured=False)
        self.assertEqual(checks.check("p")["status"], "not_configured")
        self.assertEqual(checks.status("p")["status"], "not_configured")
        check.assert_not_called()

    def test_status_is_local_and_unchecked_until_checked(self):
        check = Mock()
        checks, _ = _checks(check)
        self.assertEqual(checks.status("p")["status"], "unchecked")
        check.assert_not_called()
        result = checks.check("p")
        self.assertEqual(result["status"], "success")
        self.assertEqual(checks.status("p"), result)
        check.assert_called_once_with()

    def test_failure_is_classified_without_error_text(self):
        secret = "synthetic-secret-token"
        checks, _ = _checks(
            Mock(side_effect=AppError(502, secret, upstream_status=401))
        )
        result = checks.check("p")
        self.assertEqual(result["status"], "auth_failed")
        self.assertEqual(result["guidance"], "Schlüssel prüfen")
        self.assertNotIn(secret, repr(result))
        unexpected, _ = _checks(Mock(side_effect=RuntimeError(secret)))
        result = unexpected.check("p")
        self.assertEqual(result["status"], "unknown")
        self.assertNotIn(secret, repr(result))

    def test_credential_change_invalidates_result(self):
        checks, state = _checks(Mock())
        checks.check("p")
        state["identity"] = "b"
        self.assertEqual(checks.status("p")["status"], "unchecked")
        state["identity"] = "a"
        self.assertEqual(checks.status("p")["status"], "unchecked")

    def test_change_during_flight_discards_result(self):
        holder = {}
        checks, state = _checks(lambda: holder["state"].update(identity="changed"))
        holder["state"] = state
        self.assertEqual(checks.check("p")["status"], "unchecked")
        self.assertEqual(checks.status("p")["status"], "unchecked")

    def test_repeated_status_reads_keep_result(self):
        checks, _ = _checks(Mock())
        first = checks.check("p")
        for _ in range(3):
            self.assertEqual(checks.status("p"), first)

    def test_concurrent_check_does_not_start_a_second_request(self):
        holder = {}
        calls = []

        def check():
            calls.append(1)
            holder["inner"] = holder["checks"].check("p")

        checks, _ = _checks(check)
        holder["checks"] = checks
        checks.check("p")
        self.assertEqual(len(calls), 1)
        self.assertEqual(holder["inner"]["status"], "checking")

    def test_busy_provider_keeps_the_previous_result(self):
        outcomes = [None, AppError(503, "x", reason="provider_busy"), None]

        def check():
            outcome = outcomes.pop(0)
            if outcome:
                raise outcome

        checks, _ = _checks(check)
        first = checks.check("p")
        self.assertEqual(first["status"], "success")
        self.assertEqual(checks.check("p")["status"], "busy")
        self.assertEqual(checks.status("p"), first)

    def test_clearing_and_re_entering_a_credential_does_not_revive_a_result(self):
        checks, state = _checks(Mock())
        checks.check("p")
        state["configured"] = False
        self.assertEqual(checks.status("p")["status"], "not_configured")
        state["configured"] = True
        self.assertEqual(checks.status("p")["status"], "unchecked")

    def test_snapshot_is_read_once_per_status(self):
        snapshot = Mock(return_value=(True, "x"))
        probe = ProviderProbe(snapshot=snapshot, check=Mock())
        checks = ProviderConnectionChecks({"p": probe})
        self.assertEqual(checks.status("p")["status"], "unchecked")
        snapshot.assert_called_once_with()

    def test_restoring_old_credentials_does_not_revive_a_result(self):
        checks, state = _checks(Mock())
        checks.check("p")
        state["identity"] = "b"
        self.assertEqual(checks.status("p")["status"], "unchecked")
        state["identity"] = "a"
        self.assertEqual(checks.status("p")["status"], "unchecked")

    def test_repeated_checks_within_the_cooldown_reuse_the_result(self):
        check = Mock()
        probe = simple_probe(configured=lambda: True, identity=lambda: "a", check=check)
        moments = iter(
            datetime(2026, 1, 1, 12, 0, second, tzinfo=UTC) for second in range(60)
        )
        checks = ProviderConnectionChecks({"p": probe}, now=lambda: next(moments))
        first = checks.check("p")
        again = checks.check("p")
        self.assertEqual(again, first)
        check.assert_called_once_with()

    def test_one_unreadable_provider_does_not_break_the_rest(self):
        def broken():
            raise RuntimeError("synthetic")

        good = simple_probe(configured=lambda: True, identity=lambda: "x", check=Mock())
        bad = simple_probe(configured=broken, identity=lambda: "x", check=Mock())
        checks = ProviderConnectionChecks({"good": good, "bad": bad})
        statuses = checks.statuses()
        self.assertEqual(statuses["good"]["status"], "unchecked")
        self.assertEqual(statuses["bad"]["status"], "unknown")
        self.assertEqual(checks.check("bad")["status"], "unknown")
        bad.check.assert_not_called()

    def test_check_that_drops_the_grant_still_reports_the_rejection(self):
        state = {"connected": True}

        def check():
            state["connected"] = False
            raise AppError(409, "x", reason="wahoo_reconnect_required")

        probe = simple_probe(
            configured=lambda: state["connected"],
            identity=lambda: "a",
            check=check,
            auth_hint="Neu verbinden",
        )
        checks = ProviderConnectionChecks({"p": probe})
        result = checks.check("p")
        self.assertEqual(result["status"], "auth_failed")
        self.assertEqual(result["guidance"], "Neu verbinden")
        self.assertEqual(checks.status("p")["status"], "not_configured")

    def test_local_failure_is_not_reported_as_a_provider_outage_and_not_stored(self):
        checks, _ = _checks(Mock(side_effect=RuntimeError("synthetic")))
        self.assertEqual(checks.check("p")["status"], "unknown")
        self.assertEqual(checks.status("p")["status"], "unchecked")

    def test_transient_failures_are_retried_inside_the_cooldown(self):
        check = Mock(side_effect=[AppError(503, "x", upstream_status=503), None])
        probe = simple_probe(configured=lambda: True, identity=lambda: "a", check=check)
        moments = iter(
            datetime(2026, 1, 1, 12, 0, second, tzinfo=UTC) for second in range(60)
        )
        checks = ProviderConnectionChecks({"p": probe}, now=lambda: next(moments))
        self.assertEqual(checks.check("p")["status"], "unavailable")
        self.assertEqual(checks.check("p")["status"], "success")

    def test_unknown_provider(self):
        checks, _ = _checks(Mock())
        with self.assertRaises(AppError) as context:
            checks.check("missing")
        self.assertEqual(context.exception.status, 404)


class ProbeTests(unittest.TestCase):
    def _probes(self, **overrides):
        config = SimpleNamespace(
            openai_api_key="sk-synthetic",
            openai_base_url="https://api.example.test/v1",
            intervals_api_key="key",
            intervals_athlete_id="i1",
            wahoo_configured=True,
            wahoo_client_id="id",
            wahoo_client_secret="secret",
        )
        values = {
            "config": lambda: config,
            "request": Mock(return_value={}),
            "default_openai_base_url": "https://default.example.test/v1",
            "intervals_get": Mock(),
            "wahoo_status": lambda: {
                "connected": True,
                "connected_at": "t1",
                "scope": "user_read workouts_read",
            },
            "wahoo_user": Mock(),
            "garmin_connected": lambda: True,
            "garmin_fingerprint": lambda: "1",
            "garmin_login": Mock(),
        }
        values.update(overrides)
        return build_probes(**values), values, config

    def test_every_probe_is_a_single_read(self):
        probes, values, _ = self._probes()
        for name in ("openai", "weather", "intervals", "wahoo", "garmin"):
            probes[name].check()
        calls = values["request"].call_args_list
        self.assertEqual([call.args[0] for call in calls], ["GET", "GET"])
        self.assertEqual(calls[0].args[1], "https://api.example.test/v1/models")
        self.assertIn("api.open-meteo.com", calls[1].args[1])
        values["intervals_get"].assert_called_once_with("/athlete/i1")
        values["wahoo_user"].assert_called_once_with()
        values["garmin_login"].assert_called_once_with()

    def test_openai_models_not_found_is_unsupported(self):
        request = Mock(side_effect=AppError(502, "x", upstream_status=404))
        probes, _, _ = self._probes(request=request)
        self.assertEqual(
            ProviderConnectionChecks(probes).check("openai")["status"], "unsupported"
        )

    def test_invalid_openai_base_url_is_misconfiguration_without_a_request(self):
        probes, values, config = self._probes()
        config.openai_base_url = "https://user:pw@api.example.test/v1"
        result = ProviderConnectionChecks(probes).check("openai")
        self.assertEqual(result["status"], "misconfigured")
        values["request"].assert_not_called()

    def test_garmin_identity_changes_with_each_connection(self):
        generation = {"value": "1"}
        probes, _, _ = self._probes(garmin_fingerprint=lambda: generation["value"])
        before = probes["garmin"].snapshot()[1]
        generation["value"] = "2"
        self.assertNotEqual(before, probes["garmin"].snapshot()[1])

    def test_openai_check_uses_the_trimmed_key_and_its_own_service_label(self):
        probes, values, config = self._probes()
        config.openai_api_key = "sk-synthetic \n"
        probes["openai"].check()
        call = values["request"].call_args
        self.assertEqual(call.kwargs["headers"]["Authorization"], "Bearer sk-synthetic")
        self.assertEqual(call.kwargs["service"], "openai-check")

    def test_wahoo_identity_changes_on_reconnect(self):
        state = {"connected": True, "connected_at": "t1"}
        probes, _, _ = self._probes(wahoo_status=lambda: state)
        before = probes["wahoo"].snapshot()[1]
        state["connected_at"] = "t2"
        self.assertNotEqual(before, probes["wahoo"].snapshot()[1])

    def test_other_provider_404_is_a_misconfiguration_not_unsupported(self):
        request = Mock(side_effect=AppError(502, "x", upstream_status=404))
        probes, _, _ = self._probes(request=request)
        self.assertEqual(
            ProviderConnectionChecks(probes).check("weather")["status"], "misconfigured"
        )

    def test_wahoo_grant_without_user_read_is_unsupported_not_rejected(self):
        probes, values, _ = self._probes(
            wahoo_status=lambda: {
                "connected": True,
                "connected_at": "t1",
                "scope": "workouts_read",
            }
        )
        self.assertEqual(
            ProviderConnectionChecks(probes).check("wahoo")["status"], "scope_missing"
        )
        values["wahoo_user"].assert_not_called()

    def test_openai_forbidden_models_listing_is_a_rejection(self):
        request = Mock(side_effect=AppError(502, "x", upstream_status=403))
        probes, _, _ = self._probes(request=request)
        self.assertEqual(
            ProviderConnectionChecks(probes).check("openai")["status"], "auth_failed"
        )

    def test_unknown_intervals_athlete_is_a_misconfiguration(self):
        probes, _, _ = self._probes(
            intervals_get=Mock(side_effect=AppError(502, "x", upstream_status=404))
        )
        self.assertEqual(
            ProviderConnectionChecks(probes).check("intervals")["status"],
            "misconfigured",
        )

    def test_openai_auth_failure(self):
        request = Mock(side_effect=AppError(502, "x", upstream_status=401))
        probes, _, _ = self._probes(request=request)
        self.assertEqual(
            ProviderConnectionChecks(probes).check("openai")["status"], "auth_failed"
        )

    def test_configuration_signals(self):
        probes, _, config = self._probes(
            wahoo_status=lambda: {"connected": False, "connected_at": None}
        )
        self.assertFalse(probes["wahoo"].snapshot()[0])
        self.assertTrue(probes["weather"].snapshot()[0])
        config.openai_api_key = " "
        self.assertFalse(probes["openai"].snapshot()[0])
        config.intervals_athlete_id = ""
        self.assertFalse(probes["intervals"].snapshot()[0])

    def test_identity_changes_with_credentials(self):
        probes, _, config = self._probes()
        before = probes["openai"].snapshot()[1]
        config.openai_api_key = "sk-other"
        self.assertNotEqual(before, probes["openai"].snapshot()[1])


class RouteTests(unittest.TestCase):
    def test_status_requires_auth_and_is_local(self):
        auth = Mock()
        auth.require_auth.side_effect = AppError(401, "no")
        checks = Mock()
        routes = ProviderConnectionGetRoutes(lambda: auth, lambda: checks)
        handler = Mock()
        with self.assertRaises(AppError):
            routes.handle(handler, "/api/providers/connections")
        checks.statuses.assert_not_called()
        auth.require_auth.side_effect = None
        checks.statuses.return_value = {"openai": {"status": "unchecked"}}
        self.assertTrue(routes.handle(handler, "/api/providers/connections"))
        checks.check.assert_not_called()
        handler.send_json.assert_called_once_with(
            200, {"providers": {"openai": {"status": "unchecked"}}}
        )
        self.assertFalse(routes.handle(handler, "/api/other"))

    def test_check_dispatch_and_unknown_provider(self):
        checks = Mock()
        checks.providers.return_value = ("openai",)
        checks.check.return_value = {"status": "success", "checked_at": "t"}
        routes = ProviderConnectionPostRoutes(lambda: checks)
        handler = Mock()
        self.assertTrue(routes.handle(handler, "/api/providers/openai/check"))
        checks.check.assert_called_once_with("openai")
        handler.read_json.reset_mock()
        with self.assertRaises(AppError):
            routes.handle(handler, "/api/providers/nope/check")
        handler.read_json.assert_called_once_with()
        self.assertFalse(routes.handle(handler, "/api/nutrition/yazio/check"))


if __name__ == "__main__":
    unittest.main()


class RotationAndDeadlineTests(unittest.TestCase):
    def test_check_that_rotates_its_own_identity_keeps_its_success(self):
        state = {"identity": "before"}

        def check():
            state["identity"] = "after"
            return "after"

        probe = simple_probe(
            configured=lambda: True, identity=lambda: state["identity"], check=check
        )
        checks = ProviderConnectionChecks({"p": probe})
        self.assertEqual(checks.check("p")["status"], "success")
        self.assertEqual(checks.status("p")["status"], "success")

    def test_restore_during_the_check_is_not_stored_as_verified(self):
        state = {"identity": "before"}

        def check():
            state["identity"] = "restored"
            return "verified-before-restore"

        probe = simple_probe(
            configured=lambda: True, identity=lambda: state["identity"], check=check
        )
        checks = ProviderConnectionChecks({"p": probe})
        self.assertEqual(checks.check("p")["status"], "unchecked")
        self.assertEqual(checks.status("p")["status"], "unchecked")

    def test_a_check_past_its_deadline_reports_checking_and_still_stores_its_result(
        self,
    ):
        release = threading.Event()

        def check():
            release.wait(5)

        probe = simple_probe(configured=lambda: True, identity=lambda: "a", check=check)
        checks = ProviderConnectionChecks({"p": probe}, deadline_seconds=0.05)
        self.assertEqual(checks.check("p")["status"], "checking")
        self.assertEqual(checks.check("p")["status"], "checking")
        release.set()
        for _ in range(200):
            if checks.status("p")["status"] == "success":
                break
            time.sleep(0.01)
        self.assertEqual(checks.status("p")["status"], "success")


class GarminCheckGuardTests(unittest.TestCase):
    def _assembly(self, operation):
        assembly = object.__new__(GarminAssembly)
        coordination = Mock()
        coordination.operation = operation
        reader = Mock()
        with (
            patch.object(
                GarminAssembly, "_sync_coordination", return_value=coordination
            ),
            patch.object(GarminAssembly, "remote_reader", return_value=reader),
            patch.object(
                GarminAssembly,
                "fixture_loader",
                return_value=Mock(path=Mock(return_value=None)),
            ),
        ):
            yield assembly, coordination, reader

    def test_running_resync_reports_busy_and_skips_the_login(self):
        @contextmanager
        def operation():
            raise AppError(409, "Resync läuft", reason="provider_resync_running")
            yield

        for assembly, _coordination, reader in self._assembly(operation):
            checks = ProviderConnectionChecks(
                {
                    "garmin": simple_probe(
                        configured=lambda: True,
                        identity=lambda: "x",
                        check=assembly.check_stored_login,
                    )
                }
            )
            self.assertEqual(checks.check("garmin")["status"], "busy")
            reader.check_stored_login.assert_not_called()

    def test_running_sync_reports_busy(self):
        @contextmanager
        def operation():
            yield

        for assembly, coordination, reader in self._assembly(operation):
            coordination.acquire.return_value = False
            with self.assertRaises(AppError) as context:
                assembly.check_stored_login()
            self.assertEqual(context.exception.reason, "provider_busy")
            reader.check_stored_login.assert_not_called()

    def test_idle_garmin_runs_the_login_and_releases_the_guard(self):
        @contextmanager
        def operation():
            yield

        for assembly, coordination, reader in self._assembly(operation):
            coordination.acquire.return_value = True
            assembly.check_stored_login()
            reader.check_stored_login.assert_called_once_with()
            coordination.release.assert_called_once_with()
