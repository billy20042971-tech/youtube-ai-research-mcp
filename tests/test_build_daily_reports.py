import unittest
from pathlib import Path

from scripts.report_analysis import actionable_guidance, LEGACY_GENERIC_ADVICE


class DailyReportRenderingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = Path("scripts/build_daily_reports.py").read_text(encoding="utf-8")

    def test_renderer_uses_actionable_guidance_everywhere(self):
        self.assertNotIn("tool_guidance", self.source)
        self.assertGreaterEqual(self.source.count("actionable_guidance(v)"), 2)

    def test_docx_and_pptx_render_guidance_from_same_guarded_result(self):
        self.assertIn('guide = actionable_guidance(v)', self.source)
        self.assertIn('guide["workflow"]', self.source)
        self.assertIn('guide["steps"]', self.source)

    def test_top_three_precedes_trends_and_category_insights_in_markdown(self):
        top3 = self.source.index('"## ⭐ 今日 Top 3 必看推薦"')
        trends = self.source.index('"## 🚀 今日 3 分鐘核心趨勢摘要"')
        categories = self.source.index('"## 📊 主題分類洞察"')
        self.assertLess(top3, trends)
        self.assertLess(trends, categories)

    def test_markdown_report_is_written_as_a_separate_artifact(self):
        self.assertIn('YouTube_AI趨勢研究雷達_{date}_報告.md', self.source)
        self.assertIn('write_text', self.source)

    def test_guarded_guidance_never_contains_legacy_generic_advice(self):
        for title in ("Build a project with Claude Code", "Create with Higgsfield", "Unknown AI topic"):
            guide = actionable_guidance({"title": title})
            rendered = " ".join([guide.get("workflow", ""), *guide.get("steps", [])])
            self.assertFalse(any(phrase in rendered for phrase in LEGACY_GENERIC_ADVICE))
            self.assertNotIn("30 分鐘", rendered)


if __name__ == "__main__":
    unittest.main()
