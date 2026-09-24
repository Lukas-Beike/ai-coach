import json
import sqlite3
import unittest
from contextlib import contextmanager
from datetime import date, datetime, timezone

from backend.athlete.profile import ProfileService
from backend.db.repositories import KeyValueRepository, ProfileRepository
from backend.errors import AppError
from backend.runtime.maintenance import MaintenanceGate
from backend.weather import cache
from backend.weather.service import (
    WeatherCacheStore,
    WeatherRefreshJournal,
    WeatherService,
)


class DatabaseManager:
    def __init__(self):
        self.connection = sqlite3.connect(":memory:")
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript(
            """
            CREATE TABLE kv (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE change_history (
                id TEXT PRIMARY KEY,
                entity_type TEXT,
                entity_id TEXT,
                action TEXT,
                source TEXT,
                created_at TEXT,
                before_hash TEXT,
                after_hash TEXT,
                diff TEXT
            );
            """
        )
        self._current = None

    @contextmanager
    def unit_of_work(self):
        if self._current is not None:
            yield self._current
            return
        self._current = self.connection
        try:
            yield self.connection
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise
        finally:
            self._current = None


class Client:
    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error
        self.calls = []

    def fetch(self, query):
        self.calls.append(query)
        if self.error:
            raise self.error
        return self.result


class Tracker:
    def __init__(self, connection):
        self.connection = connection
        self.events = []

    def start(self, provider, area, operation_id, trigger):
        self.events.append(("start", provider, area, operation_id, trigger))
        return "refresh-1"

    def finish(self, refresh_id, status, phase, *, error_code=None):
        if self.connection.in_transaction:
            raise AssertionError("refresh event published before weather commit")
        self.events.append(("finish", refresh_id, status, phase, error_code))

    @staticmethod
    def error_code(_error):
        return "provider_error"


class Context:
    @staticmethod
    def get():
        return {"operation_id": "operation-1", "trigger": "manual"}


class Logger:
    def __init__(self):
        self.calls = []

    def warning(self, message, **kwargs):
        self.calls.append((message, kwargs))


class WeatherServiceTests(unittest.TestCase):
    def setUp(self):
        self.manager = DatabaseManager()
        self.addCleanup(self.manager.connection.close)
        self.now = datetime(2026, 9, 20, 12, tzinfo=timezone.utc)
        self.key_values = KeyValueRepository(lambda: self.now.isoformat())
        self.profile = ProfileService(
            self.manager, ProfileRepository(self.key_values), self.key_values
        )
        self.profile.save({"weather_location": "Berlin"})
        self.tracker = Tracker(self.manager.connection)
        self.logger = Logger()

    def service(self, client):
        return WeatherService(
            WeatherCacheStore(self.manager, self.key_values, self.profile),
            lambda: client,
            WeatherRefreshJournal(
                self.tracker, Context(), lambda: "generated-operation", self.logger
            ),
            MaintenanceGate(),
            lambda: self.now,
            lambda: date(2026, 9, 20),
        )

    def get(self, key):
        with self.manager.unit_of_work() as db:
            return self.key_values.get(db, key)

    def test_refresh_commits_cache_history_and_events_in_order(self):
        refreshed = {
            "query": "Berlin",
            "location": {"name": "Berlin"},
            "forecast": {"daily": {"time": ["2026-09-20"]}},
            "fetched_at": self.now.isoformat(),
        }
        result = self.service(Client(refreshed)).state([])

        self.assertEqual(result["state"], "ready")
        self.assertTrue(result["_refreshed"])
        self.assertEqual(json.loads(self.get(cache.CACHE_KEY)), refreshed)
        self.assertEqual(
            self.tracker.events,
            [
                ("start", "weather", "forecast", "operation-1", "manual"),
                ("finish", "refresh-1", "success", "complete", None),
            ],
        )

    def test_location_change_discards_refresh_after_commit(self):
        client = Client({"query": "Berlin", "forecast": {}})
        service = self.service(client)

        def changed_fetch(query):
            self.profile.save({"weather_location": ""})
            return {"query": query, "forecast": {}, "fetched_at": self.now.isoformat()}

        client.fetch = changed_fetch
        result = service.state()

        self.assertEqual(result["state"], "not_configured")
        self.assertEqual(self.get(cache.CACHE_KEY), "")
        self.assertEqual(
            self.tracker.events[-1],
            ("finish", "refresh-1", "skipped", "location_changed", None),
        )

    def test_cache_and_history_writes_roll_back_together(self):
        old_cache = {"query": "Berlin", "forecast": {"daily": {"time": []}}}
        old_history = {"2026-09-19": {"date": "2026-09-19"}}
        with self.manager.unit_of_work() as db:
            self.key_values.set(db, cache.CACHE_KEY, json.dumps(old_cache))
            self.key_values.set(db, cache.HISTORY_KEY, json.dumps(old_history))

        class FailingRepository:
            def get(_, db, key):
                return self.key_values.get(db, key)

            def set(_, db, key, value):
                if key == cache.CACHE_KEY:
                    raise RuntimeError("simulated cache write failure")
                self.key_values.set(db, key, value)

        store = WeatherCacheStore(self.manager, FailingRepository(), self.profile)
        state = cache.cache_state(
            "Berlin",
            json.dumps(old_cache),
            "",
            now=self.now,
        )
        with self.assertRaisesRegex(RuntimeError, "simulated"):
            store.store_refresh(
                state,
                {
                    "query": "Berlin",
                    "forecast": {"daily": {"time": ["2026-09-20"]}},
                    "fetched_at": self.now.isoformat(),
                },
            )

        self.assertEqual(json.loads(self.get(cache.CACHE_KEY)), old_cache)
        self.assertEqual(json.loads(self.get(cache.HISTORY_KEY)), old_history)

    def test_failure_is_persisted_before_error_event_and_retry_is_bounded(self):
        client = Client(error=AppError(503, "upstream"))
        service = self.service(client)

        first = service.state()
        second = service.state()

        self.assertEqual(first["state"], "error")
        self.assertIn("noch nicht erneut", second["error"])
        self.assertEqual(client.calls, ["Berlin"])
        self.assertEqual(json.loads(self.get(cache.FAILURE_KEY))["count"], 1)
        self.assertEqual(
            self.tracker.events[-1][2:], ("error", "failed", "provider_error")
        )
        self.assertEqual(len(self.logger.calls), 1)

    def test_local_read_does_not_fetch_and_uses_cached_projection(self):
        client = Client(error=AssertionError("must not fetch"))
        loading = self.service(client).state(refresh=False)
        self.assertTrue(loading["loading"])

        cached = {
            "query": "Berlin",
            "location": {"name": "Berlin"},
            "forecast": {"daily": {"time": ["2026-09-20"]}},
            "fetched_at": self.now.isoformat(),
        }
        with self.manager.unit_of_work() as db:
            self.key_values.set(db, cache.CACHE_KEY, json.dumps(cached))
        ready = self.service(client).state(refresh=False)
        self.assertEqual(ready["state"], "ready")
        self.assertEqual(client.calls, [])


if __name__ == "__main__":
    unittest.main()
