import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("notion_writeback", ROOT / "scripts/notion_writeback.py")
notion_writeback = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(notion_writeback)


class DailyNotionSummaryTests(unittest.TestCase):
    def test_comment_contains_daily_summary_top_videos_and_artifact_paths(self):
        latest = {
            "generated_at": "2026-10-15T02:00:00+00:00",
            "verification": {"verified_72h": True},
            "recent_72h_sample": {
                "per_query": {
                    "AI賺錢": {"videos": [
                        {"video_id": "v1", "title": "AI 新工具趨勢", "channel_title": "研究頻道",
                         "published_at": "2026-10-14T12:00:00Z", "views": 12345,
                         "url": "https://www.youtube.com/watch?v=v1"}
                    ]}
                },
                "videos": [{"video_id": "v1", "title": "AI 新工具趨勢", "channel_title": "研究頻道",
                            "views": 12345, "url": "https://www.youtube.com/watch?v=v1"}]
            }
        }
        manifest = {"sample_count": 1, "word": "reports/2026-10-15/report.docx",
                    "pptx": "reports/2026-10-15/brief.pptx", "chart": "reports/2026-10-15/top10.png"}
        state = {"github_run_id": "123", "trigger": "schedule",
                 "data_verification": {"verified_72h": True}}
        text = notion_writeback.comment_text("gh-123-attempt-1", manifest, state, latest)
        self.assertIn("每日 AI 趨勢雷達｜2026-10-15", text)
        self.assertIn("AI 新工具趨勢", text)
        self.assertIn("12,345 次觀看", text)
        self.assertIn("https://www.youtube.com/watch?v=v1", text)
        self.assertIn("reports/2026-10-15/report.docx", text)
        self.assertIn("execution_id：gh-123-attempt-1", text)
        self.assertLessEqual(len(text), 1900)

    def test_missing_videos_still_produces_auditable_message(self):
        text = notion_writeback.comment_text("gh-empty", {}, {}, {"generated_at": "2026-10-15T00:00:00Z"})
        self.assertIn("每日 AI 趨勢雷達｜2026-10-15", text)
        self.assertIn("樣本數：0", text)


if __name__ == "__main__":
    unittest.main()
