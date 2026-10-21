import importlib.util
import json
import os
import subprocess
import sys
import tempfile
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
        self.assertIn('if [ "$formal" != "true" ]', production)
        self.assertIn("schedule_on_time=", recovery)
        self.assertIn("(scheduled.hour, scheduled.minute) <= (6, 15)", recovery)
        self.assertIn('recovery=(trigger=="workflow_dispatch" and state.get("recovery_attempt") is True)', recovery)
        self.assertIn("scripts/recovery_policy.py", recovery)
        self.assertIn("sys.exit(1)", recovery)
        self.assertIn("verified production data is not complete.", recovery)
        self.assertIn("verified production state is incomplete; continuing to recovery policy.", recovery)
        self.assertIn("SELF_HEALING_POLICY:", recovery)
        self.assertIn("dispatch-response.txt", recovery)
        self.assertIn("Unexpected recovery dispatch HTTP status:", recovery)
        self.assertIn('if [ "$DISPATCH_HTTP_STATUS" = "200" ]', recovery)
        self.assertIn("workflow_run_id", recovery)
        self.assertIn("verifiable workflow_run_id", recovery)
        self.assertIn("CURL_EXIT_CODE=$?", recovery)
        self.assertIn("curl_exit_code=", recovery)
        self.assertNotIn('DISPATCH_HTTP_STATUS="$(curl --fail-with-body', recovery)
        parser = (ROOT / "scripts/mcp_sse.py").read_text(encoding="utf-8")
        self.assertIn("multiple data lines", parser)
        self.assertIn("parse_mcp_response_file", production)
        transport = (ROOT / "scripts/mcp_request.py").read_text(encoding="utf-8")
        evidence = (ROOT / "scripts/execution_evidence.py").read_text(encoding="utf-8")
        finalizer = (ROOT / "scripts/finalize_execution.py").read_text(encoding="utf-8")
        self.assertIn("max_attempts=2", transport)
        self.assertIn("retryable_http_status", transport)
        self.assertIn("data/last-successful-execution.json", evidence)
        self.assertIn("data/execution-history", evidence)
        self.assertIn("validate_execution_artifacts", evidence)
        self.assertIn("scripts/finalize_execution.py", production)
        self.assertIn("data/executions", production)
        self.assertIn('date = now.astimezone(ZoneInfo("Asia/Taipei")).strftime("%Y-%m-%d")',
                      (ROOT / "scripts/build_daily_reports.py").read_text(encoding="utf-8"))
        self.assertIn('"data_generated_at": src.get("generated_at")',
                      (ROOT / "scripts/build_daily_reports.py").read_text(encoding="utf-8"))
        self.assertIn("expected_text", (ROOT / "scripts/notion_writeback.py").read_text(encoding="utf-8"))
        self.assertIn("write_execution_state", finalizer)

    def test_durable_heartbeat_workflow_contract(self):
        heartbeat = (ROOT / ".github/workflows/scheduler-heartbeat.yml").read_text(encoding="utf-8")
        tests_workflow = (ROOT / ".github/workflows/scheduler-policy-tests.yml").read_text(encoding="utf-8")
        self.assertIn('cron: "16 22 * * *"', heartbeat)
        self.assertIn('runs?event=schedule', heartbeat)
        self.assertIn('created=${START_UTC_DATE}..${END_UTC_DATE}', heartbeat)
        self.assertIn('total_count == len(runs)', heartbeat)
        self.assertNotIn('total_count >= len(runs)', heartbeat)
        self.assertIn('run_started_at', heartbeat)
        self.assertIn('(6, 15)', heartbeat)
        self.assertIn('SCHEDULER_MISSED_DEADLINE', heartbeat)
        self.assertIn('data/scheduler-heartbeat.json', heartbeat)
        self.assertIn('git push origin HEAD:main', heartbeat)
        self.assertIn('.github/workflows/scheduler-heartbeat.yml', tests_workflow)



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

if __name__ == "__main__":
    unittest.main()
