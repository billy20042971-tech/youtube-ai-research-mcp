#!/usr/bin/env python3
"""Deterministic policy for deciding whether another recovery dispatch is allowed."""
import argparse
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

TAIPEI = ZoneInfo("Asia/Taipei")
ACTIVE_STATUSES = {"queued", "in_progress"}


def taipei_date(value):
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=ZoneInfo("UTC"))
        return dt.astimezone(TAIPEI).date().isoformat()
    except (TypeError, ValueError):
        return None


def is_recovery_dispatch(run):
    return (
        run.get("event") == "workflow_dispatch"
        and "recovery=true" in (run.get("display_title") or "").lower()
    )


def recovery_decision(runs, today, max_recoveries=5):
    todays = [
        run for run in runs
        if taipei_date(run.get("created_at")) == today
    ]
    active = [
        run for run in todays
        if run.get("status") in ACTIVE_STATUSES
    ]
    recovery_runs = [run for run in todays if is_recovery_dispatch(run)]
    # Fail closed: if the API data contains an active run, do not dispatch.
    if active:
        return {
            "decision": "no",
            "reason": "active_run",
            "active_run_ids": [r.get("id") for r in active],
            "recovery_dispatches": len(recovery_runs),
        }
    if len(recovery_runs) >= max_recoveries:
        return {
            "decision": "no",
            "reason": "recovery_cap",
            "active_run_ids": [],
            "recovery_dispatches": len(recovery_runs),
        }
    return {
        "decision": "yes",
        "reason": "recovery_allowed",
        "active_run_ids": [],
        "recovery_dispatches": len(recovery_runs),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", required=True)
    parser.add_argument("--today", required=True, help="Asia/Taipei YYYY-MM-DD")
    parser.add_argument("--max-recoveries", type=int, default=5)
    args = parser.parse_args()
    if args.max_recoveries < 0:
        raise SystemExit("--max-recoveries must be >= 0")
    payload = json.loads(Path(args.runs).read_text(encoding="utf-8"))
    runs = payload.get("workflow_runs")
    if not isinstance(runs, list):
        raise SystemExit("workflow_runs missing or invalid; fail closed")
    result = recovery_decision(runs, args.today, args.max_recoveries)
    print(json.dumps(result, ensure_ascii=False))
    print(result["decision"])


if __name__ == "__main__":
    main()
