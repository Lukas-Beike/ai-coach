from __future__ import annotations

import unittest
from unittest.mock import Mock

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
            "inspector": Mock(name="duplicate_inspector"),
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
        dependencies["inspector_provider"] = Mock(
            return_value=dependencies["inspector"]
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
                    dependencies["nutrition_diary_provider"],
                    dependencies["nutrition_meal_library_provider"],
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




if __name__ == "__main__":
    unittest.main()
