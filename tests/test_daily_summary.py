import unittest

from scripts.daily_summary import build_summary, classify_topic


class DailySummaryTests(unittest.TestCase):
    def test_empty_sample_does_not_claim_a_trend(self):
        result = build_summary([])
        self.assertEqual(result["sample_count"], 0)
        self.assertEqual(result["signals"], [])
        self.assertIn("暫不判定", result["headline"])

    def test_cross_channel_topic_is_labeled_as_sample_signal_not_proven_trend(self):
        videos = [
            {"video_id": "1", "title": "AI Agent 自動化工作流", "channel_title": "A", "views": 900, "url": "https://example.com/1"},
            {"video_id": "2", "title": "MCP 與 Agent 自動化", "channel_title": "B", "views": 700, "url": "https://example.com/2"},
            {"video_id": "3", "title": "AI 自動化工作流程", "channel_title": "C", "views": 500, "url": "https://example.com/3"},
        ]
        result = build_summary(videos)
        self.assertEqual(result["sample_count"], 3)
        self.assertTrue(result["signals"])
        self.assertEqual(result["signals"][0]["classification"], "樣本訊號／待跨日確認")
        self.assertIn("跨日驗證", result["signals"][0]["evidence"])

    def test_views_do_not_become_a_reliability_claim(self):
        result = build_summary([
            {"video_id": "1", "title": "AI賺錢教學", "views": 1000000, "url": "https://example.com/1"}
        ])
        self.assertIn("觀看數不代表內容可靠", result["deep_dive"]["reason"])
        self.assertIsNone(result["deep_dive"]["timestamp"])
        self.assertIn("不直接證明需求", " ".join(result["limitations"]))

    def test_topic_classifier_handles_known_topics_and_fallback(self):
        self.assertEqual(classify_topic({"title": "AI Agent 自動化"}), "AI Agent／自動化")
        self.assertEqual(classify_topic({"title": "AI副業收入"}), "AI 副業／賺錢")
        self.assertEqual(classify_topic({"title": "未知主題"}), "其他／尚未分類")


def test_chart_label_contains_real_newline_not_literal_backslash_n():
    import re
    from textwrap import wrap
    text = re.sub(r"\\s+", " ", "這是一段足夠長的中文標題，用來檢查圖表標籤換行是否正確").strip()
    lines = wrap(text, width=18, break_long_words=True, break_on_hyphens=False)
    if len(lines) <= 2:
        label = "\n".join(lines)
    else:
        label = lines[0] + "\n" + lines[1][:15] + "…"
    assert "\n" in label
    assert "\n" not in label


if __name__ == "__main__":
    unittest.main()
