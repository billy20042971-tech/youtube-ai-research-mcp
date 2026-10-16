import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class ReportFormattingTests(unittest.TestCase):
    def test_chart_and_pptx_newline_literals_are_actual_newlines(self):
        source = (ROOT / "scripts/build_daily_reports.py").read_text(encoding="utf-8")
        self.assertIn('"\\\\n".join(lines)', source)
        self.assertIn('"\\\\n".join(', source)
        self.assertNotIn('"\\\\\\\\n".join(lines)', source)
        self.assertNotIn('"\\\\\\\\n".join(', source)
        self.assertNotIn(' + "\\\\\\\\n" + ', source)


if __name__ == "__main__":
    unittest.main()
