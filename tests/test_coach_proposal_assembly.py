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


def make_assembly() -> tuple[CoachProposalAssembly, dict[str, Mock]]:
    """The assembly over named mocks, with the providers that resolve them."""
    dependencies = {
        "manager": Mock(name="database_manager"),
        "nutrition_diary": Mock(name="nutrition_diary_service"),
        "history": Mock(name="history_undo_service"),
        "intervals": Mock(name="intervals_client_factory"),
        "gate": Mock(name="maintenance_gate"),
        "now": Mock(return_value=10.0),
        "utc_now": Mock(return_value="2026-09-26T00:00:00Z"),
        "uuid": Mock(name="uuid_factory"),
    }
    dependencies["manager_provider"] = Mock(return_value=dependencies["manager"])
    dependencies["nutrition_diary_provider"] = Mock(
        return_value=dependencies["nutrition_diary"]
    )
    dependencies["history_provider"] = Mock(return_value=dependencies["history"])
    dependencies["gate"].return_value = Mock(name="first_gate")
    assembly = CoachProposalAssembly(
        dependencies=CoachProposalAssembly.Inputs(
            persistence=ProposalPersistence(
                dependencies["manager_provider"],
                dependencies["nutrition_diary_provider"],
            ),
            execution=ProposalExecutionOwners(
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


class CoachProposalAssemblyTests(unittest.TestCase):
    def test_assembly_is_lazy_and_proposal_factories_use_current_database(self):
        assembly, dependencies = make_assembly()
        dependencies["manager_provider"].assert_not_called()

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
        self.assertIs(
            create_factory.call_args.kwargs["nutrition_diary_service"],
            dependencies["nutrition_diary_provider"],
        )
        self.assertIs(confirm_factory.call_args.args[0], dependencies["manager"])
        self.assertEqual(dependencies["manager_provider"].call_count, 3)

    def test_execution_keeps_provider_and_gate_resolution_boundaries(self):
        assembly, dependencies = make_assembly()
        with patch.object(
            proposal_assembly, "CoachProposalExecutionService"
        ) as factory:
            assembly.execution_service()

        args = factory.call_args.args
        self.assertIs(args[0], dependencies["manager"])
        self.assertIs(args[1], dependencies["history"])
        self.assertIs(args[2], dependencies["intervals"])
        self.assertIs(args[3], dependencies["gate"].return_value)
        self.assertFalse(dependencies["intervals"].called)
        dependencies["gate"].return_value = Mock(name="replacement_gate")
        with patch.object(
            proposal_assembly, "CoachProposalExecutionService"
        ) as second_factory:
            assembly.execution_service()
        self.assertIs(
            second_factory.call_args.args[3], dependencies["gate"].return_value
        )
        self.assertEqual(dependencies["manager_provider"].call_count, 2)


if __name__ == "__main__":
    unittest.main()
