#!/usr/bin/env python3
"""Write and read back a per-run audit comment in Notion.

Credentials are supplied only through environment variables. Never print the token.
Missing credentials produce an explicit SKIPPED audit record and a non-zero exit so production cannot report a false PASS.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
import time
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

API_BASE = "https://api.notion.com/v1"
API_VERSION = "2022-06-28"
AUDIT_PATH = Path("data/notion-writeback-audit.json")
EXPECTED_NOTION_DATABASE_ID = "8eeeca644e1f4687a3611f5124a0c5c8"


def validate_target_database_id(database_id: str) -> None:
    """Fail closed unless the configured destination is the approved AI 情報雷達 database."""
    normalized = database_id.replace("-", "").strip().lower()
    if normalized != EXPECTED_NOTION_DATABASE_ID:
        raise RuntimeError(
            "NOTION_DATABASE_ID (or legacy NOTION_PAGE_ID) does not match the approved "
            "AI 情報雷達 database; no Notion write was attempted."
        )


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



try:
    from scripts.report_analysis import CATEGORIES, analyze_sample, chinese_title, useful_comments
except ModuleNotFoundError:  # Direct execution: python scripts/<file>.py
    from report_analysis import CATEGORIES, analyze_sample, chinese_title, useful_comments

NOTION_TEXT_LIMIT = 1800


def split_text(text: str, limit: int = NOTION_TEXT_LIMIT) -> list[str]:
    """Split content into safe Notion rich_text chunks, never exceeding 2000 chars."""
    text = str(text or "")
    if not text:
        return [""]
    chunks = []
    while len(text) > limit:
        cut = text.rfind("\\n", 0, limit + 1)
        if cut < limit // 2:
            cut = limit
        chunks.append(text[:cut])
        text = text[cut:].lstrip("\\n")
    if text:
        chunks.append(text)
    return chunks


def rich_text(content: str, *, bold: bool = False, url: str | None = None) -> list[dict]:
    result = []
    for part in split_text(content):
        item = {"type": "text", "text": {"content": part}, "annotations": {"bold": bold}}
        if url and not result:
            item["text"]["link"] = {"url": url}
        result.append(item)
    return result


def paragraph_block(text: str, *, bold: bool = False, url: str | None = None) -> dict:
    return {"object": "block", "type": "paragraph", "paragraph": {"rich_text": rich_text(text, bold=bold, url=url)}}


def heading_block(level: int, text: str) -> dict:
    key = f"heading_{level}"
    return {"object": "block", "type": key, key: {"rich_text": rich_text(text)}}


def bullet_block(label: str, body: str) -> list[dict]:
    return [paragraph_block(label, bold=True)] + [
        {"object": "block", "type": "bulleted_list_item", "bulleted_list_item": {"rich_text": rich_text(part)}}
        for part in split_text(body) if part
    ]


def video_blocks(video: dict, index: int) -> list[dict]:
    """Render one concise, source-grounded video card for mobile reading."""
    title = str(video.get("title") or "（來源未提供標題）").strip()
    description = str(video.get("description") or "").strip()
    blocks = [heading_block(3, f"{index}. {chinese_title(video)}")]
    blocks.extend(bullet_block("原始標題／頻道", f"{title}｜{video.get('channel_title') or '來源頻道未提供'}"))
    blocks.extend(bullet_block("核心洞察", description[:1400] if description else "來源描述不足，請開啟原始影片或逐字稿確認實際方法；不臆測內容。"))
    blocks.extend(bullet_block("落地建議", "先選一個低風險小任務試做，記錄原本耗時、導入後耗時、品質差異與額外成本，再決定是否擴大。"))
    for comment in useful_comments(video, 3):
        blocks.append(paragraph_block("觀眾回饋：" + comment))
    url = str(video.get("url") or "").strip()
    if url:
        blocks.append(paragraph_block(f"🔗 原始影片：{url}", url=url))
    return blocks


def build_deep_briefing_blocks(latest: dict, manifest: dict, execution_id: str) -> list[dict]:
    """Build the four-section, mobile-friendly Traditional Chinese research report."""
    recent = latest.get("recent_72h_sample", {}) if isinstance(latest, dict) else {}
    videos = recent.get("videos", []) if isinstance(recent, dict) else []
    videos = [v for v in videos if isinstance(v, dict)] if isinstance(videos, list) else []
    analysis = analyze_sample(videos)
    date_text = str(manifest.get("generated_at") or now_iso())[:10]
    count = manifest.get("sample_count", len(videos))
    blocks = [{
        "object": "block", "type": "callout",
        "callout": {"rich_text": rich_text(f"📱 每日 AI 情報雷達｜{date_text}\\n採樣影片：{count} 部\\n本報告聚焦商業應用、職場效率、內容創作與產業觀察。\\n執行識別：{execution_id}"),
                    "icon": {"type": "emoji", "emoji": "🧭"}},
    }]

    blocks.append(heading_block(2, "🚀 今日 3 分鐘核心趨勢摘要"))
    blocks.append(paragraph_block("今日最值得關注的 AI 變化：AI 應用正從工具展示，走向商業成果、內容產製與工作流程改善；以下判讀僅代表本次樣本，不等同整體市場結論。"))
    for idx, signal in enumerate(analysis["signals"], 1):
        blocks.extend(bullet_block(f"訊號 {idx}｜{signal['name']}（{signal['count']} 部）", signal["summary"]))

    blocks.append(heading_block(2, "📊 主題分類洞察"))
    for name, entries in analysis["buckets"].items():
        if not entries:
            continue
        examples = "；".join(str(v.get("title") or "未提供標題") for v in entries[:3])
        summary = (f"本次樣本共 {len(entries)} 部，代表內容：{examples}。"
                   "請區分影片作者主張與可驗證事實；單一案例不能直接推論普遍成效。")
        blocks.extend(bullet_block(f"{name}｜{len(entries)} 部", summary))

    blocks.append(heading_block(2, "💡 精選高價值影片拆解"))
    blocks.append(paragraph_block("依觀看與互動訊號排序，排序僅作為閱讀參考，不代表內容品質或觀眾認同。"))
    for idx, video in enumerate(analysis["top"][:10], 1):
        title = str(video.get("title") or "（來源未提供標題）")
        translated = chinese_title(video)
        channel = str(video.get("channel_title") or "來源頻道未提供")
        url = str(video.get("url") or "").strip()
        description = str(video.get("description") or "").strip()
        insight = description[:1400] if description else "來源描述不足，請開啟原始影片或逐字稿確認實際方法；不臆測內容。"
        blocks.append(heading_block(3, f"{idx}. {translated}"))
        blocks.extend(bullet_block("原始標題／頻道", f"{title}｜{channel}"))
        blocks.extend(bullet_block("核心洞察", insight))
        blocks.extend(bullet_block("落地建議", "選一個低風險、可在 30 分鐘內驗證的小任務試做，記錄原本耗時、導入後耗時、品質差異與額外成本；確認有效再擴大。"))
        if url:
            blocks.append(paragraph_block(f"🔗 原始影片：{url}", url=url))

    blocks.append(heading_block(2, "💬 社群觀眾反應與避坑指南"))
    comment_total = 0
    for video in analysis["top"][:10]:
        comments = useful_comments(video, 3)
        if not comments:
            continue
        comment_total += len(comments)
        blocks.append(heading_block(3, str(video.get("title") or "相關影片")[:120]))
        for comment in comments:
            blocks.append(paragraph_block("觀眾回饋：" + comment))
    blocks.append(paragraph_block(
        f"本節整理 {comment_total} 則經初步過濾的留言。留言為自選樣本，不代表全體觀眾。"
        "避坑提醒：審慎看待獲利／銷量承諾、平台政策變動、隱藏訂閱費、軟體學習門檻，以及無法重現的成功案例。"
    ))
    return blocks


def list_page_blocks(page_id: str, token: str) -> list[dict]:
    """Read all child blocks for an independent post-write verification."""
    results = []
    cursor = None
    seen = set()
    while True:
        params = {"page_size": "100"}
        if cursor:
            params["start_cursor"] = cursor
        listing = request_json("GET", f"/blocks/{page_id}/children?{urllib.parse.urlencode(params)}", token)
        page_results = listing.get("results", [])
        if not isinstance(page_results, list):
            raise RuntimeError("Notion block response has an invalid results field.")
        results.extend(x for x in page_results if isinstance(x, dict))
        if not listing.get("has_more"):
            return results
        next_cursor = listing.get("next_cursor")
        if not isinstance(next_cursor, str) or not next_cursor or next_cursor in seen:
            raise RuntimeError("Notion block pagination returned an invalid cursor.")
        seen.add(next_cursor)
        cursor = next_cursor


def _normalize_block_text(value: str) -> str:
    """Normalize representation-only differences without discarding meaningful content."""
    value = unicodedata.normalize("NFC", value).replace("\r\n", "\n").replace("\r", "\n")
    return value.replace("\u200b", "").replace("\ufeff", "")


def block_signature(block: dict) -> tuple[str, str]:
    """Return stable type/text evidence from Notion block payloads."""
    block_type = str(block.get("type", ""))
    payload = block.get(block_type, {})
    rich_text = payload.get("rich_text", []) if isinstance(payload, dict) else []
    parts = []
    for item in rich_text:
        if not isinstance(item, dict):
            continue
        text_payload = item.get("text", {})
        if not isinstance(text_payload, dict):
            text_payload = {}
        part = item.get("plain_text")
        if not isinstance(part, str):
            part = text_payload.get("content", "")
        if isinstance(part, str):
            parts.append(part)
    return block_type, _normalize_block_text("".join(parts))


def verify_block_sequence(existing: list[dict], expected: list[dict], execution_id: str) -> bool:
    """Verify the complete contiguous block sequence; only representation noise is normalized."""
    marker = _normalize_block_text(f"執行識別：{execution_id}")
    signatures = [block_signature(block) for block in existing]
    expected_signatures = [block_signature(block) for block in expected]
    starts = [i for i, (_, text) in enumerate(signatures) if marker in text]
    for start in starts:
        actual = signatures[start:start + len(expected_signatures)]
        if len(actual) == len(expected_signatures) and actual == expected_signatures:
            return True
    return False


def ensure_deep_briefing(page_id: str, token: str, latest: dict, manifest: dict, execution_id: str) -> tuple[int, bool]:
    """Append one briefing per execution and verify the full sequence with bounded read retries."""
    blocks = build_deep_briefing_blocks(latest, manifest, execution_id)
    marker = f"執行識別：{execution_id}"
    existing = list_page_blocks(page_id, token)
    marker_exists = any(marker in block_signature(block)[1] for block in existing)
    if marker_exists:
        if _readback_block_sequence(page_id, token, blocks, execution_id):
            return len(blocks), True
        raise RuntimeError(
            "Notion already contains this execution marker but its complete block sequence differs; "
            "refusing duplicate append or false PASS."
        )

    for offset in range(0, len(blocks), 100):
        request_json("PATCH", f"/blocks/{page_id}/children", token, {"children": blocks[offset:offset + 100]})

    if not _readback_block_sequence(page_id, token, blocks, execution_id):
        raise RuntimeError(
            "Notion deep briefing readback failed: execution marker or full block sequence is missing/mismatched."
        )
    return len(blocks), True


def _readback_block_sequence(page_id: str, token: str, expected: list[dict], execution_id: str) -> bool:
    """Retry read-only verification for bounded eventual consistency; never bypass validation."""
    delays = (0.5, 1.0, 2.0, 3.0)
    for attempt in range(len(delays) + 1):
        readback = list_page_blocks(page_id, token)
        if verify_block_sequence(readback, expected, execution_id):
            return True
        if attempt < len(delays):
            time.sleep(delays[attempt])
    return False

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
    """Reuse only an exact prior write; fail closed on same-run content conflicts."""
    existing = find_existing_comment(page_id, token, execution_id)
    if existing:
        if text_from_comment(existing) != text:
            raise RuntimeError(
                "An existing Notion comment for this execution_id has different content; "
                "refusing to treat it as verified or create a duplicate."
            )
        return existing["id"]
    created = request_json("POST", "/comments", token, {
        "parent": {"page_id": page_id},
        "rich_text": [
            {"type": "text", "text": {"content": part}}
            for part in split_text(text)
        ],
    })
    comment_id = created.get("id")
    if not comment_id:
        raise RuntimeError("Notion comment creation response did not include an id.")
    returned_text = text_from_comment(created)
    if returned_text and returned_text != text:
        raise RuntimeError("Notion comment creation response content differs from the requested audit text.")
    return comment_id


def verify_comment(page_id: str, token: str, comment_id: str, execution_id: str, expected_text: str | None = None) -> bool:
    """Verify exact comment ID, execution marker, and content with bounded read-only backoff."""
    delays = (1, 2, 4, 8)
    for attempt in range(len(delays) + 1):
        found = next(
            (item for item in list_comments(page_id, token)
             if item.get("id") == comment_id
             and execution_id in text_from_comment(item)
             and (expected_text is None or text_from_comment(item) == expected_text)),
            None,
        )
        if found:
            return True
        if attempt < len(delays):
            time.sleep(delays[attempt])
    return False


def write_audit(record: dict) -> None:
    AUDIT_PATH.parent.mkdir(parents=True, exist_ok=True)
    AUDIT_PATH.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(record, ensure_ascii=False))
    history_path = Path("data/notion-writeback-audit-history.json")
    try:
        history=json.loads(history_path.read_text(encoding="utf-8")) if history_path.exists() else {"audits": []}
        records=history.get("audits", []) if isinstance(history, dict) else []
        if not isinstance(records, list): records=[]
    except Exception:
        records=[]
    execution_id=record.get("execution_id")
    records=[item for item in records if not (isinstance(item, dict) and item.get("execution_id") == execution_id)]
    records.append(record)
    history_path.write_text(json.dumps({"audits": records[-100:]}, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")


def report_date_from_manifest(manifest: dict) -> str:
    """Use the Taipei calendar date for the report title and database date property."""
    generated_at = manifest.get("generated_at")
    if isinstance(generated_at, str) and generated_at.strip():
        value = generated_at.strip().replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(value)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(ZoneInfo("Asia/Taipei")).date().isoformat()
        except ValueError as exc:
            raise RuntimeError("Report manifest generated_at is not a valid ISO-8601 timestamp.") from exc
    return datetime.now(ZoneInfo("Asia/Taipei")).date().isoformat()


def find_daily_page(database_id: str, token: str, title: str, execution_id: str) -> str | None:
    """Find the existing daily database row so retries do not create duplicate report pages."""
    response = request_json("POST", f"/databases/{database_id}/query", token, {
        "filter": {"property": "情報名稱", "title": {"equals": title}},
        "page_size": 100,
    })
    rows = response.get("results", [])
    if not isinstance(rows, list):
        raise RuntimeError("Notion database query returned an invalid results field.")
    valid_pages = [row for row in rows if isinstance(row, dict) and row.get("id")]
    marker = f"執行識別：{execution_id}"
    for row in valid_pages:
        page_id = row["id"]
        if any(marker in block_signature(block)[1] for block in list_page_blocks(page_id, token)):
            return page_id
    return valid_pages[0]["id"] if valid_pages else None


def create_daily_page(database_id: str, token: str, report_date: str) -> str:
    """Create the daily report as a database row using the database's actual schema."""
    title = f"{report_date} | 每日 AI 情報雷達"
    created = request_json("POST", "/pages", token, {
        "parent": {"database_id": database_id},
        "properties": {
            "情報名稱": {"title": [{"type": "text", "text": {"content": title}}]},
            "發現日期": {"date": {"start": report_date}},
            # Notion's API creates a missing select option when a new option name is supplied.
            "類型": {"select": {"name": "YouTube"}},
        },
    })
    page_id = created.get("id")
    if not isinstance(page_id, str) or not page_id:
        raise RuntimeError("Notion database page creation response did not include a page id.")
    return page_id


