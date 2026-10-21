"""Execution-scoped evidence validation and bounded execution history."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected a JSON object in {path.name}")
    return value


def validate_success_evidence(
    state: dict[str, Any],
    data: dict[str, Any],
    summary: dict[str, Any],
    manifest: dict[str, Any],
    audit: dict[str, Any],
) -> None:
    execution_id = state.get("execution_id")
    if not isinstance(execution_id, str) or not execution_id:
        raise ValueError("Current execution ID is missing")
    if not all(item.get("execution_id") == execution_id for item in (data, summary, manifest, audit)):
        raise ValueError("Data, recent summary, report manifest, and Notion audit execution IDs do not match")
    if summary.get("generated_at") != data.get("generated_at"):
        raise ValueError("Data and recent summary timestamps do not match")
    if state.get("status") != "SUCCESS" or state.get("data") != "PASS" or state.get("reports") != "PASS" or state.get("verification") != "PASS":
        raise ValueError("Execution status gates are not all PASS")
    verification = data.get("verification")
    if not isinstance(verification, dict):
        raise ValueError("Data verification evidence is missing")
    if verification.get("verified_72h") is not True or not isinstance(verification.get("fresh_videos"), int) or verification["fresh_videos"] <= 0 or verification.get("stale_or_invalid_videos") != 0:
        raise ValueError("Freshness Data Gate failed")
    if not isinstance(manifest.get("sample_count"), int) or manifest["sample_count"] <= 0:
        raise ValueError("Report manifest sample_count is missing or invalid")
    if not isinstance(summary.get("sample_count"), int) or summary["sample_count"] <= 0:
        raise ValueError("Recent summary sample_count is missing or invalid")
    if summary["sample_count"] != manifest["sample_count"]:
        raise ValueError("Recent summary and report manifest sample_count do not match")
    try:
        data_time = datetime.fromisoformat(str(data["generated_at"]).replace("Z", "+00:00"))
        manifest_time = datetime.fromisoformat(str(manifest["generated_at"]).replace("Z", "+00:00"))
        if data_time.tzinfo is None or manifest_time.tzinfo is None:
            raise ValueError("timestamps must include timezone information")
        if abs((manifest_time.astimezone(timezone.utc) - data_time.astimezone(timezone.utc)).total_seconds()) > 900:
            raise ValueError("Data and report manifest timestamps differ by more than 15 minutes")
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"Data/manifest timestamp consistency failed: {exc}") from None
    if audit.get("status") != "PASS" or audit.get("writeback_verified") is not True or audit.get("readback_verified") is not True:
        raise ValueError("Notion writeback/readback Audit is not PASS")
    if not audit.get("page_id") or not audit.get("comment_id") or not audit.get("readback_content_sha256"):
        raise ValueError("Notion readback identity/content evidence is incomplete")


def ensure_failure_audit(
    *, root: str | Path, execution_id: str, reason: str, run_id: str
) -> bool:
    """Replace an older run's audit PASS when this run fails before writeback."""
    root = Path(root)
    audit_path = root / "data/notion-writeback-audit.json"
    try:
        current = _read_json(audit_path) if audit_path.exists() else {}
    except (OSError, ValueError, json.JSONDecodeError):
        current = {}
    if current.get("execution_id") == execution_id:
        return False
    record = {
        "execution_id": execution_id,
        "status": "NOT_RUN",
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "github_run_id": run_id,
        "writeback_verified": False,
        "readback_verified": False,
        "error": (reason or "Pipeline failed before Notion writeback was verified.")[:500],
    }
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = audit_path.with_name(audit_path.name + ".tmp")
    temp_path.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp_path.replace(audit_path)
    history_path = root / "data/notion-writeback-audit-history.json"
    try:
        history = _read_json(history_path) if history_path.exists() else {"audits": []}
        records = history.get("audits", [])
        if not isinstance(records, list):
            records = []
    except (OSError, ValueError, json.JSONDecodeError):
        records = []
    records = [item for item in records if not (isinstance(item, dict) and item.get("execution_id") == execution_id)]
    records.append(record)
    history_temp = history_path.with_name(history_path.name + ".tmp")
    history_temp.write_text(json.dumps({"audits": records[-100:]}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    history_temp.replace(history_path)
    return True


def record_execution_state(
    state: dict[str, Any],
    *,
    root: str | Path = ".",
    history_limit: int = 100,
) -> None:
    """Record every run, updating the last-success pointer only after full validation."""
    root = Path(root)
    if history_limit < 1:
        raise ValueError("history_limit must be at least 1")

    if state.get("status") == "SUCCESS":
        data = _read_json(root / "data/latest.json")
        summary = _read_json(root / "data/recent-summary.json")
        manifest = _read_json(root / "reports/latest-manifest.json")
        audit = _read_json(root / "data/notion-writeback-audit.json")
        validate_success_evidence(state, data, summary, manifest, audit)

    (root / "data/execution-state.json").write_text(
        json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    history_path = root / "data/execution-history.json"
    try:
        history = _read_json(history_path) if history_path.exists() else {"executions": []}
        records = history.get("executions", [])
        if not isinstance(records, list):
            records = []
    except (OSError, ValueError, json.JSONDecodeError):
        records = []

    execution_id = state.get("execution_id")
    records = [
        item for item in records
        if not (isinstance(item, dict) and item.get("execution_id") == execution_id)
    ]
    records.append(state)
    history_path.write_text(
        json.dumps({"executions": records[-history_limit:]}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    if state.get("status") == "SUCCESS":
        (root / "data/latest-successful-execution.json").write_text(
            json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
