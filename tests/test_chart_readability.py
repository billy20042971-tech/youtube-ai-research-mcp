from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class ChartReadabilityContractTests(unittest.TestCase):
    def test_top_ten_chart_reserves_space_and_labels_values(self):
        source = (ROOT / "scripts/build_daily_reports.py").read_text(encoding="utf-8")
        self.assertIn("fig, ax = plt.subplots(figsize=(14, fig_height))", source)
        self.assertIn("ax.set_xlim(0, max_value * 1.18 if max_value else 1)", source)
        self.assertIn("for bar, value in zip(bars, values):", source)
        self.assertIn('f"{value:,}"', source)
        self.assertIn("ax.annotate(", source)
        self.assertIn("clip_on=False", source)

    def test_chart_titles_are_wrapped_and_truncated_predictably(self):
        source = (ROOT / "scripts/build_daily_reports.py").read_text(encoding="utf-8")
        self.assertIn("lines = wrap(text, width=15", source)
        self.assertIn('lines = [lines[0], lines[1][:13] + "…"]', source)


if __name__ == "__main__":
    unittest.main()
