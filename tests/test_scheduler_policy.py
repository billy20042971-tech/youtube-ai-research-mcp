import unittest
from datetime import datetime
from zoneinfo import ZoneInfo
from pathlib import Path

TAIPEI = ZoneInfo("Asia/Taipei")


def is_formal_run(event, recovery_attempt):
    return event == "schedule" or (event == "workflow_dispatch" and recovery_attempt is True)


def schedule_is_on_time(event, recovery_attempt, started_at, today):
    if event == "workflow_dispatch" and recovery_attempt is True:
        return True
    if event != "schedule" or not started_at:
        return False
    dt = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=ZoneInfo("UTC"))
    local = dt.astimezone(TAIPEI)
    return local.date().isoformat() == today and (local.hour, local.minute) <= (6, 15)


class SchedulerPolicyTests(unittest.TestCase):
    def test_formal_run_allowlist(self):
        self.assertTrue(is_formal_run("schedule", False))
        self.assertTrue(is_formal_run("workflow_dispatch", True))
        self.assertFalse(is_formal_run("workflow_dispatch", False))
        self.assertFalse(is_formal_run("push", False))
        self.assertFalse(is_formal_run("workflow_dispatch", "true"))

    def test_schedule_deadline_and_taipei_date(self):
        self.assertTrue(schedule_is_on_time("schedule", False, "2026-10-12T22:00:00Z", "2026-10-13"))
        self.assertTrue(schedule_is_on_time("schedule", False, "2026-10-12T22:15:00Z", "2026-10-13"))
        self.assertFalse(schedule_is_on_time("schedule", False, "2026-10-12T22:16:00Z", "2026-10-13"))
        self.assertFalse(schedule_is_on_time("schedule", False, "2026-10-12T22:00:00Z", "2026-10-12"))
        self.assertFalse(schedule_is_on_time("push", False, "2026-10-12T22:00:00Z", "2026-10-13"))

    def test_recovery_can_finish_after_deadline(self):
        self.assertTrue(schedule_is_on_time("workflow_dispatch", True, "2026-10-13T02:47:12Z", "2026-10-13"))
        self.assertFalse(schedule_is_on_time("workflow_dispatch", False, "2026-10-13T02:47:12Z", "2026-10-13"))

    def test_workflow_contains_production_guard_and_late_run_gate(self):
        root = Path(__file__).resolve().parents[1]
        production = (root / ".github/workflows/daily-youtube-research.yml").read_text(encoding="utf-8")
        recovery = (root / ".github/workflows/youtube-research-self-healing.yml").read_text(encoding="utf-8")
        self.assertIn('if [ "$GITHUB_EVENT_NAME" = "schedule" ]', production)
        self.assertIn('[ "$recovery_attempt" = "true" ]', production)
        self.assertIn('if [ "$is_formal_run" != "true" ]', production)
        self.assertIn('schedule_on_time=', recovery)
        self.assertIn('(scheduled.hour, scheduled.minute) <= (6, 15)', recovery)
        self.assertIn('recovery=(trigger=="workflow_dispatch" and state.get("recovery_attempt") is True)', recovery)


if __name__ == "__main__":
    unittest.main()
