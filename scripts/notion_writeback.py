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


def comment_text(execution_id: str, manifest: dict, state: dict, latest: dict) -> str:
    """Build a compact daily research message, not just a technical audit."""
    verification = state.get("data_verification", {})
    recent = latest.get("recent_72h_sample", {})
    videos_by_id = {}
    for query, bucket in recent.get("per_query", {}).items():
        for video in bucket.get("videos", []):
            if isinstance(video, dict) and video.get("video_id"):
                item = dict(video)
                item.setdefault("query", query)
                videos_by_id[item["video_id"]] = item
    enriched = {
        v.get("video_id"): v
        for v in recent.get("videos", [])
        if isinstance(v, dict) and v.get("video_id")
    }
    videos = []
    for item in videos_by_id.values():
        full = dict(item)
        full.update({k: v for k, v in enriched.get(item["video_id"], {}).items() if v is not None})
        videos.append(full)
    videos.sort(key=lambda v: int(v.get("views") or 0), reverse=True)

    generated = latest.get("generated_at") or manifest.get("generated_at") or "時間未提供"
    report_date = generated[:10]
    lines = [
        f"📡 每日 AI 趨勢雷達｜{report_date}",
        f"狀態：資料驗證 {'通過' if verification.get('verified_72h') is True else '待確認'}｜近72小時影片 {len(videos)} 筆",
        "",
        "【今日高訊號影片｜依觀看數排序】",
    ]
    for index, video in enumerate(videos[:5], 1):
        title = str(video.get("title") or "（無標題）").replace("\\n", " ").strip()
        channel = str(video.get("channel_title") or "未知頻道")
        views = int(video.get("views") or 0)
        url = str(video.get("url") or "")
        lines.append(f"{index}. {title[:100]}｜{channel}｜{views:,} 次觀看")
        if url:
            lines.append(url)
    lines.extend([
        "",
        "【本日判讀】觀看量僅作為初步訊號，需搭配發布時間、跨頻道重複出現、留言證據及 72 小時新鮮度判斷；不可只憑單一熱門影片宣稱趨勢。",
        f"樣本數：{manifest.get('sample_count', len(videos))}｜execution_id：{execution_id}",
        f"GitHub Run：{state.get('github_run_id', '')}｜觸發：{state.get('trigger', '')}",
        "【完整產物】",
        f"Word：{manifest.get('word', '')}",
        f"簡報：{manifest.get('pptx', '')}",
        f"圖表：{manifest.get('chart', '')}",
        "自動化驗收：本留言為每日摘要；寫回後須由 Notion API 讀回確認。",
    ])
    return "\n".join(lines)[:1900]

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


def write_audit(record: dict) -> None:
    AUDIT_PATH.parent.mkdir(parents=True, exist_ok=True)
    AUDIT_PATH.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(record, ensure_ascii=False))


def main() -> int:
    execution_id = f"gh-{os.environ.get('GITHUB_RUN_ID', 'local')}-attempt-{os.environ.get('GITHUB_RUN_ATTEMPT', '1')}"
    token = os.environ.get("NOTION_API_KEY", "").strip()
    page_id = os.environ.get("NOTION_PAGE_ID", "").strip()
    latest_path = Path("data/latest.json")
    manifest_path = Path("reports/latest-manifest.json")
    latest = json.loads(latest_path.read_text(encoding="utf-8")) if latest_path.exists() else {}
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

    text = comment_text(execution_id, manifest, state, latest)
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
