import unittest
from unittest.mock import call, patch

from scripts import notion_writeback
from scripts.notion_writeback import (
    comment_text,
    ensure_comment,
    find_existing_comment,
    text_from_comment,
    verify_comment,
)


class NotionWritebackTests(unittest.TestCase):
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

    def test_retry_reuses_existing_comment_without_posting_duplicate(self):
        execution_id = "gh-123-attempt-1"
        with patch(
            "scripts.notion_writeback.request_json",
            return_value={"results": [self.comment("existing-id", execution_id)],
                          "has_more": False, "next_cursor": None},
        ) as request:
            comment_id = ensure_comment("page", "token", execution_id, f"execution_id: {execution_id}\\nnew content")

        self.assertEqual(comment_id, "existing-id")
        self.assertTrue(all(args.args[0] == "GET" for args in request.call_args_list))
        self.assertFalse(any(args.args[0] == "POST" for args in request.call_args_list))

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
        ):
            self.assertFalse(verify_comment("page", "token", "created-id", execution_id, expected))

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


if __name__ == "__main__":
    unittest.main()
