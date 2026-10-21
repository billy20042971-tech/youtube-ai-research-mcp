"""Bounded, quota-conscious retries for read-only MCP tool calls.

Only transient transport/status failures and successful HTTP responses with empty
bodies are retried. Non-empty payload parsing remains the responsibility of
scripts.mcp_sse, so malformed JSON/SSE and JSON-RPC errors fail closed.
"""
from __future__ import annotations

import json
import socket
import time
import urllib.error
import urllib.request
from typing import Any, Callable


class McpHttpError(RuntimeError):
    """Safe-to-log MCP transport failure without request headers or payloads."""


def call_mcp_tool(
    url: str,
    session_id: str,
    arguments: dict[str, Any],
    *,
    request_id: int = 3,
    max_attempts: int = 3,
    timeout: int = 240,
    opener: Callable[..., Any] = urllib.request.urlopen,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> bytes:
    if max_attempts < 1:
        raise ValueError("max_attempts must be at least 1")
    payload = json.dumps({
        "jsonrpc": "2.0",
        "id": request_id,
        "method": "tools/call",
        "params": {"name": "youtube_research_sample", "arguments": arguments},
    }, ensure_ascii=False).encode("utf-8")
    last_condition = "UNKNOWN"

    for attempt in range(1, max_attempts + 1):
        req = urllib.request.Request(
            url,
            data=payload,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream",
                "Mcp-Session-Id": session_id,
            },
        )
        try:
            with opener(req, timeout=timeout) as response:
                status = getattr(response, "status", None)
                if status is None:
                    status = response.getcode()
                body = response.read()
            if 200 <= status < 300:
                if body and body.strip():
                    return body
                last_condition = f"HTTP_{status}_EMPTY_BODY"
            elif status in (408, 429) or status >= 500:
                last_condition = f"HTTP_{status}"
            else:
                raise McpHttpError(f"MCP tool call rejected with HTTP {status}; not retrying.")
        except urllib.error.HTTPError as exc:
            status = exc.code
            if status in (408, 429) or status >= 500:
                last_condition = f"HTTP_{status}"
            else:
                raise McpHttpError(f"MCP tool call rejected with HTTP {status}; not retrying.") from None
        except (urllib.error.URLError, TimeoutError, socket.timeout):
            last_condition = "TRANSPORT_TIMEOUT_OR_ERROR"

        if attempt < max_attempts:
            sleep_fn(float(attempt))

    raise McpHttpError(
        f"MCP tool call failed after {max_attempts} attempts; last condition={last_condition}."
    )
