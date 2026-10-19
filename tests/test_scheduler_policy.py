import importlib.util
import json
import os
import re
import textwrap
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
        self.assertIn('if [ "$is_formal_run" != "true" ]', production)
        self.assertIn("scripts/recovery_policy.py", recovery)
        self.assertIn('cron: "20-59/10 22 * * *"', recovery)
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
        self.assertIn('"execution_id":os.environ["EXECUTION_ID"]', production)
        self.assertIn("data/last-successful-execution.json", production)
        self.assertIn('stamp=now.astimezone(ZoneInfo("Asia/Taipei")).strftime("%Y-%m-%d")', production)
        self.assertIn("report_date_taipei(now)", (ROOT / "scripts/build_daily_reports.py").read_text(encoding="utf-8"))
        self.assertIn("last-successful-execution.json?ref=main", recovery)
        self.assertIn("summary_execution_match", recovery)
        self.assertIn("manifest_execution_match", recovery)

    def test_daily_research_run_script_has_valid_bash_syntax(self):
        production = (ROOT / ".github/workflows/daily-youtube-research.yml").read_text(encoding="utf-8")
        self.assertIn("        run: |", production)
        script = textwrap.dedent(production.split("        run: |", 1)[1])
        script = re.sub(r"\\$\\{\\{.*?\\}\\}", "test-placeholder", script)
        result = subprocess.run(
            ["bash", "-n"], input=script, capture_output=True, text=True, check=False
        )
        self.assertEqual(result.returncode, 0, result.stderr)


    def _run_mocked_mcp_tool_call(self, empty_always=False):
        production = (ROOT / ".github/workflows/daily-youtube-research.yml").read_text(encoding="utf-8")
        run_script = textwrap.dedent(production.split("        run: |", 1)[1])
        start = run_script.index("call_tool() {")
        end = run_script.index("\n}", start) + 2
        function = run_script[start:end]

        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            bin_dir = temp / "bin"
            bin_dir.mkdir()
            curl = bin_dir / "curl"
            curl.write_text("""#!/usr/bin/env bash
set -eu
out=""
data=""
while [ "$#" -gt 0 ]; do
  case "$1" in
    -o) out="$2"; shift 2 ;;
    --data) data="$2"; shift 2 ;;
    -w) shift 2 ;;
    *) shift ;;
  esac
done
printf '%s\\n' "$data" >> "$CAPTURED_MCP_REQUESTS"
count=0
if [ -f "$MOCK_CURL_COUNT" ]; then count="$(cat "$MOCK_CURL_COUNT")"; fi
count=$((count + 1))
printf '%s' "$count" > "$MOCK_CURL_COUNT"
if [ "\${MOCK_EMPTY_ALWAYS:-0}" = "1" ] || [ "$count" -eq 1 ]; then
  : > "$out"
else
  printf 'data: {"jsonrpc":"2.0","id":3,"result":{"structuredContent":{"videos":[1]}}}\\n\\n' > "$out"
fi
printf '200'
""", encoding="utf-8")
            curl.chmod(0o755)
            sleep = bin_dir / "sleep"
            sleep.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
            sleep.chmod(0o755)
            env = os.environ.copy()
            env["PATH"] = f"{bin_dir}{os.pathsep}{env.get('PATH','')}"
            env["MCP_URL"] = "https://example.invalid/mcp"
            env["SESSION_ID"] = "unit-test-session"
            env["MOCK_CURL_COUNT"] = str(temp / "count.txt")
            env["CAPTURED_MCP_REQUESTS"] = str(temp / "requests.jsonl")
            if empty_always:
                env["MOCK_EMPTY_ALWAYS"] = "1"
            shell = function + '\ncall_tool out.body \'{"queries":["AI副業"],"videos_per_query":1}\'\n'
            result = subprocess.run(["bash", "-c", shell], cwd=temp, env=env, capture_output=True, text=True, check=False)
            count = int((temp / "count.txt").read_text(encoding="utf-8"))
            requests = (temp / "requests.jsonl").read_text(encoding="utf-8").splitlines()
            return result, count, requests, (temp / "out.body").read_text(encoding="utf-8") if (temp / "out.body").exists() else ""

    def test_mcp_empty_body_retries_once_and_sends_valid_json_rpc(self):
        result, count, requests, body = self._run_mocked_mcp_tool_call()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(count, 2)
        self.assertTrue(body.strip())
        self.assertEqual(len(requests), 2)
        payload = json.loads(requests[0])
        self.assertEqual(payload["method"], "tools/call")
        self.assertEqual(payload["params"]["name"], "youtube_research_sample")
        self.assertEqual(payload["params"]["arguments"]["queries"], ["AI副業"])

    def test_mcp_empty_body_fails_closed_after_bounded_retry(self):
        result, count, requests, body = self._run_mocked_mcp_tool_call(empty_always=True)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(count, 2)
        self.assertEqual(len(requests), 2)
        self.assertEqual(body, "")
        self.assertIn("failed after 2 attempts", result.stdout)

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
