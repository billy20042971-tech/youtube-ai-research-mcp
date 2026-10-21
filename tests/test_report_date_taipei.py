import unittest
from datetime import datetime, timezone

from scripts.report_dates import report_date_taipei


class ReportDateTaipeiTests(unittest.TestCase):
    def test_utc_evening_maps_to_next_taipei_day(self):
        self.assertEqual(report_date_taipei(datetime(2026, 10, 18, 22, 0, tzinfo=timezone.utc)), "2026-10-19")

    def test_one_second_before_taipei_midnight_stays_previous_day(self):
        self.assertEqual(report_date_taipei(datetime(2026, 10, 18, 15, 59, 59, tzinfo=timezone.utc)), "2026-10-18")

    def test_naive_datetime_is_treated_as_utc(self):
        self.assertEqual(report_date_taipei(datetime(2026, 10, 18, 22, 0)), "2026-10-19")


if __name__ == "__main__":
    unittest.main()
