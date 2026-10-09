from __future__ import annotations

import unittest
from unittest.mock import Mock

from backend.coach.turn_assembly import (
    ChatEntryServices,
    CoachTurnAssembly,
    StructuredTurnControlServices,
    StructuredTurnDialogueServices,
    TurnLifecycle,
    TurnPersistence,
)


class CoachTurnAssemblyTests(unittest.TestCase):
    def make_assembly(self):
        names = (
            "database_manager",
            "attachments",
            "dialogue",
            "payload",
            "transport",
            "rounds",
            "jobs",
            "failure",
            "conversation",
        )
        deps = {name: Mock(name=name) for name in names}
        manager = Mock(name="manager")
        lock = Mock(name="lock")
        chat_repository = Mock(name="chat_repository")
        key_values = Mock(name="key_values")
        events = Mock(name="events")
        logger = Mock(name="logger")
        settings = Mock(name="settings")
        conversation_gate = Mock(name="conversation_gate")
        maintenance_gate = Mock(name="maintenance_gate")
        tools = [{"name": "read_tool"}]
        read_only_tools = {"read_tool"}
        conversation_service = Mock(name="conversation_service")
        deps["database_manager"].return_value = manager
        deps["conversation"].return_value = conversation_service
        deps["tool_dispatch"] = Mock(name="tool_dispatch")
        assembly = CoachTurnAssembly(
            dependencies=CoachTurnAssembly.Inputs(
                persistence=TurnPersistence(
                    database_manager=deps["database_manager"],
                    database_lock=lock,
                    chat_repository=chat_repository,
                    key_value_repository=key_values,
                    event_buffer=events,
                    utc_now=Mock(name="utc_now"),
                    uuid_factory=Mock(name="uuid_factory"),
                ),
                lifecycle=TurnLifecycle(
                    root=Mock(name="root"),
                    logger=logger,
                    conversation_gate=conversation_gate,
                    maintenance_gate=maintenance_gate,
                ),
                chat_entry=ChatEntryServices(
                    settings=settings,
                    conversation_provision_service=deps["conversation"],
                ),
                dialogue=StructuredTurnDialogueServices(
                    attachment_context_service=deps["attachments"],
                    dialogue_read_service=deps["dialogue"],
                    request_payload_service=deps["payload"],
                    response_transport=deps["transport"],
                    tool_round_service=deps["rounds"],
                ),
                controls=StructuredTurnControlServices(
                    tools=lambda: tools,
                    read_only_tools=lambda: read_only_tools,
                    job_store=deps["jobs"],
                    turn_failure_service=deps["failure"],
                    tool_dispatch_service=deps["tool_dispatch"],
                ),
            )
        )
        return (
            assembly,
            deps,
            {
                "manager": manager,
                "lock": lock,
                "settings": settings,
                "conversation_gate": conversation_gate,
                "maintenance_gate": maintenance_gate,
                "conversation_service": conversation_service,
            },
        )

    def test_chat_turn_keeps_structured_turn_lazy_and_current_conversation_owner(self):
        assembly, deps, owners = self.make_assembly()

        service = assembly.chat_turn_service()

        self.assertIs(service._database_manager, deps["database_manager"])
        self.assertIs(service._database_lock, owners["lock"])
        self.assertIs(service._receipts._manager_factory, deps["database_manager"])
        self.assertIs(service._settings, owners["settings"])
        self.assertIs(service._conversations, owners["conversation_service"])
        self.assertIs(service._conversation_gate, owners["conversation_gate"])
        self.assertIs(service._maintenance_gate, owners["maintenance_gate"])
        deps["conversation"].assert_called_once_with()
        deps["attachments"].assert_not_called()
        deps["transport"].assert_not_called()
        deps["rounds"].assert_not_called()
        deps["failure"].assert_not_called()

    def test_structured_turn_resolves_existing_service_owners_at_creation(self):
        assembly, deps, _owners = self.make_assembly()

        service = assembly.structured_turn_service()

        self.assertIs(
            service._deps.opening._database_manager,
            deps["database_manager"].return_value,
        )
        self.assertIs(service._deps.attachments, deps["attachments"].return_value)
        self.assertIs(service._deps.dialogue, deps["dialogue"].return_value)
        self.assertIs(service._deps.payload, deps["payload"].return_value)
        self.assertIs(service._deps.response._transport, deps["transport"].return_value)
        self.assertIs(service._deps.rounds, deps["rounds"].return_value)
        self.assertIs(
            service._deps.outcome._database_manager,
            deps["database_manager"].return_value,
        )
        self.assertIs(service._deps.failure, deps["failure"].return_value)
        self.assertEqual(deps["jobs"].call_count, 2)

    def test_stateless_retry_policy_is_shared_by_structured_response_services(self):
        assembly, _deps, _owners = self.make_assembly()

        first = assembly.response_retry_policy()
        second = assembly.response_retry_policy()
        response = assembly.structured_response_service()

        self.assertIs(first, second)
        self.assertIs(response._retry_policy, first)


if __name__ == "__main__":
    unittest.main()
