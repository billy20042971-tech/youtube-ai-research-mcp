import unittest
import json
from unittest.mock import call, patch

from scripts import notion_writeback
from scripts.notion_writeback import (
    comment_text,
    ensure_comment,
    find_existing_comment,
    text_from_comment,
    verify_comment,
    validate_target_database_id,
    build_deep_briefing_blocks,
    block_signature,
    verify_block_sequence,
    split_text,
    video_blocks,
    _readback_block_sequence,
)


class NotionWritebackTests(unittest.TestCase):
    def test_approved_target_database_id_accepts_hyphenated_and_compact_forms(self):
        validate_target_database_id("8eeeca64-4e1f-4687-a361-1f5124a0c5c8")
        validate_target_database_id("8eeeca644e1f4687a3611f5124a0c5c8")

    def test_unapproved_target_database_id_fails_closed(self):
        with self.assertRaisesRegex(RuntimeError, "approved.*AI 情報雷達 database"):
            validate_target_database_id("2a240065-15d9-8017-98c3-fee1659120ae")

    def test_comment_contains_stable_execution_id_and_artifact_paths(self):
        text = comment_text(
            "gh-123-attempt-2",
            {
                "sample_count": 40,
                "word": "reports/report.docx",
                "pptx": "reports/slides.pptx",
                "chart": "reports/chart.png",
            },
            {
                "github_run_id": "123",
                "trigger": "schedule",
                "status": "IN_PROGRESS",
                "data_verification": {"verified_72h": True},
            },
        )
        self.assertIn("execution_id: gh-123-attempt-2", text)
        self.assertIn("pipeline_status_at_writeback: IN_PROGRESS", text)
        self.assertNotIn("pipeline_status: IN_PROGRESS", text)
        self.assertIn("sample_count: 40", text)
        self.assertIn("reports/report.docx", text)
        self.assertIn("verified_72h: True", text)

    @staticmethod
    def comment(comment_id, execution_id):
        return {
            "id": comment_id,
            "rich_text": [{"plain_text": f"execution_id: {execution_id}"}],
        }

    def test_finds_existing_execution_across_comment_pages(self):
        execution_id = "gh-123-attempt-1"
        with patch(
            "scripts.notion_writeback.request_json",
            side_effect=[
                {"results": [{"id": "other", "rich_text": [{"plain_text": "other run"}]}],
                 "has_more": True, "next_cursor": "cursor-2"},
                {"results": [self.comment("existing-id", execution_id)],
                 "has_more": False, "next_cursor": None},
            ],
        ) as request:
            found = find_existing_comment("page", "token", execution_id)

        self.assertEqual(found["id"], "existing-id")
        self.assertEqual(request.call_count, 2)
        self.assertIn("start_cursor=cursor-2", request.call_args_list[1].args[1])

    def test_retry_reuses_existing_comment_only_when_full_content_matches(self):
        execution_id = "gh-123-attempt-1"
        expected = f"execution_id: {execution_id}\\nnew content"
        existing = {"id": "existing-id", "rich_text": [{"plain_text": expected}]}
        with patch(
            "scripts.notion_writeback.request_json",
            return_value={"results": [existing], "has_more": False, "next_cursor": None},
        ) as request:
            comment_id = ensure_comment("page", "token", execution_id, expected)

        self.assertEqual(comment_id, "existing-id")
        self.assertTrue(all(args.args[0] == "GET" for args in request.call_args_list))
        self.assertFalse(any(args.args[0] == "POST" for args in request.call_args_list))

    def test_existing_execution_comment_with_different_content_fails_closed(self):
        execution_id = "gh-123-attempt-1"
        existing = {"id": "existing-id", "rich_text": [{"plain_text": f"execution_id: {execution_id}\\nold content"}]}
        with patch(
            "scripts.notion_writeback.request_json",
            return_value={"results": [existing], "has_more": False, "next_cursor": None},
        ) as request:
            with self.assertRaisesRegex(RuntimeError, "different content"):
                ensure_comment("page", "token", execution_id, f"execution_id: {execution_id}\\nnew content")
        self.assertTrue(all(args.args[0] == "GET" for args in request.call_args_list))

    def test_long_comment_is_chunked_without_truncating_expected_content(self):
        execution_id = "gh-127-attempt-1"
        text = f"execution_id: {execution_id}\\n" + ("長" * 4500)
        parts = split_text(text)
        created = {"id": "created-id", "rich_text": [{"plain_text": part} for part in parts]}
        with patch(
            "scripts.notion_writeback.request_json",
            side_effect=[
                {"results": [], "has_more": False, "next_cursor": None},
                created,
            ],
        ) as request:
            comment_id = ensure_comment("page", "token", execution_id, text)
        payload = request.call_args_list[1].args[3]["rich_text"]
        self.assertEqual(comment_id, "created-id")
        self.assertEqual("".join(item["text"]["content"] for item in payload), text)
        self.assertTrue(all(len(item["text"]["content"]) <= 2000 for item in payload))

    def test_creates_comment_only_when_execution_marker_is_absent(self):
        execution_id = "gh-124-attempt-1"
        with patch(
            "scripts.notion_writeback.request_json",
            side_effect=[
                {"results": [self.comment("other-id", "gh-other")],
                 "has_more": False, "next_cursor": None},
                {"id": "created-id"},
            ],
        ) as request:
            comment_id = ensure_comment("page", "token", execution_id, f"execution_id: {execution_id}\\nnew content")

        self.assertEqual(comment_id, "created-id")
        self.assertEqual([c.args[0] for c in request.call_args_list], ["GET", "POST"])
        self.assertEqual(request.call_args_list[1].args[1], "/comments")
        self.assertIn(execution_id, request.call_args_list[1].args[3]["rich_text"][0]["text"]["content"])

    def test_readback_retries_get_without_creating_another_comment(self):
        execution_id = "gh-125-attempt-1"
        with patch(
            "scripts.notion_writeback.request_json",
            side_effect=[
                {"results": [], "has_more": False, "next_cursor": None},
                {"results": [self.comment("created-id", execution_id)],
                 "has_more": False, "next_cursor": None},
            ],
        ) as request:
            verified = verify_comment("page", "token", "created-id", execution_id)

        self.assertTrue(verified)
        self.assertEqual(request.call_count, 2)
        self.assertTrue(all(c.args[0] == "GET" for c in request.call_args_list))

    def test_readback_rejects_content_mismatch_even_when_execution_id_matches(self):
        execution_id = "gh-126-attempt-1"
        expected = f"execution_id: {execution_id}\\nexpected full audit content"
        with patch(
            "scripts.notion_writeback.request_json",
            return_value={"results": [self.comment("created-id", execution_id)],
                          "has_more": False, "next_cursor": None},
        ), patch("scripts.notion_writeback.time.sleep"):
            self.assertFalse(verify_comment("page", "token", "created-id", execution_id, expected))

    def test_block_sequence_verification_requires_exact_complete_sequence(self):
        execution_id = "gh-200-attempt-1"
        expected = [
            {"type": "callout", "callout": {"rich_text": [{"type": "text", "text": {"content": f"執行識別：{execution_id}"}}]}},
            {"type": "heading_2", "heading_2": {"rich_text": [{"type": "text", "text": {"content": "技術突破"}}]}},
            {"type": "divider", "divider": {}},
        ]
        exact_readback = [
            {"type": "paragraph", "paragraph": {"rich_text": [{"plain_text": "older content"}]}},
            {"type": "callout", "callout": {"rich_text": [{"plain_text": f"執行識別：{execution_id}"}]}},
            {"type": "heading_2", "heading_2": {"rich_text": [{"plain_text": "技術突破"}]}},
            {"type": "divider", "divider": {}},
        ]
        self.assertTrue(verify_block_sequence(exact_readback, expected, execution_id))
        self.assertEqual(block_signature(exact_readback[2]), ("heading_2", "技術突破"))

    def test_block_sequence_verification_rejects_partial_or_mismatched_content(self):
        execution_id = "gh-201-attempt-1"
        expected = [
            {"type": "callout", "callout": {"rich_text": [{"type": "text", "text": {"content": f"執行識別：{execution_id}"}}]}},
            {"type": "heading_2", "heading_2": {"rich_text": [{"type": "text", "text": {"content": "原始標題"}}]}},
        ]
        partial = [expected[0]]
        mismatch = [
            expected[0],
            {"type": "heading_2", "heading_2": {"rich_text": [{"plain_text": "被修改的標題"}]}},
        ]
        self.assertFalse(verify_block_sequence(partial, expected, execution_id))
        self.assertFalse(verify_block_sequence(mismatch, expected, execution_id))


    def test_block_readback_retries_eventual_consistency_without_skipping_verification(self):
        execution_id = "gh-retry-attempt-1"
        expected = [
            {"type": "callout", "callout": {"rich_text": [{"type": "text", "text": {"content": f"執行識別：{execution_id}"}}]}},
            {"type": "heading_2", "heading_2": {"rich_text": [{"type": "text", "text": {"content": "技術突破"}}]}},
        ]
        delayed = [{"type": "callout", "callout": {"rich_text": [{"plain_text": f"執行識別：{execution_id}"}]}}]
        verified = [
            {"type": "callout", "callout": {"rich_text": [{"plain_text": f"執行識別：{execution_id}"}]}},
            {"type": "heading_2", "heading_2": {"rich_text": [{"plain_text": "技術突破"}]}},
        ]
        with patch("scripts.notion_writeback.list_page_blocks", side_effect=[delayed, verified]) as read, \
             patch("scripts.notion_writeback.time.sleep") as sleep:
            self.assertTrue(_readback_block_sequence("page", "token", expected, execution_id))
        self.assertEqual(read.call_count, 2)
        sleep.assert_called_once_with(0.5)

    def test_block_signature_normalizes_unicode_and_representation_noise_only(self):
        block = {"type": "paragraph", "paragraph": {"rich_text": [
            {"plain_text": "Cafe\u0301\u200b"}
        ]}}
        self.assertEqual(block_signature(block), ("paragraph", "Café"))

    def test_rejects_repeated_pagination_cursor(self):
        with patch(
            "scripts.notion_writeback.request_json",
            return_value={"results": [], "has_more": True, "next_cursor": "same"},
        ):
            with self.assertRaisesRegex(RuntimeError, "invalid cursor"):
                notion_writeback.list_comments("page", "token")

    def test_extracts_plain_text_from_notion_rich_text(self):
        comment = {
            "rich_text": [
                {"plain_text": "execution_id: gh-123"},
                {"plain_text": "attempt-1"},
            ]
        }
        self.assertEqual(text_from_comment(comment), "execution_id: gh-123attempt-1")


    def test_split_text_never_exceeds_notion_rich_text_limit(self):
        chunks = split_text(("字" * 1999) + "\n" + ("長" * 2500))
        self.assertTrue(chunks)
        self.assertTrue(all(len(chunk) <= 2000 for chunk in chunks))
        self.assertEqual("".join(chunks).replace("\n", ""), ("字" * 1999) + ("長" * 2500))

    def test_deep_briefing_contains_mobile_navigation_and_five_dimensions(self):
        blocks = build_deep_briefing_blocks(
            {"recent_72h_sample": {"videos": [
                {"title": "MCP agent workflow update", "channel_title": "Example Channel",
                 "description": "A workflow update and implementation detail.", "published_at": "2026-10-22",
                 "views": 1200, "likes": 80, "url": "https://example.com/video",
                 "tags": ["MCP", "agent"], "comments": [{"text": "Useful demo"}]},
            ]}},
            {"sample_count": 1, "generated_at": "2026-10-22T04:00:00+00:00"},
            "gh-test-attempt-1",
        )
        self.assertEqual(blocks[0]["type"], "callout")
        self.assertIn("執行識別：gh-test-attempt-1",
                      blocks[0]["callout"]["rich_text"][0]["text"]["content"])
        headings = [
            "".join(x["text"]["content"] for x in b["heading_2"]["rich_text"])
            for b in blocks if b["type"] == "heading_2"
        ]
        self.assertEqual(headings, [
            "🔥 熱門焦點", "🚀 技術突破", "💡 Agent/MCP 落地", "💬 社群熱議", "🛠️ 工具推薦"
        ])
        all_text = json.dumps(blocks, ensure_ascii=False)
        for expected in ("📜 事件背景", "⚙️ 核心機制", "💡 影響評估", "https://example.com/video"):
            self.assertIn(expected, all_text)

    def test_deep_briefing_blocks_match_notion_block_schema_and_text_limits(self):
        blocks = video_blocks({
            "title": "A" * 2500,
            "channel_title": "Example",
            "description": "B" * 5000,
            "url": "https://example.com/video",
        }, 1)
        self.assertEqual(blocks[0]["object"], "block")
        for block in blocks:
            self.assertIn("type", block)
            self.assertIn(block["type"], {
                "heading_3", "paragraph", "bulleted_list_item", "divider"
            })
            if block["type"] != "divider":
                payload = block[block["type"]]
                self.assertIn("rich_text", payload)
                for item in payload["rich_text"]:
                    self.assertLessEqual(len(item["text"]["content"]), 2000)
                    self.assertEqual(item["type"], "text")


if __name__ == "__main__":
    unittest.main()
