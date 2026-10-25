import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone

from scripts.schedule_timing import expected_slot, schedule_lateness_minutes, validate_schedule_start
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class RemainingSafetyTests(unittest.TestCase):
    def test_mcp_handshake_does_not_consume_youtube_api_quota(self):
        handshake = (ROOT / ".github/workflows/mcp-handshake-test.yml").read_text(encoding="utf-8")
        self.assertIn("tools/list", handshake)
        self.assertIn("tools.body", handshake)
        self.assertIn("without consuming YouTube API quota", handshake)
        self.assertNotIn('"method":"tools/call"', handshake)
        self.assertNotIn("name: Call YouTube research tool", handshake)
        self.assertNotIn("tool.body", handshake)

    def test_missing_notion_credentials_fail_closed_and_write_skipped_audit(self):
        script = ROOT / "scripts/notion_writeback.py"
        with tempfile.TemporaryDirectory() as temp_dir:
            env = os.environ.copy()
            env.pop("NOTION_API_KEY", None)
            env.pop("NOTION_PAGE_ID", None)
            env["GITHUB_RUN_ID"] = "test-run"
            env["GITHUB_RUN_ATTEMPT"] = "1"
            result = subprocess.run(
                [sys.executable, str(script)],
                cwd=temp_dir,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            audit_path = Path(temp_dir) / "data/notion-writeback-audit.json"
            self.assertTrue(audit_path.is_file())
            audit = json.loads(audit_path.read_text(encoding="utf-8"))
            self.assertEqual(audit["status"], "SKIPPED_MISSING_CREDENTIALS")
            self.assertFalse(audit["writeback_verified"])
            self.assertFalse(audit["token_configured"])
            self.assertFalse(audit["page_id_configured"])


    def test_schedule_gate_accepts_on_time_and_small_queue_delay(self):
        now = datetime(2026, 10, 24, 22, 10, tzinfo=timezone.utc)
        self.assertEqual(expected_slot(now), datetime(2026, 10, 24, 22, 0, tzinfo=timezone.utc))
        self.assertEqual(schedule_lateness_minutes(now), 10)
        validate_schedule_start(now, max_lateness_minutes=15)

    def test_schedule_gate_rejects_materially_late_run(self):
        now = datetime(2026, 10, 24, 23, 53, tzinfo=timezone.utc)
        self.assertEqual(schedule_lateness_minutes(now), 113)
        with self.assertRaisesRegex(RuntimeError, "missed its start deadline"):
            validate_schedule_start(now, max_lateness_minutes=15)

    def test_schedule_gate_handles_after_midnight_delay(self):
        now = datetime(2026, 10, 25, 0, 5, tzinfo=timezone.utc)
        self.assertEqual(expected_slot(now), datetime(2026, 10, 24, 22, 0, tzinfo=timezone.utc))
        self.assertEqual(schedule_lateness_minutes(now), 125)


    def test_report_paths_use_taipei_calendar_date(self):
        workflow = (ROOT / ".github/workflows/daily-youtube-research.yml").read_text(encoding="utf-8")
        report_builder = (ROOT / "scripts/build_daily_reports.py").read_text(encoding="utf-8")
        self.assertIn('from zoneinfo import ZoneInfo', workflow)
        self.assertIn('stamp=now.astimezone(ZoneInfo("Asia/Taipei")).strftime("%Y-%m-%d")', workflow)
        self.assertIn('date = now.astimezone(ZoneInfo("Asia/Taipei")).strftime("%Y-%m-%d")', report_builder)


if __name__ == "__main__":
    unittest.main()
