import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

TAIPEI = ZoneInfo("Asia/Taipei")
DEADLINE = (6, 15)


def parse_local(value):
    if not isinstance(value, str) or not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            return None
        return dt.astimezone(TAIPEI)
    except (TypeError, ValueError):
        return None


def heartbeat_decision(payload, today):
    """Pure decision helper mirroring Heartbeat's fail-closed evidence policy."""
    if not isinstance(payload, dict):
        return {"status": "UNDETERMINED_API_RESPONSE", "reason": "payload_not_object"}
    runs = payload.get("workflow_runs")
    total = payload.get("total_count")
    if not isinstance(runs, list) or not isinstance(total, int) or total < len(runs):
        return {"status": "UNDETERMINED_API_RESPONSE", "reason": "runs_payload_incomplete_or_invalid"}

    invalid = []
    todays = []
    for run in runs:
        if not isinstance(run, dict) or run.get("event") != "schedule":
            continue
        created = parse_local(run.get("created_at"))
        started = parse_local(run.get("run_started_at"))
        if created and created.date().isoformat() == today and started is None:
            invalid.append(run.get("id"))
        if started and started.date().isoformat() == today:
            todays.append((run, started))

    eligible = [(run, started) for run, started in todays
                if (started.hour, started.minute) <= DEADLINE]
    eligible.sort(key=lambda item: item[1])
    if invalid:
        return {"status": "UNDETERMINED_RUN_TIMESTAMP", "reason": "today_schedule_run_has_missing_or_invalid_started_at"}
    if eligible:
        return {"status": "ON_TIME_RUN_FOUND", "run_id": eligible[-1][0].get("id")}
    return {"status": "SCHEDULER_MISSED_DEADLINE", "reason": "complete_run_list_contains_no_today_schedule_started_by_0615"}


class HeartbeatEvidenceTests(unittest.TestCase):
    def test_on_time_schedule_run(self):
        payload = {"total_count": 1, "workflow_runs": [
            {"id": 7, "event": "schedule", "created_at": "2026-10-15T22:00:00Z", "run_started_at": "2026-10-15T22:03:00Z"}
        ]}
        self.assertEqual(heartbeat_decision(payload, "2026-10-16")["status"], "ON_TIME_RUN_FOUND")

    def test_after_deadline_is_missed_even_if_schedule_ran(self):
        payload = {"total_count": 1, "workflow_runs": [
            {"id": 7, "event": "schedule", "created_at": "2026-10-15T22:00:00Z", "run_started_at": "2026-10-15T22:16:00Z"}
        ]}
        self.assertEqual(heartbeat_decision(payload, "2026-10-16")["status"], "SCHEDULER_MISSED_DEADLINE")

    def test_recovery_does_not_count_as_formal_schedule(self):
        payload = {"total_count": 1, "workflow_runs": [
            {"id": 9, "event": "workflow_dispatch", "created_at": "2026-10-15T23:00:00Z", "run_started_at": "2026-10-15T23:00:00Z"}
        ]}
        self.assertEqual(heartbeat_decision(payload, "2026-10-16")["status"], "SCHEDULER_MISSED_DEADLINE")

    def test_empty_complete_result_is_a_confirmed_miss(self):
        self.assertEqual(heartbeat_decision({"total_count": 0, "workflow_runs": []}, "2026-10-16")["status"], "SCHEDULER_MISSED_DEADLINE")

    def test_missing_total_count_is_undetermined(self):
        result = heartbeat_decision({"workflow_runs": []}, "2026-10-16")
        self.assertEqual(result["status"], "UNDETERMINED_API_RESPONSE")

    def test_api_count_inconsistent_with_returned_runs_is_undetermined(self):
        result = heartbeat_decision({"total_count": 0, "workflow_runs": [{"id": 1}]}, "2026-10-16")
        self.assertEqual(result["status"], "UNDETERMINED_API_RESPONSE")

    def test_today_run_with_bad_timestamp_is_undetermined(self):
        payload = {"total_count": 1, "workflow_runs": [
            {"id": 3, "event": "schedule", "created_at": "2026-10-15T22:00:00Z", "run_started_at": "bad"}
        ]}
        self.assertEqual(heartbeat_decision(payload, "2026-10-16")["status"], "UNDETERMINED_RUN_TIMESTAMP")

    def test_timezone_day_boundary(self):
        payload = {"total_count": 1, "workflow_runs": [
            {"id": 4, "event": "schedule", "created_at": "2026-10-15T15:59:00Z", "run_started_at": "2026-10-15T16:00:00Z"}
        ]}
        self.assertEqual(heartbeat_decision(payload, "2026-10-16")["status"], "ON_TIME_RUN_FOUND")

    def test_missing_started_at_on_created_today_is_undetermined(self):
        payload = {"total_count": 1, "workflow_runs": [
            {"id": 5, "event": "schedule", "created_at": "2026-10-15T22:00:00Z"}
        ]}
        self.assertEqual(heartbeat_decision(payload, "2026-10-16")["status"], "UNDETERMINED_RUN_TIMESTAMP")


if __name__ == "__main__":
    unittest.main()
