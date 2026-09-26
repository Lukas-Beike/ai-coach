from __future__ import annotations

import unittest
from unittest.mock import Mock

from backend.coach.structured_tool_round_assembly import CoachStructuredToolRoundAssembly


class CoachStructuredToolRoundAssemblyTests(unittest.TestCase):
    def make_assembly(self):
        names = (
            "database_manager", "tool_names", "read_only_tools", "clarification",
            "training_patch", "sync_state", "proposal_creation", "tool_dispatch",
            "job_store", "dialogue_action",
            "planning_authority", "training_context", "response", "limits",
        )
        dependencies = {name: Mock(name=name) for name in names}
        journal_jobs = Mock(name="journal_jobs")
        round_jobs = Mock(name="round_jobs")
        dependencies["job_store"].side_effect = [journal_jobs, round_jobs]
        dependencies["tool_names"].return_value = ["read_tool"]
        dependencies["read_only_tools"].return_value = ["read_tool"]
        lock = Mock(name="database_lock")
        key_values = Mock(name="key_values")
        logger = Mock(name="logger")
        root = Mock(name="repository_root")
        sync_defaults = {"intervals": 30}
        assembly = CoachStructuredToolRoundAssembly(
            database_manager=dependencies["database_manager"],
            database_lock=lock,
            key_value_repository=key_values,
            root=root,
            logger=logger,
            tool_names=dependencies["tool_names"],
            read_only_tools=dependencies["read_only_tools"],
            sync_period_defaults=sync_defaults,
            all_sync_days=3650,
            clarification_service=dependencies["clarification"],
            training_patch_service=dependencies["training_patch"],
            sync_state_repository=dependencies["sync_state"],
            proposal_creation_service=dependencies["proposal_creation"],
            tool_dispatch_service=dependencies["tool_dispatch"],
            job_store=dependencies["job_store"],
            dialogue_action_service=dependencies["dialogue_action"],
            planning_authority_service=dependencies["planning_authority"],
            training_context_service=dependencies["training_context"],
            response_service=dependencies["response"],
            tool_round_limits=dependencies["limits"],
        )
        dependencies.update({
            "lock": lock, "key_values": key_values, "root": root, "logger": logger,
            "sync_defaults": sync_defaults, "journal_jobs": journal_jobs,
            "round_jobs": round_jobs,
        })
        return assembly, dependencies

    def test_round_construction_is_lazy_then_uses_current_owner_outputs(self):
        assembly, deps = self.make_assembly()
        for name in (
            "database_manager", "tool_names", "read_only_tools", "clarification",
            "training_patch", "sync_state", "proposal_creation", "tool_dispatch",
            "job_store", "dialogue_action",
            "planning_authority", "training_context", "response", "limits",
        ):
            deps[name].assert_not_called()

        service = assembly.service()

        self.assertIs(service._database_manager, deps["database_manager"])
        self.assertIs(service._database_lock, deps["lock"])
        self.assertIs(service._replay._database_manager, deps["database_manager"].return_value)
        self.assertIs(service._replay._database_lock, deps["lock"])
        self.assertIs(service._preparation._dialogue_action, deps["dialogue_action"].return_value)
        self.assertIs(service._preparation._sync_state, deps["sync_state"].return_value)
        self.assertIs(service._execution._key_values, deps["key_values"])
        self.assertIs(service._execution._training_patch, deps["training_patch"].return_value)
        self.assertIs(service._execution._tool_dispatch, deps["tool_dispatch"].return_value)
        self.assertIs(service._journal._job_store, deps["journal_jobs"])
        self.assertIs(service._jobs, deps["round_jobs"])
        self.assertIs(service._training_context, deps["training_context"].return_value)
        self.assertIs(service._response, deps["response"].return_value)
        self.assertIs(service._limits, deps["limits"].return_value)
        self.assertEqual(deps["database_manager"].call_count, 2)
        self.assertEqual(deps["job_store"].call_count, 2)
        self.assertEqual(deps["read_only_tools"].call_count, 2)
        self.assertEqual(deps["tool_names"].call_count, 1)


if __name__ == "__main__":
    unittest.main()
