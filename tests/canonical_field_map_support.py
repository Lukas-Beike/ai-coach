"""Static extraction behind the canonical field map drift test.

Reads the mapper sources as text (AST) and the canonical vocabulary and record
modules; nothing is executed beyond importing the vocabulary enums.
"""

from __future__ import annotations

import ast
import dataclasses
import importlib
import inspect
import re
from enum import StrEnum
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[1]
PROVIDERS = ROOT / "backend" / "providers"
DOC = ROOT / "docs" / "canonical-field-map.md"

RECORD_MODULES = (
    "backend.canonical.records",
    "backend.canonical.activity_detail",
    "backend.canonical.domain_records",
)
# Canonical record constructors whose keyword arguments are emitted fields.
EXTRA_RECORD_NAMES = frozenset({"PowerCurvePoint", "PowerCurveFetch"})

BACKTICKED = re.compile(r"`([^`\n]+)`")
HEADING = re.compile(r"^(#{1,6})\s+(.*)$")


def vocabulary_enums() -> dict[str, type[StrEnum]]:
    """Every StrEnum declared in the canonical vocabulary, by class name."""
    vocabulary = importlib.import_module("backend.canonical.vocabulary")
    return {
        name: member
        for name, member in vars(vocabulary).items()
        if inspect.isclass(member)
        and issubclass(member, StrEnum)
        and member.__module__ == vocabulary.__name__
    }


def record_classes() -> dict[str, type]:
    """Every canonical record dataclass, by class name."""
    found: dict[str, type] = {}
    for module_name in RECORD_MODULES:
        module: ModuleType = importlib.import_module(module_name)
        for name, member in vars(module).items():
            if (
                inspect.isclass(member)
                and dataclasses.is_dataclass(member)
                and member.__module__ == module.__name__
            ):
                found[name] = member
    return found


def record_fields(cls: type) -> list[str]:
    return [field.name for field in dataclasses.fields(cls)]


def emitted_tokens(source: str) -> set[str]:
    """Enum values and record keyword names a mapper source names in code."""
    enums = vocabulary_enums()
    records = set(record_classes()) | EXTRA_RECORD_NAMES
    tokens: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if (
            isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id in enums
        ):
            member = getattr(enums[node.value.id], node.attr, None)
            if isinstance(member, StrEnum):
                tokens.add(member.value)
        elif isinstance(node, ast.Call):
            func = node.func
            name = (
                func.id
                if isinstance(func, ast.Name)
                else func.attr
                if isinstance(func, ast.Attribute)
                else None
            )
            if name in records:
                tokens.update(kw.arg for kw in node.keywords if kw.arg)
    return tokens


def mapper_modules() -> list[Path]:
    """Provider modules that name canonical enum members or construct records."""
    found = []
    for path in sorted(PROVIDERS.glob("*.py")):
        if emitted_tokens(path.read_text(encoding="utf-8")):
            found.append(path)
    return found


def doc_sections(text: str) -> list[tuple[int, str, str]]:
    """Split markdown into (level, heading, body) with the body up to the next
    heading of the same or a higher level (sub-headings stay in the body)."""
    lines = text.splitlines()
    heads: list[tuple[int, int, str]] = []
    in_fence = False
    for index, line in enumerate(lines):
        if line.startswith("```"):
            in_fence = not in_fence
            continue
        match = None if in_fence else HEADING.match(line)
        if match:
            heads.append((index, len(match.group(1)), match.group(2)))
    sections = []
    for position, (index, level, title) in enumerate(heads):
        end = len(lines)
        for next_index, next_level, _ in heads[position + 1 :]:
            if next_level <= level:
                end = next_index
                break
        sections.append((level, title, "\n".join(lines[index + 1 : end])))
    return sections


def backticked(text: str) -> set[str]:
    """Backticked tokens, also splitting `a.b` / `a, b` / `a | b` style lists."""
    tokens: set[str] = set()
    for raw in BACKTICKED.findall(text):
        tokens.add(raw.strip())
        for part in re.split(r"[,|;/\s]+", raw):
            if part:
                tokens.add(part.strip("()"))
    return tokens


def section_for_module(sections, filename: str) -> str | None:
    """Body of the section whose heading names ``filename`` in backticks."""
    for _, title, body in sections:
        if f"`{filename}`" in title:
            return body
    return None


def record_constructor_calls(source: str) -> bool:
    """Whether the source calls a canonical record constructor with keywords."""
    records = set(record_classes()) | EXTRA_RECORD_NAMES
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Call) and any(kw.arg for kw in node.keywords):
            func = node.func
            name = (
                func.id
                if isinstance(func, ast.Name)
                else func.attr
                if isinstance(func, ast.Attribute)
                else None
            )
            if name in records:
                return True
    return False


def record_builders_outside_providers() -> list[Path]:
    """Backend files outside the provider mappers that build canonical records."""
    found = []
    for path in sorted((ROOT / "backend").rglob("*.py")):
        relative = path.relative_to(ROOT).as_posix()
        if relative.startswith(("backend/providers/", "backend/canonical/")):
            continue
        if record_constructor_calls(path.read_text(encoding="utf-8")):
            found.append(path)
    return found
