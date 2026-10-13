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
        )
        self.assertIn("execution_id: gh-123-attempt-2", text)
        self.assertIn("sample_count: 40", text)
        self.assertIn("reports/report.docx", text)
        self.assertIn("verified_72h: True", text)

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
