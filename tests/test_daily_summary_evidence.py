import unittest
from scripts.daily_summary_evidence import evidence_metadata


class EvidenceMetadataTests(unittest.TestCase):
    def test_stale_and_unknown_dates_are_not_claimed_fresh(self):
        rows = evidence_metadata([
            {"video_id": "a", "title": "AI 自動化工作流", "published_at": "2026-10-10T00:00:00Z", "channel_title": "A"},
            {"video_id": "b", "title": "無日期影片", "channel_title": "B"},
        ], "2026-10-16T00:00:00Z")
        self.assertEqual(rows["stale_count"], 1)
        self.assertEqual(rows["freshness_unknown_count"], 1)
        self.assertEqual(rows["trend_status"], "資料不足，不判定已證實趨勢")

    def test_duplicates_are_deduplicated_and_source_independence_stays_unverified(self):
        video = {"video_id": "same", "title": "MCP 自動化", "published_at": "2026-10-15T00:00:00Z", "channel_title": "A"}
        rows = evidence_metadata([video, dict(video)], "2026-10-16T00:00:00Z")
        self.assertEqual(rows["sample_count"], 1)
        self.assertEqual(rows["duplicate_count"], 1)
        self.assertIn("未驗證", rows["signals"][0]["source_independence"])

    def test_work_relevance_is_explicit_or_says_none_found(self):
        rows = evidence_metadata([
            {"video_id": "a", "title": "Notion MCP 自動化", "published_at": "2026-10-15T00:00:00Z"},
            {"video_id": "b", "title": "一般生活分享", "published_at": "2026-10-15T00:00:00Z"},
        ], "2026-10-16T00:00:00Z")
        self.assertIn("Notion／AI 自動化", rows["signals"][0]["work_relevance"])
        self.assertEqual(rows["signals"][1]["work_relevance"], ["未發現明確工作關聯"])

    def test_invalid_or_future_dates_are_not_fresh(self):
        rows = evidence_metadata([
            {"video_id": "a", "title": "A", "published_at": "bad"},
            {"video_id": "b", "title": "B", "published_at": "2026-10-17T00:00:00Z"},
        ], "2026-10-16T00:00:00Z")
        self.assertEqual(rows["freshness_unknown_count"], 1)
        self.assertEqual(rows["signals"][1]["freshness"], "未來時間異常")


if __name__ == "__main__":
    unittest.main()
