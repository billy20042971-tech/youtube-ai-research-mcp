import importlib.util
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("recovery_policy", ROOT / "scripts/recovery_policy.py")
recovery_policy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(recovery_policy)

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

    def test_recovery_policy_counts_only_explicit_recovery_dispatches(self):
        runs = [
            {"id": 1, "event": "workflow_dispatch", "display_title": "Daily YouTube Research (recovery=true)", "created_at": "2026-10-12T22:30:00Z", "status": "completed"},
            {"id": 2, "event": "workflow_dispatch", "display_title": "Daily YouTube Research (recovery=false)", "created_at": "2026-10-12T22:31:00Z", "status": "completed"},
            {"id": 3, "event": "schedule", "display_title": "Daily YouTube Research (recovery=false)", "created_at": "2026-10-12T22:00:00Z", "status": "completed"},
            {"id": 4, "event": "workflow_dispatch", "display_title": "Daily YouTube Research (recovery=true)", "created_at": "2026-10-12T15:00:00Z", "status": "completed"},
        ]
        result = recovery_policy.recovery_decision(runs, "2026-10-13", 5)
        self.assertEqual(result["decision"], "yes")
        self.assertEqual(result["recovery_dispatches"], 1)

    def test_recovery_policy_blocks_when_active_run_exists(self):
        runs = [
            {"id": 22, "event": "schedule", "display_title": "Daily YouTube Research", "created_at": "2026-10-12T22:00:00Z", "status": "in_progress"},
        ]
        result = recovery_policy.recovery_decision(runs, "2026-10-13", 5)
        self.assertEqual(result["decision"], "no")
        self.assertEqual(result["reason"], "active_run")
        self.assertEqual(result["active_run_ids"], [22])

    def test_recovery_policy_enforces_cap_and_retry_boundary(self):
        runs = [
            {"id": i, "event": "workflow_dispatch", "display_title": "Daily YouTube Research (recovery=true)", "created_at": f"2026-10-12T22:{30+i:02d}:00Z", "status": "completed"}
            for i in range(5)
        ]
        self.assertEqual(recovery_policy.recovery_decision(runs, "2026-10-13", 5)["reason"], "recovery_cap")
        self.assertEqual(recovery_policy.recovery_decision(runs[:4], "2026-10-13", 5)["decision"], "yes")

    def test_recovery_policy_handles_taipei_date_boundary_and_malformed_time(self):
        runs = [
            {"id": 1, "event": "workflow_dispatch", "display_title": "Daily YouTube Research (recovery=true)", "created_at": "2026-10-12T15:59:59Z", "status": "completed"},
            {"id": 2, "event": "workflow_dispatch", "display_title": "Daily YouTube Research (recovery=true)", "created_at": "not-a-time", "status": "completed"},
        ]
        result = recovery_policy.recovery_decision(runs, "2026-10-13", 5)
        self.assertEqual(result["decision"], "yes")
        self.assertEqual(result["recovery_dispatches"], 0)

    def test_workflow_contains_production_guard_late_run_gate_and_tested_policy(self):
        production = (ROOT / ".github/workflows/daily-youtube-research.yml").read_text(encoding="utf-8")
        recovery = (ROOT / ".github/workflows/youtube-research-self-healing.yml").read_text(encoding="utf-8")
        self.assertIn('if [ "$GITHUB_EVENT_NAME" = "schedule" ]', production)
        self.assertIn('[ "$recovery_attempt" = "true" ]', production)
        self.assertIn('if [ "$is_formal_run" != "true" ]', production)
        self.assertIn("schedule_on_time=", recovery)
        self.assertIn("(scheduled.hour, scheduled.minute) <= (6, 15)", recovery)
        self.assertIn('recovery=(trigger=="workflow_dispatch" and state.get("recovery_attempt") is True)', recovery)
        self.assertIn("scripts/recovery_policy.py", recovery)

    def test_durable_heartbeat_workflow_contract(self):
        heartbeat = (ROOT / ".github/workflows/scheduler-heartbeat.yml").read_text(encoding="utf-8")
        tests_workflow = (ROOT / ".github/workflows/scheduler-policy-tests.yml").read_text(encoding="utf-8")
        self.assertIn('cron: "16 22 * * *"', heartbeat)
        self.assertIn('data/scheduler-heartbeat.json', heartbeat)
        self.assertIn('git push origin HEAD:main', heartbeat)
        self.assertIn('.github/workflows/scheduler-heartbeat.yml', tests_workflow)


if __name__ == "__main__":
    unittest.main()
