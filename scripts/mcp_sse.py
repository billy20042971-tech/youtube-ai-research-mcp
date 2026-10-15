"""Robust parsing for JSON and Server-Sent Events returned by the MCP endpoint."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _decode_payload(payload: str, source: str) -> dict[str, Any]:
    try:
        value = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"Invalid JSON in MCP {source} payload (line {exc.lineno}, column {exc.colno})."
        ) from None
    if not isinstance(value, dict):
        raise RuntimeError(f"MCP {source} payload is not a JSON object.")
    if "error" in value:
        raise RuntimeError("MCP returned a JSON-RPC error.")
    return value


def parse_mcp_response_text(raw: str) -> Any:
    """Parse a JSON response or the final valid JSON event in an SSE response."""
    text = raw.lstrip("\ufeff").strip()
    if not text:
        raise RuntimeError("MCP response body is empty.")

    if not text.startswith(("data:", "event:", "id:", "retry:")):
        outer = _decode_payload(text, "JSON")
    else:
        # SSE events are separated by blank lines. A single event may contain
        # multiple data lines; per the SSE spec, those lines form one payload.
        events: list[str] = []
        current: list[str] = []
        for line in text.splitlines():
            if not line.strip():
                if current:
                    events.append("\n".join(current))
                    current = []
                continue
            if line.startswith("data:"):
                value = line[5:]
                current.append(value[1:] if value.startswith(" ") else value)
        if current:
            events.append("\n".join(current))

        if not events:
            raise RuntimeError("MCP SSE response contains no data events.")

        outer = None
        last_error: RuntimeError | None = None
        # Streamable HTTP may emit progress/events before the final response.
        for payload in events:
            if payload.strip() == "[DONE]":
                continue
            try:
                outer = _decode_payload(payload, "SSE")
            except RuntimeError as exc:
                last_error = exc
                continue
        if outer is None:
            if last_error:
                raise last_error
            raise RuntimeError("MCP SSE response contains no JSON response event.")

    result = outer.get("result", {})
    if not isinstance(result, dict):
        raise RuntimeError("MCP JSON-RPC result is not an object.")
    structured = result.get("structuredContent")
    if structured is not None:
        return structured
    for item in result.get("content", []):
        if isinstance(item, dict) and item.get("type") == "text":
            content = item.get("text", "")
            try:
                return json.loads(content)
            except (json.JSONDecodeError, TypeError):
                raise RuntimeError("MCP text content is not valid JSON.") from None
    # Some tools return their object directly as the result.
    if result:
        return result
    raise RuntimeError("MCP response contains no structured result.")


def parse_mcp_response_file(path: str | Path) -> Any:
    return parse_mcp_response_text(Path(path).read_text(encoding="utf-8-sig"))
