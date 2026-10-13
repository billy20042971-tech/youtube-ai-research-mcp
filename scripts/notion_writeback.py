#!/usr/bin/env python3
"""Write and read back a per-run audit comment in Notion.

Credentials are supplied only through environment variables. Never print the token.
Missing credentials produce an explicit SKIPPED audit record rather than a false PASS.
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
        f"pipeline_status: {state.get('status', 'IN_PROGRESS')}\n"
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
        # Do not print request headers or secrets.
        details = exc.read().decode("utf-8", errors="replace")[:800]
        raise RuntimeError(f"Notion API {method} {path} failed ({exc.code}): {details}") from None


def text_from_comment(comment: dict) -> str:
    return "".join(
        item.get("plain_text", item.get("text", {}).get("content", ""))
        for item in comment.get("rich_text", [])
    )


def write_audit(record: dict) -> None:
    AUDIT_PATH.parent.mkdir(parents=True, exist_ok=True)
    AUDIT_PATH.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(record, ensure_ascii=False))


def main() -> int:
    execution_id = f"gh-{os.environ.get('GITHUB_RUN_ID', 'local')}-attempt-{os.environ.get('GITHUB_RUN_ATTEMPT', '1')}"
    token = os.environ.get("NOTION_API_KEY", "").strip()
    page_id = os.environ.get("NOTION_PAGE_ID", "").strip()
    state_path = Path("data/execution-state.json")
    manifest_path = Path("reports/latest-manifest.json")
    state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {}
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}

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
        return 0

    text = comment_text(execution_id, manifest, state)
    created = request_json("POST", "/comments", token, {
        "parent": {"page_id": page_id},
        "rich_text": [{"type": "text", "text": {"content": text[:1900]}}],
    })
    comment_id = created.get("id")
    if not comment_id:
        raise RuntimeError("Notion comment creation response did not include an id.")

    query = urllib.parse.urlencode({"block_id": page_id, "page_size": "100"})
    listing = request_json("GET", f"/comments?{query}", token)
    found = next(
        (item for item in listing.get("results", [])
         if item.get("id") == comment_id and execution_id in text_from_comment(item)),
        None,
    )
    if found is None:
        # One additional read catches brief API propagation delay without duplicating the write.
        listing = request_json("GET", f"/comments?{query}", token)
        found = next(
            (item for item in listing.get("results", [])
             if item.get("id") == comment_id and execution_id in text_from_comment(item)),
            None,
        )
    if found is None:
        raise RuntimeError(f"Notion comment {comment_id} was created but could not be verified by readback.")

    write_audit({
        "execution_id": execution_id,
        "status": "PASS",
        "checked_at": now_iso(),
        "page_id": page_id,
        "comment_id": comment_id,
        "writeback_verified": True,
        "readback_verified": True,
        "sample_count": manifest.get("sample_count"),
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
