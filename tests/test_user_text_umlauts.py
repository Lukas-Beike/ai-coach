import ast
import pathlib
import unittest

BACKEND_ROOT = pathlib.Path(__file__).resolve().parents[1] / "backend"

# German transliterations (ae/oe/ue/ss) that must not appear in backend
# string literals. Matching is case-insensitive substring matching so that
# compounds such as "Aktivitaetsfeedback" are caught as well.
TRANSLITERATION_STEMS = (
    "fuer",
    "ueber",
    "koenn",
    "moeglich",
    "waehrend",
    "aender",
    "verfuegbar",
    "ungueltig",
    "gueltig",
    "bestaetig",
    "muessen",
    "benoetig",
    "gehoert",
    "spaeter",
    "pruef",
    "geprueft",
    "zurueck",
    "loesch",
    "rueckgaeng",
    "zulaessig",
    "zukuenft",
    "vollstaend",
    "ausgefuehr",
    "aktivitaet",
    "intensitaet",
    "bloecke",
    "enthaelt",
    "ueberein",
    "zaehlt",
    "fruehere",
    "wettkaempf",
    "geschuetzt",
)

# Literal fragments that are machine-facing regex input for athlete prompts,
# not user-facing German text. Keyed by backend-relative path.
ALLOWED_REGEX_FRAGMENTS = {
    "coach/context_selection.py": (
        "loeschen",
        "aender",
        "fruehstueck",
        "aktivitaet",
    ),
}


def _string_constants(path):
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            yield node.lineno, node.value


class UserTextUmlautTests(unittest.TestCase):
    def test_backend_string_literals_use_real_umlauts(self):
        findings = []
        for path in sorted(BACKEND_ROOT.rglob("*.py")):
            relative = path.relative_to(BACKEND_ROOT).as_posix()
            allowed = ALLOWED_REGEX_FRAGMENTS.get(relative, ())
            for lineno, value in _string_constants(path):
                lowered = value.lower()
                for stem in TRANSLITERATION_STEMS:
                    if stem not in lowered:
                        continue
                    if any(fragment in lowered for fragment in allowed):
                        continue
                    findings.append(f"{relative}:{lineno}: {stem!r} in {value[:80]!r}")
        self.assertEqual(
            [],
            findings,
            "German user-facing text must use real umlauts (ä, ö, ü, ß):\n"
            + "\n".join(findings),
        )


if __name__ == "__main__":
    unittest.main()
