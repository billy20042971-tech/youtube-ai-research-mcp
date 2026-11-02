import unittest

from scripts.report_analysis import analyze_sample, chinese_title, classify_video, useful_comments


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
        self.assertTrue(chinese_title({"title": "An unknown English title"}).startswith("中文意譯待確認："))

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


if __name__ == "__main__":
    unittest.main()
