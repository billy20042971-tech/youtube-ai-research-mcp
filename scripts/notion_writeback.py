#!/usr/bin/env python3
"""Write and read back a per-run audit comment in Notion.

Credentials are supplied only through environment variables. Never print the token.
Missing credentials produce an explicit SKIPPED audit record and a non-zero exit so production cannot report a false PASS.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

API_BASE = "https://api.notion.com/v1"
API_VERSION = "2022-06-28"
AUDIT_PATH = Path("data/notion-writeback-audit.json")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def comment_text(execution_id: str, manifest: dict, state: dict) -> str:
    verification = state.get("data_verification", {})
    return (
        f"YouTube AI Research pipeline audit\n"
        f"execution_id: {execution_id}\n"
        f"github_run_id: {state.get('github_run_id', '')}\n"
        f"trigger: {state.get('trigger', '')}\n"
        f"pipeline_status_at_writeback: {state.get('status', 'IN_PROGRESS')}\n"
        f"sample_count: {manifest.get('sample_count', 'unknown')}\n"
        f"verified_72h: {verification.get('verified_72h', 'see data/latest.json')}\n"
        f"reports: {manifest.get('word', '')} | {manifest.get('pptx', '')} | {manifest.get('chart', '')}\n"
        f"automated_writeback: execution comment created and read back by GitHub Actions."
    )


def request_json(method: str, path: str, token: str, payload: dict | None = None) -> dict:
    body = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        API_BASE + path,
        data=body,
        method=method,
        headers={
            "Authorization": f"Bearer {token}",
            "Notion-Version": API_VERSION,
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=25) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        # Keep response bodies out of logs; API errors can contain resource metadata.
        raise RuntimeError(
            f"Notion API request failed ({exc.code}); check integration access, page sharing, and permissions."
        ) from None


def text_from_comment(comment: dict) -> str:
    return "".join(
        item.get("plain_text", item.get("text", {}).get("content", ""))
        for item in comment.get("rich_text", [])
    )


def list_comments(page_id: str, token: str) -> list[dict]:
    """Read every comment page so old execution markers are not missed."""
    results: list[dict] = []
    cursor: str | None = None
    seen_cursors: set[str] = set()
    while True:
        params = {"block_id": page_id, "page_size": "100"}
        if cursor:
            params["start_cursor"] = cursor
        query = urllib.parse.urlencode(params)
        listing = request_json("GET", f"/comments?{query}", token)
        page_results = listing.get("results", [])
        if not isinstance(page_results, list):
            raise RuntimeError("Notion comments response has an invalid results field.")
        results.extend(item for item in page_results if isinstance(item, dict))
        if not listing.get("has_more"):
            return results
        next_cursor = listing.get("next_cursor")
        if not isinstance(next_cursor, str) or not next_cursor or next_cursor in seen_cursors:
            raise RuntimeError("Notion comments pagination returned an invalid cursor.")
        seen_cursors.add(next_cursor)
        cursor = next_cursor


def find_existing_comment(page_id: str, token: str, execution_id: str) -> dict | None:
    """Find an existing write for this exact execution before creating another."""
    return next(
        (item for item in list_comments(page_id, token)
         if execution_id in text_from_comment(item) and item.get("id")),
        None,
    )


def ensure_comment(page_id: str, token: str, execution_id: str, text: str) -> str:
    """Reuse a prior execution comment, otherwise create it once."""
    existing = find_existing_comment(page_id, token, execution_id)
    if existing:
        return existing["id"]
    created = request_json("POST", "/comments", token, {
        "parent": {"page_id": page_id},
        "rich_text": [{"type": "text", "text": {"content": text[:1900]}}],
    })
    comment_id = created.get("id")
    if not comment_id:
        raise RuntimeError("Notion comment creation response did not include an id.")
    return comment_id


def verify_comment(page_id: str, token: str, comment_id: str, execution_id: str, expected_text: str) -> bool:
    """Verify the exact comment ID and execution marker, retrying reads only."""
    for attempt in range(2):
        found = next(
            (item for item in list_comments(page_id, token)
             if item.get("id") == comment_id
             and execution_id in text_from_comment(item)
             and text_from_comment(item) == expected_text[:1900]),
            None,
        )
        if found:
            return True
    return False


def write_audit(record: dict) -> None:
    AUDIT_PATH.parent.mkdir(parents=True, exist_ok=True)
    AUDIT_PATH.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(record, ensure_ascii=False))


def main() -> int:
    execution_id = f"gh-{os.environ.get('GITHUB_RUN_ID', 'local')}-attempt-{os.environ.get('GITHUB_RUN_ATTEMPT', '1')}"
    token = os.environ.get("NOTION_API_KEY", "").strip()
    page_id = os.environ.get("NOTION_PAGE_ID", "").strip()
    latest_path = Path("data/latest.json")
    summary_path = Path("data/recent-summary.json")
    manifest_path = Path("reports/latest-manifest.json")
    latest = json.loads(latest_path.read_text(encoding="utf-8")) if latest_path.exists() else {}
    summary = json.loads(summary_path.read_text(encoding="utf-8")) if summary_path.exists() else {}
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
    state = {
        "github_run_id": os.environ.get("GITHUB_RUN_ID", ""),
        "github_run_attempt": os.environ.get("GITHUB_RUN_ATTEMPT", "1"),
        "trigger": os.environ.get("GITHUB_EVENT_NAME", ""),
        "status": "IN_PROGRESS",
        "data_verification": latest.get("verification", {}),
    }

    if not token or not page_id:
        write_audit({
            "execution_id": execution_id,
            "status": "SKIPPED_MISSING_CREDENTIALS",
            "checked_at": now_iso(),
            "page_id_configured": bool(page_id),
            "token_configured": bool(token),
            "writeback_verified": False,
            "note": "Set GitHub Actions secrets NOTION_API_KEY and NOTION_PAGE_ID to enable automatic Notion writeback.",
        })
        return 1

    if (latest.get("execution_id") != execution_id
            or summary.get("execution_id") != execution_id
            or manifest.get("execution_id") != execution_id):
        raise RuntimeError("Data/summary/manifest execution_id does not match this GitHub run; refusing Notion PASS")
    if not (latest.get("generated_at") == summary.get("generated_at") == manifest.get("data_generated_at")):
        raise RuntimeError("Data/summary/manifest generated_at mismatch; refusing Notion PASS")
    if not (latest.get("sample_count") == summary.get("sample_count") == manifest.get("sample_count")):
        raise RuntimeError("Data/summary/manifest sample_count mismatch; refusing Notion PASS")
    verification=latest.get("verification", {})
    if verification.get("verified_72h") is not True or verification.get("fresh_videos", 0) <= 0 or verification.get("stale_or_invalid_videos") != 0:
        raise RuntimeError("72h verification gate is not PASS; refusing Notion PASS")

    text = comment_text(execution_id, manifest, state)
    comment_id = ensure_comment(page_id, token, execution_id, text)
    expected_text=text[:1900]
    if not verify_comment(page_id, token, comment_id, execution_id, expected_text):
        raise RuntimeError(f"Notion comment {comment_id} exists or was created but could not be verified by readback.")

    write_audit({
        "execution_id": execution_id,
        "status": "PASS",
        "checked_at": now_iso(),
        "page_id": page_id,
        "comment_id": comment_id,
        "writeback_verified": True,
        "readback_verified": True,
        "sample_count": manifest.get("sample_count"),
        "data_generated_at": latest.get("generated_at"),
        "summary_generated_at": summary.get("generated_at"),
        "manifest_generated_at": manifest.get("generated_at"),
        "data_execution_id": latest.get("execution_id"),
        "summary_execution_id": summary.get("execution_id"),
        "manifest_execution_id": manifest.get("execution_id"),
        "content_verified": True,
        "github_run_id": state.get("github_run_id", os.environ.get("GITHUB_RUN_ID")),
    })
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        record = {
            "execution_id": f"gh-{os.environ.get('GITHUB_RUN_ID', 'local')}-attempt-{os.environ.get('GITHUB_RUN_ATTEMPT', '1')}",
            "status": "FAILED",
            "checked_at": now_iso(),
            "writeback_verified": False,
            "error": str(exc)[:1000],
        }
        write_audit(record)
        raise SystemExit(1)
