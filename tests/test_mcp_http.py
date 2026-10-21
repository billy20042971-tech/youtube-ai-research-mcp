import json
import socket
import unittest
import urllib.error
from unittest.mock import Mock

from scripts.mcp_http import McpHttpError, call_mcp_tool


class FakeResponse:
    def __init__(self, body=b"", status=200):
        self.body = body
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return self.body


class McpHttpRetryTests(unittest.TestCase):
    def setUp(self):
        self.sleep = Mock()

    def test_returns_valid_json_body(self):
        body = b'{"jsonrpc":"2.0","id":3,"result":{"structuredContent":{"ok":true}}}'
        result = call_mcp_tool("https://example.invalid/mcp", "session", {"queries": []},
                               opener=Mock(return_value=FakeResponse(body)), sleep_fn=self.sleep)
        self.assertEqual(result, body)
        self.sleep.assert_not_called()

    def test_returns_valid_sse_body(self):
        body = b'data: {"jsonrpc":"2.0","id":3,"result":{"structuredContent":{"ok":true}}}\n\n'
        result = call_mcp_tool("https://example.invalid/mcp", "session", {"queries": []},
                               opener=Mock(return_value=FakeResponse(body)), sleep_fn=self.sleep)
        self.assertEqual(result, body)

    def test_empty_http_200_then_success_retries_once(self):
        opener = Mock(side_effect=[FakeResponse(b""), FakeResponse(b'{"ok":true}')])
        result = call_mcp_tool("https://example.invalid/mcp", "session", {"queries": []},
                               opener=opener, sleep_fn=self.sleep)
        self.assertEqual(result, b'{"ok":true}')
        self.assertEqual(opener.call_count, 2)
        self.sleep.assert_called_once_with(1.0)

    def test_empty_http_200_exhausts_bounded_retries(self):
        opener = Mock(return_value=FakeResponse(b""))
        with self.assertRaisesRegex(McpHttpError, "after 3 attempts.*HTTP_200_EMPTY_BODY"):
            call_mcp_tool("https://example.invalid/mcp", "session", {"queries": []},
                          opener=opener, sleep_fn=self.sleep)
        self.assertEqual(opener.call_count, 3)
        self.assertEqual(self.sleep.call_count, 2)

    def test_http_503_then_success_retries(self):
        error = urllib.error.HTTPError("https://example.invalid/mcp", 503, "unavailable", {}, None)
        opener = Mock(side_effect=[error, FakeResponse(b'{"ok":true}')])
        result = call_mcp_tool("https://example.invalid/mcp", "session", {"queries": []},
                               opener=opener, sleep_fn=self.sleep)
        self.assertEqual(result, b'{"ok":true}')
        self.assertEqual(opener.call_count, 2)

    def test_non_retryable_http_400_fails_immediately(self):
        error = urllib.error.HTTPError("https://example.invalid/mcp", 400, "bad request", {}, None)
        opener = Mock(side_effect=error)
        with self.assertRaisesRegex(McpHttpError, "HTTP 400; not retrying"):
            call_mcp_tool("https://example.invalid/mcp", "session", {"queries": []},
                          opener=opener, sleep_fn=self.sleep)
        opener.assert_called_once()
        self.sleep.assert_not_called()

    def test_timeout_then_success_retries(self):
        opener = Mock(side_effect=[socket.timeout(), FakeResponse(b'{"ok":true}')])
        result = call_mcp_tool("https://example.invalid/mcp", "session", {"queries": []},
                               opener=opener, sleep_fn=self.sleep)
        self.assertEqual(result, b'{"ok":true}')
        self.assertEqual(opener.call_count, 2)

    def test_request_uses_session_header_and_read_only_tool_name(self):
        opener = Mock(return_value=FakeResponse(b'{"ok":true}'))
        call_mcp_tool("https://example.invalid/mcp", "session-abc", {"queries": ["AI"]},
                      opener=opener, sleep_fn=self.sleep)
        request = opener.call_args.args[0]
        self.assertEqual(request.get_header("Mcp-session-id"), "session-abc")
        payload = json.loads(request.data)
        self.assertEqual(payload["method"], "tools/call")
        self.assertEqual(payload["params"]["name"], "youtube_research_sample")
        self.assertEqual(payload["id"], 3)
        self.assertNotIn("Authorization", request.headers)


if __name__ == "__main__":
    unittest.main()
