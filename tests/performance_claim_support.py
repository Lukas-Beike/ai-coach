"""Forbidden recovery wording shared by the wording scan and the Coach cases.

The terms come from the Forbidden statements of the M2 and M3 evidence cards
(docs/performance-methods). The Sleep Regularity Index may be named only to deny
that a method is one.
"""

import re

FORBIDDEN_TERMS = (
    r"sleep\s+debt",
    r"Schlafschuld",
    r"Schlafdefizit",
    r"Normalbereich",
    r"normal\s+range",
    r"üblichen\s+Bereich",
    r"Grüner\s+Bereich",
    r"abnormal",
    r"auffällig",
    r"klinisch",
    r"clinical",
    r"sleep[-_]regularity",
)
_FORBIDDEN = re.compile("|".join(FORBIDDEN_TERMS), re.IGNORECASE)
_SRI = re.compile(r"Sleep\s+Regularity\s+Index|\bSRI\b")
_DENIAL = re.compile(r"\b(?:not|kein|keine|nicht)\b(?:\s+\S+){0,2}\s+$", re.IGNORECASE)


def claim_wording_violations(text: str) -> list[tuple[int, str]]:
    """Return (line, term) for each forbidden term in ``text``."""
    found = []
    for match in _FORBIDDEN.finditer(text):
        found.append((text.count("\n", 0, match.start()) + 1, match.group(0)))
    for match in _SRI.finditer(text):
        if not _DENIAL.search(text[max(0, match.start() - 40) : match.start()]):
            found.append((text.count("\n", 0, match.start()) + 1, match.group(0)))
    return found
