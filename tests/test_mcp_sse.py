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

    def test_parses_json_with_leading_whitespace_and_bom(self):
        payload = {"jsonrpc": "2.0", "id": 3, "result": {"structuredContent": {"ok": True}}}
        raw = " \ufeff  " + json.dumps(payload) + "\n"
        self.assertEqual(parse_mcp_response_text(raw), {"ok": True})

    def test_parses_data_prefixed_json_with_leading_whitespace(self):
        payload = {"jsonrpc": "2.0", "id": 3, "result": {"structuredContent": {"ok": True}}}
        self.assertEqual(parse_mcp_response_text("  data: " + json.dumps(payload)), {"ok": True})

    def test_ignores_leading_sse_ping_comment(self):
        payload = {"jsonrpc": "2.0", "id": 3, "result": {"structuredContent": {"ok": True}}}
        raw = ": ping - 2026-10-22 00:21:09.517050+00:00\n\ndata: " + json.dumps(payload) + "\n\n"
        self.assertEqual(parse_mcp_response_text(raw), {"ok": True})

    def test_ignores_multiple_sse_comment_lines_between_data_lines(self):
        payload = {
            "jsonrpc": "2.0",
            "id": 3,
            "result": {"structuredContent": {"title": "AI 趨勢", "videos": [{"id": "a"}, {"id": "b"}]}},
        }
        pretty = json.dumps(payload, ensure_ascii=False, indent=2)
        data_lines = pretty.splitlines()
        raw = (
            ": ping - timestamp one\n"
            ": heartbeat detail\n"
            + "\n".join("data: " + line for line in data_lines[:2])
            + "\n: ping - timestamp two\n"
            + "\n".join("data: " + line for line in data_lines[2:])
            + "\n\n"
        )
        self.assertEqual(parse_mcp_response_text(raw), payload["result"]["structuredContent"])

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

    def test_rejects_malformed_payload_with_first_200_chars(self):
        raw = "<html>" + ("x" * 250)
        with self.assertRaisesRegex(RuntimeError, "Invalid JSON") as ctx:
            parse_mcp_response_text(raw)
        message = str(ctx.exception)
        self.assertIn("raw payload preview (first 200 chars)", message)
        self.assertIn("<html>", message)
        self.assertIn("x" * 190, message)
        self.assertNotIn("x" * 201, message)

    def test_ignores_ping_comments_at_start_middle_and_end(self):
        payload = {"jsonrpc": "2.0", "id": 3, "result": {"structuredContent": {"ok": True}}}
        raw = (
            ": ping - start\n"
            "data: " + json.dumps(payload) + "\n"
            ": ping - middle\n"
            "\n"
            ": ping - end\n"
        )
        self.assertEqual(parse_mcp_response_text(raw), {"ok": True})

    def test_ignores_unexpected_sse_event_headers(self):
        payload = {"jsonrpc": "2.0", "id": 3, "result": {"structuredContent": {"ok": "header-safe"}}}
        raw = (
            "event: heartbeat\n"
            "id: 123\n"
            ": ping - timestamp\n"
            "data: " + json.dumps(payload) + "\n\n"
        )
        self.assertEqual(parse_mcp_response_text(raw), {"ok": "header-safe"})

    def test_parses_bom_before_ping_comment_and_data(self):
        payload = {"jsonrpc": "2.0", "id": 3, "result": {"structuredContent": {"ok": "bom-safe"}}}
        raw = "\ufeff: ping - timestamp\n\n" + "data: " + json.dumps(payload) + "\n\n"
        self.assertEqual(parse_mcp_response_text(raw), {"ok": "bom-safe"})

    def test_blank_line_ends_event_and_parser_uses_later_valid_event(self):
        progress = {"jsonrpc": "2.0", "method": "notifications/progress", "params": {}}
        final = {"jsonrpc": "2.0", "id": 3, "result": {"structuredContent": {"ok": "after-blank"}}}
        raw = (
            "event: heartbeat\ndata: " + json.dumps(progress) + "\n\n"
            ": ping - between events\n"
            "event: message\nid: 123\ndata: " + json.dumps(final) + "\n\n"
        )
        self.assertEqual(parse_mcp_response_text(raw), {"ok": "after-blank"})
