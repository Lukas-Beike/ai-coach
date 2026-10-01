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


def _cell_values(row: ET.Element, strings: list[str]) -> dict[str, str]:
    cells = {}
    for cell in row:
        value = cell.find("m:v", NS)
        if value is not None:
            column = "".join(char for char in cell.attrib["r"] if char.isalpha())
            cells[column] = (
                strings[int(value.text)] if cell.get("t") == "s" else value.text
            )
    return cells


def _validate_header(cells: dict[str, str]) -> None:
    headers = {
        "A": "BLS Code",
        "B": "Lebensmittelbezeichnung",
        "G": "ENERCC ",
        "M": "PROT625 ",
        "P": "FAT ",
        "S": "CHO ",
    }
    if any(
        not cells.get(column, "").startswith(prefix)
        for column, prefix in headers.items()
    ):
        raise ValueError("Unexpected BLS column layout")


def _nutrition_fields(
    cells: dict[str, str],
) -> tuple[dict[str, float | None], dict[str, str]]:
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
    return nutrients, origins


def _extract_rows(sheet: bytes, strings: list[str]) -> list[dict]:
    foods = []
    for _, row in ET.iterparse(io.BytesIO(sheet), events=("end",)):
        if row.tag != f"{{{NS['m']}}}row":
            continue
        cells = _cell_values(row, strings)
        if row.attrib["r"] == "1":
            _validate_header(cells)
        else:
            nutrients, origins = _nutrition_fields(cells)
            foods.append(
                {
                    "code": cells["A"],
                    "name": cells["B"],
                    "per_100": nutrients,
                    "origins": origins,
                }
            )
        row.clear()
    return foods


def extract(archive: Path) -> dict:
    with zipfile.ZipFile(archive) as outer:
        workbook = outer.read("BLS_4_0_2025_DE/BLS_4_0_Daten_2025_DE.xlsx")
    with zipfile.ZipFile(io.BytesIO(workbook)) as inner:
        strings = [
            "".join(item.itertext())
            for item in ET.fromstring(inner.read("xl/sharedStrings.xml"))
        ]
        foods = _extract_rows(inner.read("xl/worksheets/sheet1.xml"), strings)
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
