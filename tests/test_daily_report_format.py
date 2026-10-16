import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class ReportFormattingTests(unittest.TestCase):
    def test_chart_and_pptx_use_single_escape_for_line_breaks(self):
        source = (ROOT / "scripts/build_daily_reports.py").read_text(encoding="utf-8")
        slash = chr(92)
        good_join = '"' + slash + 'n".join('
        bad_join = '"' + slash * 2 + 'n".join('
        self.assertIn(good_join, source)
        self.assertNotIn(bad_join, source)
        self.assertIn('summary["headline"] + "' + slash + 'n" + "' + slash + 'n".join(', source)
        self.assertIn('"' + slash + 'n".join("• " + x', source)


if __name__ == "__main__":
    unittest.main()
