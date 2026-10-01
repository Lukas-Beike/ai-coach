"""Extract the four nutrition fields from the official BLS 4.0 download.

Usage: python tools/extract_bls.py <BLS_4_0_2025_DE.zip>
No network access or third-party spreadsheet library is needed.
"""

from __future__ import annotations

import io
import json
import sys
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}


def extract(archive: Path) -> dict:
    with zipfile.ZipFile(archive) as outer:
        workbook = outer.read("BLS_4_0_2025_DE/BLS_4_0_Daten_2025_DE.xlsx")
    with zipfile.ZipFile(io.BytesIO(workbook)) as inner:
        strings = [
            "".join(item.itertext())
            for item in ET.fromstring(inner.read("xl/sharedStrings.xml"))
        ]
        foods = []
        for _, row in ET.iterparse(
            io.BytesIO(inner.read("xl/worksheets/sheet1.xml")), events=("end",)
        ):
            if row.tag != f"{{{NS['m']}}}row":
                continue
            cells = {}
            for cell in row:
                value = cell.find("m:v", NS)
                if value is not None:
                    column = "".join(c for c in cell.attrib["r"] if c.isalpha())
                    cells[column] = (
                        strings[int(value.text)] if cell.get("t") == "s" else value.text
                    )
            if row.attrib["r"] == "1":
                for column, prefix in {
                    "A": "BLS Code",
                    "B": "Lebensmittelbezeichnung",
                    "G": "ENERCC ",
                    "M": "PROT625 ",
                    "P": "FAT ",
                    "S": "CHO ",
                }.items():
                    if not cells.get(column, "").startswith(prefix):
                        raise ValueError("Unexpected BLS column layout")
            else:
                nutrients = {}
                origins = {}
                for key, column, origin in (
                    ("kcal", "G", "H"),
                    ("protein_g", "M", "N"),
                    ("fat_g", "P", "Q"),
                    ("carbs_g", "S", "T"),
                ):
                    value = cells.get(column, "-")
                    nutrients[key] = (
                        None
                        if value in ("-", "", "TR") or value.startswith("<")
                        else round(float(value), 4)
                    )
                    origins[key] = cells.get(origin, "")
                foods.append(
                    {
                        "code": cells["A"],
                        "name": cells["B"],
                        "per_100": nutrients,
                        "origins": origins,
                    }
                )
            row.clear()
    if len(foods) != 7140:
        raise ValueError("Unexpected BLS 4.0 record count")
    return {
        "source": "Max Rubner-Institut (2025): Bundeslebensmittelschlüssel (BLS), Version 4.0",
        "url": "https://doi.org/10.25826/Data20251217-134202-0",
        "license": "CC BY 4.0",
        "foods": foods,
    }


if __name__ == "__main__":
    target = Path(__file__).resolve().parents[1] / "backend/nutrition/bls_4_0.json"
    target.write_text(
        json.dumps(
            extract(Path(sys.argv[1])), ensure_ascii=False, separators=(",", ":")
        ),
        encoding="utf-8",
    )
