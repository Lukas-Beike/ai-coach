from __future__ import annotations

import unittest
from unittest.mock import Mock

from backend.coach.structured_tool_round_assembly import (
    CoachStructuredToolRoundAssembly,
    StructuredToolRoundContract,
    StructuredToolRoundConversation,
    StructuredToolRoundRuntime,
    StructuredToolRoundServices,
    StructuredToolRoundState,
)
from backend.coach.write_gate import ImpactVerdict


class CoachStructuredToolRoundAssemblyTests(unittest.TestCase):
    def make_assembly(self):
        names = (
            "database_manager",
            "tool_names",
            "read_only_tools",
            "clarification",
            "training_patch",
            "inspector",
            "proposal_creation",
            "tool_dispatch",
            "job_store",
            "dialogue_action",
            "planning_authority",
            "training_context",
            "response",
            "response_transport",
            "limits",
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
        assembly = CoachStructuredToolRoundAssembly(
            dependencies=CoachStructuredToolRoundAssembly.Inputs(
                runtime=StructuredToolRoundRuntime(
                    database_manager=dependencies["database_manager"],
                    database_lock=lock,
                    key_value_repository=key_values,
                    root=root,
                    logger=logger,
                ),
                contract=StructuredToolRoundContract(
                    tool_names=dependencies["tool_names"],
                    read_only_tools=dependencies["read_only_tools"],
                    limits=dependencies["limits"],
                ),
                services=StructuredToolRoundServices(
                    clarification_service=dependencies["clarification"],
                    training_patch_service=dependencies["training_patch"],
                    proposal_creation_service=dependencies["proposal_creation"],
                    tool_dispatch_service=dependencies["tool_dispatch"],
                    dialogue_action_service=dependencies["dialogue_action"],
                    planning_authority_service=dependencies["planning_authority"],
                ),
                state=StructuredToolRoundState(
                    duplicate_inspector=dependencies["inspector"],
                    job_store=dependencies["job_store"],
                ),
                conversation=StructuredToolRoundConversation(
                    training_context_service=dependencies["training_context"],
                    response_service=dependencies["response"],
                    response_transport=dependencies["response_transport"],
                ),
            )
        )
        dependencies.update(
            {
                "lock": lock,
                "key_values": key_values,
                "root": root,
                "logger": logger,
                "journal_jobs": journal_jobs,
                "round_jobs": round_jobs,
            }
        )
        return assembly, dependencies

    def test_round_construction_is_lazy_then_uses_current_owner_outputs(self):
        assembly, deps = self.make_assembly()
        for name in (
            "database_manager",
            "tool_names",
            "read_only_tools",
            "clarification",
            "training_patch",
            "inspector",
            "proposal_creation",
            "tool_dispatch",
            "job_store",
            "dialogue_action",
            "planning_authority",
            "training_context",
            "response",
            "response_transport",
            "limits",
        ):
            deps[name].assert_not_called()

        service = assembly.service()

        self.assertIs(service._database_manager, deps["database_manager"])
        self.assertIs(service._database_lock, deps["lock"])
        self.assertIs(
            service._replay._database_manager, deps["database_manager"].return_value
        )
        self.assertIs(service._replay._database_lock, deps["lock"])
        self.assertIs(
            service._preparation._dialogue_action, deps["dialogue_action"].return_value
        )
        self.assertIs(
            service._execution._duplicate_inspector, deps["inspector"].return_value
        )
        self.assertIs(service._execution._key_values, deps["key_values"])
        self.assertIs(
            service._execution._training_patch, deps["training_patch"].return_value
        )
        self.assertIs(
            service._execution._tool_dispatch, deps["tool_dispatch"].return_value
        )
        self.assertIs(service._journal._job_store, deps["journal_jobs"])
        self.assertIs(service._jobs, deps["round_jobs"])
        self.assertIs(service._training_context, deps["training_context"].return_value)
        self.assertIs(service._response, deps["response"].return_value)
        self.assertIs(service._limits, deps["limits"].return_value)
        self.assertEqual(deps["database_manager"].call_count, 2)
        self.assertEqual(deps["job_store"].call_count, 2)
        self.assertEqual(deps["read_only_tools"].call_count, 3)
        self.assertEqual(deps["tool_names"].call_count, 1)

    def test_write_gate_uses_read_only_tools_logger_and_lazy_transport(self):
        assembly, deps = self.make_assembly()
        deps["response_transport"].return_value.request.return_value = {
            "output_text": '{"requests": [{"domain": "planning", '
            '"delete": false, "bulk": true}]}'
        }

        gate = assembly.service()._write_gate

        self.assertEqual(gate._read_only_tools, frozenset({"read_tool"}))
        self.assertIs(gate._logger, deps["logger"])
        deps["response_transport"].assert_not_called()
        classifier = gate._classifier_factory("synthetic-model")
        self.assertEqual(
            classifier("Plan neu aufbauen", "", ""),
            ImpactVerdict(frozenset({"planning"}), bulk=frozenset({"planning"})),
        )
        payload = deps["response_transport"].return_value.request.call_args.args[0]
        self.assertEqual(payload["model"], "synthetic-model")
        self.assertEqual(payload["reasoning"], {"effort": "low"})


if __name__ == "__main__":
    unittest.main()
