#!/usr/bin/env python3
"""Verify Notion database write/read permissions using an isolated, archived test row.

The database ID is the only destination setting. Notion comments require a page parent,
so this script creates a uniquely named temporary row under the database, verifies the
row by GET, writes a comment to that row, reads the exact comment back, then archives
the temporary row in a finally block. No production intelligence page is modified.
"""
from __future__ import annotations

import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

API_BASE = "https://api.notion.com/v1"
API_VERSION = "2022-06-28"


def request(method: str, path: str, token: str, payload: dict | None = None) -> dict:
    body = None if payload is None else json.dumps(payload).encode("utf-8")
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
        with urllib.request.urlopen(req, timeout=20) as response:
            raw = response.read()
            return json.loads(raw.decode("utf-8")) if raw else {}
    except urllib.error.HTTPError as exc:
        raise RuntimeError(
            f"Notion API request failed with HTTP {exc.code} for {method} {path.split('?')[0]}."
        ) from None


def rich_text_content(items: list[dict]) -> str:
    return "".join(
        item.get("plain_text", item.get("text", {}).get("content", ""))
        for item in items
    )


def main() -> int:
    token = os.environ.get("NOTION_API_KEY", "").strip()
    database_id = os.environ.get("NOTION_DATABASE_ID", "").strip()
    if not token or not database_id:
        raise RuntimeError("NOTION_API_KEY and NOTION_DATABASE_ID are required.")
    if not token.isascii() or any(ch.isspace() for ch in token):
        raise RuntimeError("NOTION_API_KEY must be a raw ASCII token without whitespace.")
    normalized_database_id = database_id.replace("-", "").lower()
    if not re.fullmatch(r"[0-9a-f]{32}", normalized_database_id):
        raise RuntimeError("NOTION_DATABASE_ID must be a valid Notion database UUID.")

    execution_id = (
        f"notion-preflight-gh-{os.environ.get('GH_RUN_ID', 'local')}"
        f"-attempt-{os.environ.get('GH_RUN_ATTEMPT', '1')}"
    )
    marker = (
        "GitHub Actions Notion database credentials preflight.\n"
        f"execution_id: {execution_id}\n"
        f"checked_at_utc: {datetime.now(timezone.utc).isoformat()}\n"
        "purpose: verify database page creation, page retrieval, comment write, and exact comment readback."
    )
    page_id = None
    cleanup_ok = False
    try:
        created = request("POST", "/pages", token, {
            "parent": {"database_id": database_id},
            "properties": {
                "情報名稱": {
                    "title": [{"type": "text", "text": {"content": f"__PREFLIGHT__ {execution_id}"}}]
                }
            },
        })
        page_id = created.get("id")
        if not isinstance(page_id, str) or not page_id:
            raise RuntimeError("Notion database page creation response did not include a page ID.")

        page = request("GET", f"/pages/{urllib.parse.quote(page_id, safe='')}", token)
        parent = page.get("parent", {})
        returned_database_id = str(parent.get("database_id", "")).replace("-", "").lower()
        if returned_database_id != normalized_database_id:
            raise RuntimeError("Created preflight page did not resolve to the configured database on readback.")

        created_comment = request("POST", "/comments", token, {
            "parent": {"page_id": page_id},
            "rich_text": [{"type": "text", "text": {"content": marker[:1900]}}],
        })
        comment_id = created_comment.get("id")
        if not isinstance(comment_id, str) or not comment_id:
            raise RuntimeError("Notion API did not return a preflight comment ID.")

        query = urllib.parse.urlencode({"block_id": page_id, "page_size": "100"})
        listing = request("GET", f"/comments?{query}", token)
        found = next((
            item for item in listing.get("results", [])
            if item.get("id") == comment_id
            and execution_id in rich_text_content(item.get("rich_text", []))
        ), None)
        if found is None:
            listing = request("GET", f"/comments?{query}", token)
            found = next((
                item for item in listing.get("results", [])
                if item.get("id") == comment_id
                and execution_id in rich_text_content(item.get("rich_text", []))
            ), None)
        if found is None:
            raise RuntimeError("Preflight comment write returned but exact comment readback failed.")
    finally:
        if page_id:
            try:
                request("PATCH", f"/pages/{urllib.parse.quote(page_id, safe='')}", token, {"archived": True})
                cleanup_ok = True
            except Exception as exc:
                print(f"::error::Preflight temporary page cleanup failed: {exc}", file=sys.stderr)
        if page_id and not cleanup_ok:
            raise RuntimeError("Preflight temporary database row could not be archived; manual cleanup is required.")

    print(json.dumps({
        "status": "PASS",
        "execution_id": execution_id,
        "database_page_created_and_read": True,
        "comment_id": comment_id,
        "comment_write_verified": True,
        "comment_readback_verified": True,
        "temporary_page_archived": True,
    }))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"::error::{exc}", file=sys.stderr)
        raise SystemExit(1)
