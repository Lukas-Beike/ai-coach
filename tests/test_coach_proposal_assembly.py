from __future__ import annotations

import unittest
from unittest.mock import Mock, patch

from backend.coach import proposal_assembly
from backend.coach.proposal_assembly import (
    CoachProposalAssembly,
    ProposalClock,
    ProposalExecutionOwners,
    ProposalPersistence,
)


class CoachProposalAssemblyTests(unittest.TestCase):
    def make_assembly(self):
        dependencies = {
            "manager": Mock(name="database_manager"),
            "sync_state": Mock(name="sync_state_repository"),
            "nutrition_diary": Mock(name="nutrition_diary_service"),
            "nutrition_meal_library": Mock(name="nutrition_meal_library_service"),
            "duplicate": Mock(name="duplicate_activity_service"),
            "history": Mock(name="history_undo_service"),
            "intervals": Mock(name="intervals_client_factory"),
            "gate": Mock(name="maintenance_gate"),
            "now": Mock(return_value=10.0),
            "utc_now": Mock(return_value="2026-09-26T00:00:00Z"),
            "uuid": Mock(name="uuid_factory"),
        }
        dependencies["manager_provider"] = Mock(return_value=dependencies["manager"])
        dependencies["sync_state_provider"] = Mock(
            return_value=dependencies["sync_state"]
        )
        dependencies["nutrition_diary_provider"] = Mock(
            return_value=dependencies["nutrition_diary"]
        )
        dependencies["nutrition_meal_library_provider"] = Mock(
            return_value=dependencies["nutrition_meal_library"]
        )
        dependencies["duplicate_provider"] = Mock(
            return_value=dependencies["duplicate"]
        )
        dependencies["history_provider"] = Mock(return_value=dependencies["history"])
        first_gate = Mock(name="first_gate")
        dependencies["gate"].return_value = first_gate
        assembly = CoachProposalAssembly(
            dependencies=CoachProposalAssembly.Inputs(
                persistence=ProposalPersistence(
                    dependencies["manager_provider"],
                    dependencies["sync_state_provider"],
                    dependencies["nutrition_diary_provider"],
                    dependencies["nutrition_meal_library_provider"],
                ),
                execution=ProposalExecutionOwners(
                    dependencies["duplicate_provider"],
                    dependencies["history_provider"],
                    dependencies["intervals"],
                    dependencies["gate"],
                ),
                clock=ProposalClock(
                    utc_now=dependencies["utc_now"],
                    now=dependencies["now"],
                    uuid_factory=dependencies["uuid"],
                ),
            )
        )
        return assembly, dependencies

    def test_assembly_is_lazy_and_proposal_factories_use_current_database(self):
        assembly, dependencies = self.make_assembly()
        dependencies["manager_provider"].assert_not_called()
        dependencies["sync_state_provider"].assert_not_called()

        with (
            patch.object(proposal_assembly, "CoachProposalReadService") as read_factory,
            patch.object(
                proposal_assembly, "CoachProposalCreationService"
            ) as create_factory,
            patch.object(
                proposal_assembly, "CoachProposalConfirmationService"
            ) as confirm_factory,
        ):
            assembly.read_service()
            assembly.creation_service()
            assembly.confirmation_service()

        self.assertIs(read_factory.call_args.args[0], dependencies["manager"])
        self.assertIs(create_factory.call_args.args[0], dependencies["manager"])
        self.assertIs(create_factory.call_args.args[1], dependencies["sync_state"])
        self.assertIs(
            create_factory.call_args.kwargs["nutrition_diary_service"],
            dependencies["nutrition_diary_provider"],
        )
        self.assertIs(
            create_factory.call_args.kwargs["nutrition_meal_library_service"],
            dependencies["nutrition_meal_library_provider"],
        )
        self.assertIs(confirm_factory.call_args.args[0], dependencies["manager"])
        self.assertEqual(dependencies["manager_provider"].call_count, 3)

    def test_execution_keeps_provider_and_gate_resolution_boundaries(self):
        assembly, dependencies = self.make_assembly()
        with patch.object(
            proposal_assembly, "CoachProposalExecutionService"
        ) as factory:
            assembly.execution_service()

        args = factory.call_args.args
        self.assertIs(args[0], dependencies["manager"])
        self.assertIs(args[1], dependencies["duplicate"])
        self.assertIs(args[2], dependencies["history"])
        self.assertIs(args[3], dependencies["intervals"])
        self.assertIs(args[4], dependencies["gate"].return_value)
        self.assertFalse(dependencies["intervals"].called)
        dependencies["gate"].return_value = Mock(name="replacement_gate")
        with patch.object(
            proposal_assembly, "CoachProposalExecutionService"
        ) as second_factory:
            assembly.execution_service()
        self.assertIs(
            second_factory.call_args.args[4], dependencies["gate"].return_value
        )
        self.assertEqual(dependencies["manager_provider"].call_count, 2)


if __name__ == "__main__":
    unittest.main()
