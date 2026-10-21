"""CLI entry point for evidence-bound execution state."""
import json
import os
import sys
from pathlib import Path
from execution_evidence import atomic_json, read_json, write_execution_state
from datetime import datetime, timezone

def ensure_failure_audit(root: Path, execution_id: str, reason: str, run_id: str) -> None:
    """Do not let a previous run's PASS remain the apparent latest audit after a new run fails."""
    audit_path = root / "data/notion-writeback-audit.json"
    current = read_json(audit_path)
    if current.get("execution_id") == execution_id:
        return
    record = {
        "execution_id": execution_id,
        "status": "NOT_RUN",
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "github_run_id": run_id,
        "writeback_verified": False,
        "readback_verified": False,
        "content_verified": False,
        "error": (reason or "Pipeline failed before Notion writeback was verified.")[:500],
    }
    atomic_json(audit_path, record)
    history_path = root / "data/execution-history" / (execution_id + "-notion-writeback-audit.json")
    atomic_json(history_path, record)


def main():
    eid = os.environ["EXECUTION_ID"]
    requested = os.environ["STATE_STATUS"]
    root = Path.cwd()
    if requested != "SUCCESS":
        ensure_failure_audit(root, eid, os.environ.get("STATE_FAILURE_REASON", ""),
                             os.environ.get("GITHUB_RUN_ID", ""))
    state, accepted = write_execution_state(
        Path.cwd(), execution_id=eid, started_at=os.environ.get("STARTED_AT", ""),
        github_run_id=os.environ.get("GITHUB_RUN_ID", ""),
        github_run_attempt=os.environ.get("GITHUB_RUN_ATTEMPT", "1"),
        trigger=os.environ.get("GITHUB_EVENT_NAME", ""),
        recovery_attempt=os.environ.get("RECOVERY_ATTEMPT", "false").lower() == "true",
        requested_status=requested, failure_reason=os.environ.get("STATE_FAILURE_REASON", ""),
        recovery_action=os.environ.get("STATE_RECOVERY_ACTION", ""), mcp_endpoint=os.environ.get("MCP_URL", ""),
    )
    print(json.dumps({k: state[k] for k in ("execution_id", "status", "artifact_gate_status",
                                               "artifact_gate_errors", "schedule_deadline_status")}, ensure_ascii=False))
    if requested == "SUCCESS" and not accepted:
        print("::error::Execution evidence gate rejected SUCCESS; last-successful pointer was not changed.", file=sys.stderr)
        return 1
    return 0

if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print("Execution finalization failed: " + type(exc).__name__, file=sys.stderr)
        raise SystemExit(1)
