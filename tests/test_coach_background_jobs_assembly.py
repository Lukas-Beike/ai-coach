from __future__ import annotations

import unittest
from unittest.mock import Mock

from backend.coach.background_jobs_assembly import (
    CoachBackgroundJobsAssembly,
    CoachJobAthleteServices,
    CoachJobLimits,
    CoachJobPersistence,
    CoachJobTurnServices,
    CoachJobWorkerRuntime,
)


class CoachBackgroundJobsAssemblyTests(unittest.TestCase):
    def make_assembly(self):
        names = (
            "database_manager",
            "worker",
            "maintenance",
            "settings",
            "streams",
            "sessions",
            "chat_turn",
            "morning",
            "quick_actions",
            "clock",
            "horizon",
            "storage_limit",
            "read_only_tools",
        )
        deps = {name: Mock(name=name) for name in names}
        manager = Mock(name="manager")
        lock = Mock(name="lock")
        chat_repository = Mock(name="chat_repository")
        key_values = Mock(name="key_values")
        events = Mock(name="events")
        redactor = Mock(name="redactor")
        root = Mock(name="root")
        logger = Mock(name="logger")
        stream_registry = Mock(name="stream_registry")
        worker = Mock(name="worker")
        maintenance = Mock(name="maintenance_gate")
        athlete_clock = Mock(name="athlete_clock")
        deps["database_manager"].return_value = manager
        deps["read_only_tools"].return_value = {"read_tool"}
        deps["worker"].return_value = worker
        deps["maintenance"].return_value = maintenance
        deps["streams"].return_value = stream_registry
        deps["clock"].return_value = athlete_clock
        deps["horizon"].return_value = 30
        deps["storage_limit"].return_value = 1024
        assembly = CoachBackgroundJobsAssembly(
            dependencies=CoachBackgroundJobsAssembly.Inputs(
                persistence=CoachJobPersistence(
                    database_manager=deps["database_manager"],
                    database_lock=lock,
                    chat_repository=chat_repository,
                    key_value_repository=key_values,
                    event_buffer=events,
                ),
                worker=CoachJobWorkerRuntime(
                    worker_wake_event=deps["worker"],
                    maintenance_gate=deps["maintenance"],
                    utc_now=Mock(name="utc_now"),
                    redactor=redactor,
                    repository_root=root,
                    logger=logger,
                ),
                turn=CoachJobTurnServices(
                    read_only_tools=deps["read_only_tools"],
                    settings=deps["settings"],
                    stream_registry=deps["streams"],
                    session_auth_service=deps["sessions"],
                    chat_turn_service=deps["chat_turn"],
                ),
                athlete=CoachJobAthleteServices(
                    manual_morning_checkin_service=deps["morning"],
                    quick_actions_service=deps["quick_actions"],
                    athlete_clock=deps["clock"],
                ),
                limits=CoachJobLimits(
                    background_horizon_days=deps["horizon"],
                    max_attachment_storage_bytes=deps["storage_limit"],
                ),
            )
        )
        deps.update(
            {
                "manager": manager,
                "lock": lock,
                "chat_repository": chat_repository,
                "key_values": key_values,
                "events": events,
                "redactor": redactor,
                "root": root,
                "logger": logger,
                "stream_registry": stream_registry,
                "worker_value": worker,
                "maintenance_value": maintenance,
                "athlete_clock_value": athlete_clock,
            }
        )
        return assembly, deps

    def test_job_services_resolve_current_worker_limits_and_stream_owner(self):
        assembly, deps = self.make_assembly()

        store = assembly.job_store()
        submission = assembly.job_submission_service()
        cancellation = assembly.cancellation_service()

        self.assertIs(store._database_manager, deps["database_manager"])
        self.assertIs(store._database_lock, deps["lock"])
        self.assertIs(store._wake_event, deps["worker_value"])
        self.assertIs(store._maintenance_gate, deps["maintenance_value"])
        self.assertIs(submission._stream_registry, deps["stream_registry"])
        self.assertIs(submission._wake_event, deps["worker_value"])
        self.assertEqual(submission._background_horizon_days, 30)
        self.assertEqual(submission._max_attachment_storage_bytes, 1024)
        self.assertIs(cancellation._streams, deps["stream_registry"])

    def test_runner_keeps_chat_and_recovery_factories_lazy(self):
        assembly, deps = self.make_assembly()

        runner = assembly.background_job_runner()

        self.assertIs(runner._chat_turn, deps["chat_turn"])
        self.assertIs(runner._sessions, deps["sessions"])
        self.assertIs(runner._streams, deps["stream_registry"])
        self.assertIs(runner._maintenance, deps["maintenance_value"])
        self.assertIs(runner._morning, deps["morning"])
        self.assertIs(runner._failures.__self__, assembly)
        deps["chat_turn"].assert_not_called()
        deps["sessions"].assert_not_called()
        deps["morning"].assert_not_called()

    def test_turn_failure_keeps_shared_storage_and_event_owners(self):
        assembly, deps = self.make_assembly()

        failure = assembly.turn_failure_service()

        self.assertIs(failure._deps.database_manager, deps["database_manager"])
        self.assertIs(failure._deps.database_lock, deps["lock"])
        self.assertIs(failure._deps.chat_repository, deps["chat_repository"])
        self.assertIs(failure._deps.key_values, deps["key_values"])
        self.assertIs(failure._deps.event_buffer, deps["events"])
        self.assertIs(failure._deps.redactor, deps["redactor"])
        self.assertIs(failure._deps.repository_root, deps["root"])


if __name__ == "__main__":
    unittest.main()
