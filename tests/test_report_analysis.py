import unittest

from scripts.report_analysis import (
    analyze_sample, chinese_title, classify_video, useful_comments,
    clean_description, tool_guidance, recommendation_reason,
)


class ReportAnalysisTests(unittest.TestCase):
    def test_classifies_business_content(self):
        self.assertEqual(
            classify_video({"title": "AI 副業變現與數位產品", "description": "side hustle"}),
            "AI 副業變現",
        )

    def test_classifies_industry_and_investment(self):
        self.assertEqual(
            classify_video({"title": "台積電與半導體產業投資觀點"}),
            "產業與投資觀點",
        )

    def test_filters_promotional_comments(self):
        comments = [
            {"text": "點擊連結加入會員領取課程，現在有折扣碼"},
            {"text": "我照著步驟操作後，發現軟體設定比想像中複雜很多"},
            {"text": "👍"},
            {"text": "This workflow saved me hours every week"},
        ]
        self.assertEqual(
            useful_comments({"comments": comments}),
            ["我照著步驟操作後，發現軟體設定比想像中複雜很多"],
        )

    def test_english_title_translation_is_not_fabricated(self):
        self.assertEqual(
            chinese_title({"title": "The Easiest Claude AI Side Hustle Everyone Is Overlooking"}),
            "多數人忽略的 Claude AI 簡易副業機會",
        )
        self.assertEqual(
            chinese_title({"title": "An unknown English title"}),
            "中文意譯待確認（原始標題見附註）",
        )
        self.assertEqual(
            chinese_title({"title": "A title", "title_zh": "繁體中文標題"}),
            "繁體中文標題",
        )

    def test_description_filter_removes_channel_bio_and_ads(self):
        text = """這個工作流程可以將商品資料轉成刊登草稿，並減少重複輸入。
歡迎來到我的頻道，記得訂閱並按讚。
加入 LINE 官方帳號領取免費 Prompt：https://example.com
The creator explains their personal journey."""
        cleaned = clean_description(text)
        self.assertIn("工作流程", cleaned)
        self.assertNotIn("訂閱", cleaned)
        self.assertNotIn("LINE", cleaned)
        self.assertNotIn("personal journey", cleaned)

    def test_tool_specific_steps_are_concrete(self):
        guide = tool_guidance({"title": "Build a project with Claude Code"})
        self.assertIn("Claude Code", guide["label"])
        self.assertEqual(len(guide["steps"]), 3)
        self.assertIn("Git", guide["steps"][0])
        self.assertNotIn("30 分鐘", " ".join(guide["steps"]))

    def test_unknown_tool_does_not_invent_video_workflow(self):
        guide = tool_guidance({"title": "A general AI discussion"})
        self.assertIn("來源未提供", guide["label"])
        self.assertIn("逐字稿", " ".join(guide["steps"]))

    def test_recommendation_reason_is_grounded_in_video_metadata(self):
        self.assertIn(
            "AI 商業化",
            recommendation_reason({"title": "AI business case study with revenue"}),
        )

    def test_analysis_has_four_theme_buckets_and_top_three_signals(self):
        sample = [
            {"title": "AI 副業賺錢", "views": 100, "likes": 10, "comments": []},
            {"title": "AI 自動化工作流省時", "views": 200, "likes": 20, "comments": []},
            {"title": "AI 影片數位人", "views": 300, "likes": 30, "comments": []},
            {"title": "台股半導體投資", "views": 400, "likes": 40, "comments": []},
        ]
        result = analyze_sample(sample)
        self.assertIn("AI 副業變現", result["buckets"])
        self.assertEqual(len(result["signals"]), 3)
        self.assertEqual(len(result["top"]), 4)
        self.assertEqual(len(result["top3"]), 3)


if __name__ == "__main__":
    unittest.main()
