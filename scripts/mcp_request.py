"""Bounded HTTP retry for read-style MCP tools/call requests."""
import json
import os
import socket
import sys
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

RETRYABLE_HTTP_STATUSES = {408, 425, 429}
class McpRequestError(RuntimeError):
    pass

def retryable_http_status(status):
    return status in RETRYABLE_HTTP_STATUSES or 500 <= status <= 599

def request_tool(url, session_id, arguments, output_path, *, opener=None, sleeper=None, max_attempts=2, timeout=240):
    if not isinstance(arguments, dict):
        raise McpRequestError("MCP tool arguments must be a JSON object.")
    if not isinstance(session_id, str) or not session_id.strip():
        raise McpRequestError("MCP session ID is missing.")
    if max_attempts < 1:
        raise ValueError("max_attempts must be at least one")
    open_request, sleep = opener or urlopen, sleeper or time.sleep
    payload = {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
               "params": {"name": "youtube_research_sample", "arguments": arguments}}
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    req = Request(url, data=body, method="POST", headers={
        "Content-Type": "application/json", "Accept": "application/json, text/event-stream",
        "Mcp-Session-Id": session_id,
    })
    last_reason = "no response"
    for attempt in range(1, max_attempts + 1):
        status, response_body = None, b""
        try:
            with open_request(req, timeout=timeout) as response:
                status = getattr(response, "status", None)
                if status is None:
                    status = response.getcode()
                response_body = response.read()
        except HTTPError as exc:
            status = exc.code
        except (URLError, TimeoutError, socket.timeout, ConnectionError, OSError) as exc:
            last_reason = "transient transport failure (" + type(exc).__name__ + ")"
            if attempt < max_attempts:
                sleep(5 * attempt)
                continue
            raise McpRequestError("MCP tool request failed after " + str(attempt) + " attempts: " + last_reason) from None
        if status is not None and 200 <= status <= 299:
            if response_body and response_body.strip():
                output_path.parent.mkdir(parents=True, exist_ok=True)
                temp = output_path.with_name(output_path.name + ".tmp")
                temp.write_bytes(response_body)
                temp.replace(output_path)
                return attempt
            last_reason = "HTTP " + str(status) + " returned an empty response body"
        elif status is not None and retryable_http_status(status):
            last_reason = "transient HTTP " + str(status)
        else:
            raise McpRequestError("MCP tool request returned non-retryable HTTP status " + str(status or "unknown") + ".")
        if attempt < max_attempts:
            sleep(5 * attempt)
    raise McpRequestError("MCP tool request failed after " + str(max_attempts) + " attempts: " + last_reason)

def main():
    try:
        arguments = json.loads(os.environ["MCP_TOOL_ARGUMENTS"])
        request_tool(os.environ["MCP_URL"], os.environ.get("MCP_SESSION_ID", ""), arguments,
                     Path(os.environ["MCP_OUTPUT_FILE"]))
        return 0
    except (KeyError, json.JSONDecodeError, McpRequestError) as exc:
        print(str(exc) if isinstance(exc, McpRequestError) else
              "MCP tool request configuration is incomplete or invalid.", file=sys.stderr)
        return 1

if __name__ == "__main__":
    raise SystemExit(main())