def main() -> int:
    execution_id = f"gh-{os.environ.get('GITHUB_RUN_ID', 'local')}-attempt-{os.environ.get('GITHUB_RUN_ATTEMPT', '1')}"
    token = os.environ.get("NOTION_API_KEY", "").strip()
    database_id = (
        os.environ.get("NOTION_DATABASE_ID", "").strip()
        or os.environ.get("NOTION_PAGE_ID", "").strip()
    )
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

    if not token or not database_id:
        write_audit({
            "execution_id": execution_id,
            "status": "SKIPPED_MISSING_CREDENTIALS",
            "checked_at": now_iso(),
            "database_id_configured": bool(database_id),
            "token_configured": bool(token),
            "writeback_verified": False,
            "note": "Set NOTION_API_KEY and NOTION_DATABASE_ID (or update legacy NOTION_PAGE_ID to the approved database ID) to enable automatic Notion writeback.",
        })
        return 1

    validate_target_database_id(database_id)

    if latest.get("execution_id") != execution_id or manifest.get("execution_id") != execution_id:
        raise RuntimeError("Data and report manifest execution IDs do not match the current GitHub run.")

    report_date = report_date_from_manifest(manifest)
    page_title = f"{report_date} | 每日 AI 情報雷達"
    page_id = find_daily_page(database_id, token, page_title, execution_id)
    if page_id is None:
        page_id = create_daily_page(database_id, token, report_date)

    block_count, blocks_readback_verified = ensure_deep_briefing(page_id, token, latest, manifest, execution_id)
    text = comment_text(execution_id, manifest, state)
    comment_id = ensure_comment(page_id, token, execution_id, text)
    if not verify_comment(page_id, token, comment_id, execution_id, text):
        raise RuntimeError(f"Notion comment {comment_id} exists or was created but could not be verified by exact readback.")

    write_audit({
        "execution_id": execution_id,
        "status": "PASS",
        "page_block_verification": "PASS_FULL_SEQUENCE_TYPE_AND_TEXT",
        "comment_verification": "PASS_EXACT_ID_EXECUTION_ID_AND_FULL_CONTENT",
        "verification_scope": "GitHub Actions verified the target page via the Notion API; connector-side visibility is not directly callable from this workflow.",
        "checked_at": now_iso(),
        "database_id": database_id,
        "page_id": page_id,
        "report_date": report_date,
        "page_title": page_title,
        "comment_id": comment_id,
        "writeback_verified": True,
        "readback_verified": True,
        "deep_briefing_blocks": block_count,
        "deep_briefing_readback_verified": blocks_readback_verified,
        "readback_content_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
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
            "readback_verified": False,
            "database_id": os.environ.get("NOTION_DATABASE_ID", "").strip() or os.environ.get("NOTION_PAGE_ID", "").strip(),
            "error": str(exc)[:1000],
        }
        write_audit(record)
        raise SystemExit(1)
