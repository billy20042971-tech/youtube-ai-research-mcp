import json
import unittest

from scripts.mcp_sse import parse_mcp_response_text


class McpSseParserTests(unittest.TestCase):
    def test_parses_plain_json_response(self):
        payload = {"jsonrpc": "2.0", "id": 3, "result": {"structuredContent": {"videos": [1]}}}
        self.assertEqual(parse_mcp_response_text(json.dumps(payload)), {"videos": [1]})

    def test_parses_single_line_sse_response(self):
        payload = {"jsonrpc": "2.0", "id": 3, "result": {"structuredContent": {"videos": [1]}}}
        self.assertEqual(parse_mcp_response_text("data: " + json.dumps(payload) + "\n\n"), {"videos": [1]})

    def test_combines_multiline_sse_data_event(self):
        payload = {
            "jsonrpc": "2.0",
            "id": 3,
            "result": {"structuredContent": {"title": "AI 趨勢", "videos": [{"id": "a"}, {"id": "b"}]}},
        }
        pretty = json.dumps(payload, ensure_ascii=False, indent=2)
        raw = "\n".join("data: " + line for line in pretty.splitlines()) + "\n\n"
        self.assertEqual(parse_mcp_response_text(raw), payload["result"]["structuredContent"])

    def test_uses_final_valid_sse_event(self):
        first = {"jsonrpc": "2.0", "method": "notifications/progress", "params": {}}
        final = {"jsonrpc": "2.0", "id": 3, "result": {"structuredContent": {"ok": True}}}
        raw = "data: " + json.dumps(first) + "\n\n" + "data: " + json.dumps(final) + "\n\n"
        self.assertEqual(parse_mcp_response_text(raw), {"ok": True})

    def test_parses_json_encoded_text_content(self):
        payload = {"jsonrpc": "2.0", "id": 3, "result": {"content": [{"type": "text", "text": json.dumps({"ok": True})}]}}
        self.assertEqual(parse_mcp_response_text(json.dumps(payload)), {"ok": True})

    def test_rejects_malformed_payload_without_echoing_response(self):
        with self.assertRaisesRegex(RuntimeError, "Invalid JSON"):
            parse_mcp_response_text('data: {"jsonrpc":"2.0","result":{"text":"bad')
