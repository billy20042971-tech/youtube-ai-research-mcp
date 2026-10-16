import json
import tempfile
import unittest
from pathlib import Path

from scripts.daily_history import persist_history, update_history


class DailyHistoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.history_path = str(Path(self.temp.name) / "daily-summary-history.json")

    def tearDown(self):
        self.temp.cleanup()

    def test_first_run_is_baseline_and_persists_snapshot(self):
        result = update_history(
            [{"video_id": "a", "title": "Notion MCP 自動化"}],
            {}, {"stale_count": 0, "freshness_unknown_count": 0},
            "2026-10-14T22:00:00Z", self.history_path,
        )
        self.assertEqual(result["status"], "baseline")
        self.assertIsNone(result["new_video_count"])
        saved = json.loads(Path(self.history_path).read_text(encoding="utf-8"))
        self.assertEqual(len(saved["snapshots"]), 1)
        self.assertEqual(saved["snapshots"][0]["snapshot_date"], "2026-10-15")

    def test_cross_day_recurrence_and_new_video_comparison(self):
        update_history(
            [{"video_id": "a", "title": "Notion MCP 自動化"}], {},
            {"stale_count": 0, "freshness_unknown_count": 0},
            "2026-10-14T22:00:00Z", self.history_path,
        )
        update_history(
            [{"video_id": "a", "title": "Notion MCP 自動化"}], {},
            {"stale_count": 0, "freshness_unknown_count": 0},
            "2026-10-15T22:00:00Z", self.history_path,
        )
        result = update_history(
            [{"video_id": "b", "title": "Notion MCP 自動化"}], {},
            {"stale_count": 0, "freshness_unknown_count": 0},
            "2026-10-16T22:00:00Z", self.history_path,
        )
        self.assertEqual(result["status"], "history_available")
        self.assertEqual(result["new_video_count"], 1)
        observation = result["topic_observations"][0]
        self.assertEqual(observation["prior_runs_in_last_6"], 2)
        self.assertIn("仍需驗證", observation["classification"])

    def test_same_day_rerun_replaces_instead_of_duplicating(self):
        for video_id in ("a", "b"):
            update_history(
                [{"video_id": video_id, "title": "AI Agent 自動化"}], {},
                {"stale_count": 0, "freshness_unknown_count": 0},
                "2026-10-16T22:00:00Z", self.history_path,
            )
        saved = json.loads(Path(self.history_path).read_text(encoding="utf-8"))
        self.assertEqual(len(saved["snapshots"]), 1)
        self.assertEqual(saved["snapshots"][0]["video_ids"], ["b"])

    def test_deferred_persistence_waits_until_caller_commits_report(self):
        result, payload, path = update_history(
            [{"video_id": "a", "title": "AI Agent 自動化"}], {},
            {"stale_count": 0, "freshness_unknown_count": 0},
            "2026-10-16T22:00:00Z", self.history_path, persist=False,
        )
        self.assertEqual(result["status"], "baseline")
        self.assertFalse(Path(path).exists())
        persist_history(path, payload)
        self.assertTrue(Path(path).exists())

    def test_corrupt_history_fails_without_overwriting_it(self):
        Path(self.history_path).write_text("{broken", encoding="utf-8")
        with self.assertRaises(RuntimeError):
            update_history(
                [{"video_id": "a", "title": "AI Agent"}], {},
                {"stale_count": 0, "freshness_unknown_count": 0},
                "2026-10-16T22:00:00Z", self.history_path,
            )
        self.assertEqual(Path(self.history_path).read_text(encoding="utf-8"), "{broken")


    def test_snapshot_date_uses_taipei_calendar_day_at_utc_schedule_boundary(self):
        result = update_history(
            [{"video_id": "a", "title": "AI Agent 自動化"}], {},
            {"stale_count": 0, "freshness_unknown_count": 0},
            "2026-10-16T22:00:00Z", self.history_path, persist=False,
        )
        self.assertEqual(result[0]["snapshot_date"], "2026-10-17")
        self.assertEqual(result[1]["snapshots"][0]["snapshot_date"], "2026-10-17")

if __name__ == "__main__":
    unittest.main()
