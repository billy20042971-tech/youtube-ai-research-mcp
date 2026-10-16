import unittest
from pathlib import Path


class DailyReportEvidenceIntegrationTests(unittest.TestCase):
    def test_evidence_metadata_flows_to_word_pptx_and_manifest(self):
        source = Path("scripts/build_daily_reports.py").read_text(encoding="utf-8")
        self.assertIn("from scripts.daily_summary_evidence import evidence_metadata", source)
        self.assertIn("證據狀態：{evidence['trend_status']}", source)
        self.assertIn("來源獨立性：{signal['source_independence']}", source)
        self.assertIn('slide("一分鐘決策摘要"', source)
        self.assertIn("來源獨立性未驗證；工作關聯為關鍵字初篩。", source)
        self.assertIn('"evidence_summary": evidence', source)

    def test_duplicate_count_is_measured_before_deduplication(self):
        source = Path("scripts/build_daily_reports.py").read_text(encoding="utf-8")
        self.assertIn('raw_video_count = sum(1 for video in videos if video.get("video_id"))', source)
        self.assertIn('evidence["duplicate_count"] = max(0, raw_video_count - len(videos))', source)

    def test_chart_labels_use_real_newline_separators(self):
        source = Path("scripts/build_daily_reports.py").read_text(encoding="utf-8")
        quote, slash = chr(34), chr(92)
        self.assertIn("return " + quote + slash + "n" + quote + ".join(lines)", source)
        self.assertNotIn("return " + quote + slash * 2 + "n" + quote + ".join(lines)", source)


if __name__ == "__main__":
    unittest.main()
