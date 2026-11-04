import unittest

from scripts.report_analysis import (
    analyze_sample, chinese_title, classify_video, useful_comments,
    clean_description, tool_guidance, recommendation_reason,
    classify_language, actionable_guidance, LEGACY_GENERIC_ADVICE,
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
        self.assertEqual(
            chinese_title({"title": "这是一个简体中文标题"}),
            "中文意譯待確認（原始標題見附註）",
        )
        self.assertEqual(
            chinese_title({"title": "これは日本語のタイトルです"}),
            "中文意譯待確認（原始標題見附註）",
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

    def test_classifies_traditional_simplified_japanese_english_and_mixed(self):
        self.assertEqual(classify_language("這個工作流程可以提升效率"), "traditional_chinese")
        self.assertEqual(classify_language("这是一个简体中文标题"), "simplified_chinese")
        self.assertEqual(classify_language("これは日本語の説明です"), "japanese")
        self.assertEqual(classify_language("An English description"), "english")
        self.assertEqual(classify_language("這是 English 混合內容"), "mixed")

    def test_rejects_mixed_english_chinese_description(self):
        self.assertFalse(__import__("scripts.report_analysis", fromlist=["is_traditional_chinese"]).is_traditional_chinese(
            "這是 English description，包含完整英文句子"
        ))

    def test_rejects_japanese_kanji_and_ambiguous_text(self):
        self.assertFalse(__import__("scripts.report_analysis", fromlist=["is_traditional_chinese"]).is_traditional_chinese("日本語漢字だけ"))
        self.assertFalse(__import__("scripts.report_analysis", fromlist=["is_traditional_chinese"]).is_traditional_chinese("中文"))

    def test_filters_line_and_wechat_promotions(self):
        text = "這個工具可以整理資料並提升工作效率。\\n加入 LINE 官方帳號領取免費提示詞。\\n加我微信領取完整教學。"
        cleaned = clean_description(text)
        self.assertIn("整理資料", cleaned)
        self.assertNotIn("LINE", cleaned)
        self.assertNotIn("微信", cleaned)

    def test_filters_course_webinar_and_affiliate_promotions(self):
        text = "這個流程可以自動整理資料並產生報表。\\n免費線上講座立即報名，席位有限。\\n這是我的 affiliate link，購買可獲得優惠。"
        cleaned = clean_description(text)
        self.assertIn("自動整理資料", cleaned)
        self.assertNotIn("講座", cleaned)
        self.assertNotIn("affiliate", cleaned)

    def test_normalizes_html_breaks_before_promo_filtering(self):
        text = "這個工作流程可以減少重複輸入。<br /><br />免費課程報名：https://example.com<br>加我微信領取。"
        cleaned = clean_description(text)
        self.assertIn("工作流程", cleaned)
        self.assertNotIn("免費課程", cleaned)
        self.assertNotIn("微信", cleaned)

    def test_preserves_legitimate_line_automation_teaching(self):
        text = "這個案例說明 LINE 自動化客服如何串接表單與資料庫，並降低人工回覆時間。"
        self.assertIn("LINE 自動化客服", clean_description(text))

    def test_filters_purchase_and_download_calls_to_action(self):
        text = "這個工具能將資料整理成可搜尋的知識庫。\\n立即購買課程請點此連結。\\n免費下載完整手冊。"
        cleaned = clean_description(text)
        self.assertIn("知識庫", cleaned)
        self.assertNotIn("購買", cleaned)
        self.assertNotIn("下載", cleaned)

    def test_legacy_generic_advice_is_never_emitted(self):
        for title in ("Build a project with Claude Code", "Create with Higgsfield", "Unknown AI topic"):
            result = actionable_guidance({"title": title})
            output = " ".join([result.get("workflow", ""), *result.get("steps", [])])
            self.assertFalse(any(term in output for term in LEGACY_GENERIC_ADVICE))
            self.assertNotIn("30 分鐘", output)

    def test_unknown_tool_guidance_explicitly_requests_source(self):
        result = actionable_guidance({"title": "An unknown AI discussion"})
        self.assertIn("待補來源", result["workflow"])
        self.assertIn("逐字稿", " ".join(result["steps"]))

    def test_top3_matches_ranked_top_three(self):
        videos = [
            {"title": "這個工作流程有效", "views": 30},
            {"title": "這個工具提升效率", "views": 100},
            {"title": "這個方法改善工作", "views": 60},
            {"title": "這個案例值得研究", "views": 10},
        ]
        result = analyze_sample(videos)
        self.assertEqual(result["top3"], result["top"][:3])


if __name__ == "__main__":
    unittest.main()
