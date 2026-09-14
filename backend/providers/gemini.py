"""Pure Gemini response and tool-schema adapters."""

from __future__ import annotations

from typing import Any


def response_text(result: Any) -> str:
    """Extract visible text from the first Gemini candidate."""
    candidates = result.get("candidates") if isinstance(result, dict) else []
    candidate = candidates[0] if isinstance(candidates, list) and candidates and isinstance(candidates[0], dict) else {}
    content = candidate.get("content") if isinstance(candidate.get("content"), dict) else {}
    parts = content.get("parts") if isinstance(content.get("parts"), list) else []
    return "\n".join(str(part.get("text") or "") for part in parts if isinstance(part, dict) and part.get("text")).strip()


def function_tools(tools: Any) -> list[dict[str, Any]]:
    """Translate Responses-style function tools to Gemini declarations."""
    declarations = []
    for tool in tools if isinstance(tools, list) else []:
        if not isinstance(tool, dict) or tool.get("type") != "function" or not tool.get("name"):
            continue
        declarations.append({
            "name": str(tool["name"]),
            "description": str(tool.get("description") or ""),
            "parametersJsonSchema": tool.get("parameters") if isinstance(tool.get("parameters"), dict)
            else {"type": "object", "properties": {}},
        })
    return [{"functionDeclarations": declarations}] if declarations else []
