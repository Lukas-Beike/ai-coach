"""Keep repository-local AI instructions aligned with the source tree."""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILL_ROOTS = (ROOT / ".agents" / "skills", ROOT / ".codex" / "skills")


@unittest.skipUnless(
    (ROOT / "AGENTS.md").is_file(),
    "Repository AI documentation is not packaged in the runtime image",
)
class AiDocsContractTests(unittest.TestCase):
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
        skill_files = sorted(
            path for root in SKILL_ROOTS for path in root.rglob("SKILL.md")
        )
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

    def test_repository_skill_links_resolve(self) -> None:
        markdown_files = [path for root in SKILL_ROOTS for path in root.rglob("*.md")]
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

    def test_validation_skill_does_not_reference_removed_test_module(self) -> None:
        validation = (
            ROOT / ".agents" / "skills" / "ai-coach-validation" / "SKILL.md"
        ).read_text(encoding="utf-8")
        self.assertNotIn("tests/test_server.py", validation)
        self.assertTrue((ROOT / "tests" / "run_tests.py").is_file())

    def test_skills_stay_repository_local(self) -> None:
        for skill_root in SKILL_ROOTS:
            self.assertTrue(skill_root.is_dir(), skill_root)
            self.assertTrue(skill_root.is_relative_to(ROOT))
            for skill_file in skill_root.rglob("SKILL.md"):
                self.assertTrue(skill_file.resolve().is_relative_to(ROOT), skill_file)


if __name__ == "__main__":
    unittest.main()
