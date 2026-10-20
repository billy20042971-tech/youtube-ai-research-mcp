"""Execution-bound data, report, audit validation, and durable state pointers."""
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

TAIPEI = ZoneInfo("Asia/Taipei")

def read_json(path):
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}

def atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(path)

def schedule_deadline_status(trigger, started_at):
    if trigger != "schedule":
        return "NOT_APPLICABLE_RECOVERY_OR_NON_SCHEDULE"
    try:
        dt = datetime.fromisoformat(str(started_at).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            return "UNDETERMINED_TIMESTAMP"
        local = dt.astimezone(TAIPEI)
    except (TypeError, ValueError):
        return "UNDETERMINED_TIMESTAMP"
    return "ON_TIME" if (local.hour, local.minute, local.second) <= (6, 15, 0) else "MISSED_DEADLINE"

def validate_execution_artifacts(root, execution_id):
    root = Path(root).resolve()
    data = read_json(root / "data/latest.json")
    summary = read_json(root / "data/recent-summary.json")
    manifest = read_json(root / "reports/latest-manifest.json")
    audit = read_json(root / "data/notion-writeback-audit.json")
    errors = []
    for name, record in (("data", data), ("summary", summary), ("manifest", manifest), ("audit", audit)):
        if not record:
            errors.append(name + "_missing_or_invalid")
        elif record.get("execution_id") != execution_id:
            errors.append(name + "_execution_id_mismatch")
    data_time = data.get("generated_at")
    summary_time = summary.get("generated_at")
    manifest_data_time = manifest.get("data_generated_at")
    if not data_time:
        errors.append("data_generated_at_missing")
    if summary_time != data_time:
        errors.append("summary_data_timestamp_mismatch")
    if manifest_data_time != data_time:
        errors.append("manifest_data_timestamp_mismatch")
    counts = [data.get("sample_count"), summary.get("sample_count"), manifest.get("sample_count")]
    if not all(isinstance(v, int) and not isinstance(v, bool) and v > 0 for v in counts):
        errors.append("sample_count_missing_or_invalid")
    elif not (counts[0] == counts[1] == counts[2]):
        errors.append("sample_count_mismatch")
    verification = data.get("verification", {})
    if not isinstance(verification, dict):
        verification = {}
        errors.append("data_verification_invalid")
    fresh = verification.get("fresh_videos")
    if verification.get("verified_72h") is not True:
        errors.append("verified_72h_not_true")
    if not isinstance(fresh, int) or isinstance(fresh, bool) or fresh <= 0:
        errors.append("fresh_video_count_invalid")
    if verification.get("stale_or_invalid_videos") != 0:
        errors.append("stale_or_invalid_video_count_not_zero")
    if isinstance(counts[0], int) and isinstance(fresh, int) and counts[0] != fresh:
        errors.append("sample_count_fresh_count_mismatch")
    artifacts = {}
    for key in ("word", "pptx", "chart"):
        raw = manifest.get(key)
        if not isinstance(raw, str) or not raw.strip():
            errors.append("manifest_" + key + "_path_missing")
            continue
        rel = Path(raw)
        if rel.is_absolute():
            errors.append("manifest_" + key + "_path_not_relative")
            continue
        target = (root / rel).resolve()
        try:
            target.relative_to((root / "reports").resolve())
        except ValueError:
            errors.append("manifest_" + key + "_path_outside_reports")
            continue
        if "executions" not in rel.parts or execution_id not in rel.parts:
            errors.append("manifest_" + key + "_path_execution_mismatch")
            continue
        if not target.is_file() or target.stat().st_size <= 0:
            errors.append("manifest_" + key + "_artifact_missing_or_empty")
            continue
        artifacts[key] = raw
    for key in ("data_execution_id", "summary_execution_id", "manifest_execution_id"):
        if audit.get(key) != execution_id:
            errors.append("audit_" + key + "_mismatch")
    if audit.get("status") != "PASS":
        errors.append("notion_audit_not_pass")
    for key in ("writeback_verified", "readback_verified", "content_verified"):
        if audit.get(key) is not True:
            errors.append("notion_" + key + "_not_verified")
    if not audit.get("comment_id") or not audit.get("page_id"):
        errors.append("notion_comment_or_page_id_missing")
    if audit.get("sample_count") != manifest.get("sample_count"):
        errors.append("audit_sample_count_mismatch")
    if audit.get("data_generated_at") != data_time:
        errors.append("audit_data_timestamp_mismatch")
    if audit.get("summary_generated_at") != summary_time:
        errors.append("audit_summary_timestamp_mismatch")
    if audit.get("manifest_data_generated_at") != manifest_data_time:
        errors.append("audit_manifest_data_timestamp_mismatch")
    return {
        "status": "PASS" if not errors else "FAIL", "errors": errors,
        "data_execution_match": data.get("execution_id") == execution_id,
        "summary_execution_match": summary.get("execution_id") == execution_id,
        "manifest_execution_match": manifest.get("execution_id") == execution_id,
        "audit_execution_match": audit.get("execution_id") == execution_id,
        "data_generated_at": data_time if data.get("execution_id") == execution_id else None,
        "summary_generated_at": summary_time if summary.get("execution_id") == execution_id else None,
        "manifest_generated_at": manifest.get("generated_at") if manifest.get("execution_id") == execution_id else None,
        "manifest_data_generated_at": manifest_data_time if manifest.get("execution_id") == execution_id else None,
        "data_sample_count": data.get("sample_count") if data.get("execution_id") == execution_id else None,
        "summary_sample_count": summary.get("sample_count") if summary.get("execution_id") == execution_id else None,
        "manifest_sample_count": manifest.get("sample_count") if manifest.get("execution_id") == execution_id else None,
        "data_verification": verification if data.get("execution_id") == execution_id else {},
        "report_artifacts": artifacts,
    }

def write_execution_state(root, *, execution_id, started_at, github_run_id, github_run_attempt,
                          trigger, recovery_attempt, requested_status, failure_reason="",
                          recovery_action="", mcp_endpoint=""):
    root = Path(root).resolve()
    gate = validate_execution_artifacts(root, execution_id)
    accepted = requested_status == "SUCCESS" and gate["status"] == "PASS"
    status = "SUCCESS" if accepted else "FAILED"
    if requested_status == "SUCCESS" and not accepted:
        reason = "execution evidence gate failed: " + ", ".join(gate["errors"])
    else:
        reason = failure_reason or (None if accepted else "pipeline failed before all success gates passed")
    state = {
        "execution_id": execution_id, "workflow": "Daily YouTube Research via MCP", "status": status,
        "started_at": started_at, "completed_at": datetime.now(ZoneInfo("UTC")).isoformat(),
        "github_run_id": str(github_run_id), "github_run_attempt": str(github_run_attempt),
        "trigger": trigger, "recovery_attempt": bool(recovery_attempt), "mcp_endpoint": mcp_endpoint,
        "data": "PASS" if accepted else "UNKNOWN", "reports": "PASS" if accepted else "UNKNOWN",
        "verification": "PASS" if accepted else "UNKNOWN", "artifact_gate_status": gate["status"],
        "artifact_gate_errors": gate["errors"], "data_execution_match": gate["data_execution_match"],
        "summary_execution_match": gate["summary_execution_match"],
        "manifest_execution_match": gate["manifest_execution_match"], "audit_execution_match": gate["audit_execution_match"],
        "data_generated_at": gate["data_generated_at"], "summary_generated_at": gate["summary_generated_at"],
        "manifest_generated_at": gate["manifest_generated_at"], "manifest_data_generated_at": gate["manifest_data_generated_at"],
        "data_sample_count": gate["data_sample_count"], "summary_sample_count": gate["summary_sample_count"],
        "manifest_sample_count": gate["manifest_sample_count"],
        "data_verification": gate["data_verification"] if accepted else {},
        "report_artifacts": gate["report_artifacts"] if accepted else {},
        "schedule_deadline_status": schedule_deadline_status(trigger, started_at),
        "failure_reason": reason,
        "recovery_action": recovery_action or (None if accepted else "Inspect this execution only; do not reuse prior data as a successful result."),
    }
    atomic_json(root / "data/execution-history" / (execution_id + ".json"), state)
    atomic_json(root / "data/execution-state.json", state)
    if accepted:
        atomic_json(root / "data/last-successful-execution.json", state)
    return state, accepted
