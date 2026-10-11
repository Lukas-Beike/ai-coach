"""Keep repository-local AI instructions aligned with the source tree."""

import os
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILL_ROOT = ROOT / ".agents" / "skills"
SCOPED_INSTRUCTIONS = (
    "backend/AGENTS.md",
    "public/AGENTS.md",
    "tests/AGENTS.md",
    "e2e/AGENTS.md",
    ".github/AGENTS.md",
)
REQUIRED_GUIDANCE = (
    "AGENTS.md",
    "REVIEW.md",
    ".agents/skills/README.md",
    *SCOPED_INSTRUCTIONS,
)


@unittest.skipUnless(
    os.environ.get("AI_DOCS_REQUIRED") == "1" or (ROOT / "AGENTS.md").is_file(),
    "Repository AI documentation is not packaged in the runtime image",
)
class AiDocsContractTests(unittest.TestCase):
    def test_required_guidance_exists_and_scopes_are_routed(self) -> None:
        for relative in REQUIRED_GUIDANCE:
            self.assertTrue((ROOT / relative).is_file(), relative)
        instructions = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
        for relative in SCOPED_INSTRUCTIONS:
            self.assertIn(f"]({relative})", instructions, relative)
        self.assertIn("](.agents/skills/README.md)", instructions)
        self.assertIn("](REVIEW.md)", instructions)

    def test_expected_backend_domains_are_documented(self) -> None:
        instructions = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
        domains = [
            path.name
            for path in (ROOT / "backend").iterdir()
            if path.is_dir() and not path.name.startswith("_")
        ]
        self.assertTrue(domains)
        for domain in domains:
            self.assertIn(f"`{domain}/`", instructions)

    def test_skill_names_are_unique_and_frontmatter_matches_directories(self) -> None:
        skill_files = sorted(SKILL_ROOT.rglob("SKILL.md"))
        self.assertTrue(skill_files)
        skills = []
        for skill_file in skill_files:
            content = skill_file.read_text(encoding="utf-8")
            self.assertTrue(content.startswith("---\n"), skill_file)
            frontmatter = content.split("---\n", 2)
            self.assertEqual(len(frontmatter), 3, skill_file)
            self.assertRegex(frontmatter[1], r"(?m)^description:[ \t]*\S")
            match = re.search(r"^name:[ \t]*([^\r\n]+)$", frontmatter[1], re.MULTILINE)
            if match is None:
                self.fail(str(skill_file))
            skill_name = match.group(1).strip().strip('"')
            skills.append((skill_name, skill_file))
            self.assertEqual(skill_file.parent.name, skill_name, skill_file)
        names = [name for name, _ in skills]
        self.assertEqual(len(names), len(set(names)), names)

    def test_repository_guidance_links_resolve(self) -> None:
        markdown_files = [ROOT / relative for relative in REQUIRED_GUIDANCE]
        markdown_files.extend(SKILL_ROOT.rglob("*.md"))
        for markdown_file in markdown_files:
            content = markdown_file.read_text(encoding="utf-8")
            for target in re.findall(r"\[[^\]]*\]\(([^)#]+)", content):
                if target.startswith(("http://", "https://")):
                    continue
                resolved = (markdown_file.parent / target).resolve()
                self.assertTrue(
                    resolved.is_relative_to(ROOT), f"{markdown_file}: {target}"
                )
                self.assertTrue(resolved.is_file(), f"{markdown_file}: {target}")

    def test_every_skill_is_routed_by_the_index(self) -> None:
        index = (SKILL_ROOT / "README.md").read_text(encoding="utf-8")
        routes = [
            (SKILL_ROOT / target).resolve()
            for target in re.findall(r"\[[^\]]*\]\(([^)#]+/SKILL\.md)\)", index)
        ]
        expected = {path.resolve() for path in SKILL_ROOT.rglob("SKILL.md")}
        self.assertTrue(expected)
        self.assertEqual(len(routes), len(set(routes)), "Duplicate skill routes")
        self.assertEqual(set(routes), expected, "Missing or obsolete skill routes")

    def test_validation_skill_does_not_reference_removed_test_module(self) -> None:
        validation = (
            ROOT / ".agents" / "skills" / "ai-coach-validation" / "SKILL.md"
        ).read_text(encoding="utf-8")
        self.assertNotIn("tests/test_server.py", validation)
        self.assertTrue((ROOT / "tests" / "run_tests.py").is_file())

    def test_skills_stay_repository_local(self) -> None:
        self.assertTrue(SKILL_ROOT.is_dir(), SKILL_ROOT)
        self.assertTrue(SKILL_ROOT.resolve().is_relative_to(ROOT))
        self.assertFalse(
            list((ROOT / ".codex" / "skills").rglob("SKILL.md")),
            "Project skills have one canonical root: .agents/skills",
        )
        for skill_file in SKILL_ROOT.rglob("SKILL.md"):
            self.assertEqual(skill_file.parent.parent, SKILL_ROOT, skill_file)
            self.assertTrue(
                skill_file.resolve().is_relative_to(SKILL_ROOT.resolve()), skill_file
            )


if __name__ == "__main__":
    unittest.main()
