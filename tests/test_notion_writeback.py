import unittest

from scripts.notion_writeback import comment_text, text_from_comment


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
            {
                "generated_at": "2026-10-15T00:00:00Z",
                "verification": {"verified_72h": True},
                "recent_72h_sample": {
                    "per_query": {"AI賺錢": {"videos": [
                        {"video_id": "v1", "title": "AI 測試影片", "channel_title": "測試頻道",
                         "views": 500, "url": "https://www.youtube.com/watch?v=v1"}
                    ]}},
                    "videos": [{"video_id": "v1", "title": "AI 測試影片", "channel_title": "測試頻道",
                                "views": 500, "url": "https://www.youtube.com/watch?v=v1"}]
                },
            },
        )
        self.assertIn("execution_id：gh-123-attempt-2", text)
        self.assertIn("\n", text)
        self.assertNotIn("\\n", text)
        self.assertIn("每日 AI 趨勢雷達｜2026-10-15", text)
        self.assertIn("AI 測試影片", text)
        self.assertIn("500 次觀看", text)
        self.assertIn("reports/report.docx", text)
        self.assertIn("https://www.youtube.com/watch?v=v1", text)

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
