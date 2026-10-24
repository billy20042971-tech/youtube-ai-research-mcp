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
from datetime import datetime, timezone
from pathlib import Path

API_BASE = "https://api.notion.com/v1"
API_VERSION = "2022-06-28"
AUDIT_PATH = Path("data/notion-writeback-audit.json")
EXPECTED_NOTION_PAGE_ID = "3cc4006515d9806cb196f038cf8c5bc4"


def validate_target_page_id(page_id: str) -> None:
    """Fail closed if the configured secret points outside the approved AI Lab page."""
    normalized = page_id.replace("-", "").strip().lower()
    if normalized != EXPECTED_NOTION_PAGE_ID:
        raise RuntimeError("NOTION_PAGE_ID does not match the approved AI Lab page; no Notion write was attempted.")


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



DIMENSIONS = [
    ("🔥 熱門焦點", ("viral", "trend", "popular", "views", "hot", "熱門", "趨勢", "爆紅")),
    ("🚀 技術突破", ("model", "llm", "benchmark", "release", "sdk", "api", "模型", "發布", "技術", "突破")),
    ("💡 Agent/MCP 落地", ("agent", "mcp", "workflow", "automation", "tool calling", "代理", "自動化", "工作流")),
    ("💬 社群熱議", ("debate", "opinion", "problem", "issue", "cost", "controversy", "爭議", "問題", "成本", "踩坑")),
    ("🛠️ 工具推薦", ("github", "open source", "repo", "tool", "prompt", "工具", "開源", "提示詞")),
]
NOTION_TEXT_LIMIT = 1800


def split_text(text: str, limit: int = NOTION_TEXT_LIMIT) -> list[str]:
    """Split content into safe Notion rich_text chunks, never exceeding 2000 chars."""
    text = str(text or "")
    if not text:
        return [""]
    chunks = []
    while len(text) > limit:
        cut = text.rfind("\n", 0, limit + 1)
        if cut < limit // 2:
            cut = limit
        chunks.append(text[:cut])
        text = text[cut:].lstrip("\n")
    if text:
        chunks.append(text)
    return chunks


def rich_text(content: str, *, bold: bool = False, url: str | None = None) -> list[dict]:
    """Build schema-valid Notion rich_text items with per-item text limits."""
    result = []
    for part in split_text(content):
        item = {
            "type": "text",
            "text": {"content": part},
            "annotations": {"bold": bold},
        }
        if url and len(result) == 0:
            item["text"]["link"] = {"url": url}
        result.append(item)
    return result


def paragraph_block(text: str, *, bold: bool = False, url: str | None = None) -> dict:
    return {"object": "block", "type": "paragraph", "paragraph": {"rich_text": rich_text(text, bold=bold, url=url)}}


def bullet_block(label: str, body: str) -> list[dict]:
    return [paragraph_block(label, bold=True)] + [
        {"object": "block", "type": "bulleted_list_item", "bulleted_list_item": {"rich_text": rich_text(part)}}
        for part in split_text(body) if part
    ]


def classify_video(video: dict) -> str:
    text = " ".join(str(video.get(k, "")) for k in ("title", "description", "tags", "query", "channel_title")).lower()
    for dimension, keywords in DIMENSIONS:
        if any(word in text for word in keywords):
            return dimension
    return "🔥 熱門焦點"


def video_blocks(video: dict, index: int) -> list[dict]:
    """Render a source-grounded mobile briefing card; do not invent missing details."""
    title = str(video.get("title") or "（影片未提供標題）").strip()
    channel = str(video.get("channel_title") or "來源頻道未提供").strip()
    url = str(video.get("url") or "").strip()
    description = str(video.get("description") or "").strip()
    if not description:
        description = "來源未提供影片描述；需開啟原始影片或逐字稿補足事件背景。"
    published = str(video.get("published_at") or "未提供")
    views = video.get("views", "未提供")
    likes = video.get("likes", "未提供")
    comments = video.get("comments", [])
    if not isinstance(comments, list):
        comments = []
    tags = video.get("tags", [])
    if isinstance(tags, list):
        tags_text = "、".join(str(x) for x in tags[:12]) or "未提供"
    else:
        tags_text = str(tags or "未提供")
    comment_texts = []
    for comment in comments[:3]:
        value = comment.get("text", "") if isinstance(comment, dict) else str(comment)
        value = " ".join(str(value).split())
        if value:
            comment_texts.append(value[:500])
    blocks = [{
        "object": "block", "type": "heading_3",
        "heading_3": {"rich_text": rich_text(f"📌 {index}. {title}")},
    }]
    blocks.extend(bullet_block("📌 標題與事件來源", f"頻道／作者：{channel}；發布時間：{published}；觀看數：{views}；喜歡數：{likes}。"))
    blocks.extend(bullet_block("📜 事件背景與來龍去脈（Context）", description))
    blocks.extend(bullet_block("⚙️ 核心機制與技術動態（Technical Breakdown）",
        f"影片標籤／檢索線索：{tags_text}。目前這是依來源中可取得的描述與標籤整理；若來源沒有提供版本、架構或效能數據，不推測或補造。"))
    insight = (
        "實務建議：先依影片提供的原始步驟做小範圍、可回復的測試，記錄成本、品質、耗時與失敗案例，再決定是否納入正式流程。"
        if description and description != "來源未提供影片描述；需開啟原始影片或逐字稿補足事件背景。"
        else "實務建議：先閱讀／觀看原始來源並確認其主張與證據，再評估是否值得試用；目前資料不足，不對效益作結論。"
    )
    blocks.extend(bullet_block("💡 影響評估與落地建議（Actionable Insights）", insight))
    if comment_texts:
        blocks.extend(bullet_block("💬 可取得的社群回饋（非代表性樣本）", "；".join(comment_texts)))
    if url:
        blocks.append(paragraph_block(f"🔗 原始參考連結／影片：{url}", url=url))
    else:
        blocks.append(paragraph_block("🔗 原始參考連結／影片：來源未提供可用網址。"))
    blocks.append({"object": "block", "type": "divider", "divider": {}})
    return blocks


def build_deep_briefing_blocks(latest: dict, manifest: dict, execution_id: str) -> list[dict]:
    """Build phone-friendly Notion blocks from available source evidence."""
    recent = latest.get("recent_72h_sample", {}) if isinstance(latest, dict) else {}
    videos = recent.get("videos", []) if isinstance(recent, dict) else []
    if not isinstance(videos, list):
        videos = []
    videos = [v for v in videos if isinstance(v, dict)]
    date_text = str(manifest.get("generated_at") or now_iso())[:10]
    count = manifest.get("sample_count", len(videos))
    titles = [str(v.get("title", "")).strip() for v in videos[:5] if v.get("title")]
    overview = "；".join(titles) if titles else "本次來源資料未提供可用影片標題，請檢查原始資料。"
    blocks = [{
        "object": "block", "type": "callout",
        "callout": {
            "rich_text": rich_text(f"📱 每日 AI 情報雷達｜{date_text}\n採樣影片：{count} 筆\n當日動態一覽：{overview}\n執行識別：{execution_id}"),
            "icon": {"type": "emoji", "emoji": "🧭"},
        },
    }]
    buckets = {name: [] for name, _ in DIMENSIONS}
    for video in videos:
        buckets[classify_video(video)].append(video)
    index = 0
    for dimension, _keywords in DIMENSIONS:
        blocks.append({"object": "block", "type": "heading_2", "heading_2": {"rich_text": rich_text(dimension)}})
        blocks.append({"object": "block", "type": "divider", "divider": {}})
        entries = buckets[dimension]
        if not entries:
            blocks.append(paragraph_block("本次樣本沒有可可靠歸入此維度的項目；不以推測補足。"))
            continue
        for video in entries:
            index += 1
            blocks.extend(video_blocks(video, index))
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


def block_signature(block: dict) -> tuple[str, str]:
    """Return stable type/text evidence from a Notion block response."""
    block_type = str(block.get("type", ""))
    payload = block.get(block_type, {})
    rich_text = payload.get("rich_text", []) if isinstance(payload, dict) else []
    text = "".join(
        str(item.get("plain_text", item.get("text", {}).get("content", "")))
        for item in rich_text if isinstance(item, dict)
    )
    return block_type, text


def verify_block_sequence(existing: list[dict], expected: list[dict], execution_id: str) -> bool:
    """Verify the complete contiguous block sequence for an execution, not just its marker."""
    marker = f"執行識別：{execution_id}"
    signatures = [block_signature(block) for block in existing]
    expected_signatures = [block_signature(block) for block in expected]
    starts = [i for i, (_, text) in enumerate(signatures) if marker in text]
    if not starts:
        return False
    start = starts[0]
    actual = signatures[start:start + len(expected_signatures)]
    return len(actual) == len(expected_signatures) and actual == expected_signatures


def ensure_deep_briefing(page_id: str, token: str, latest: dict, manifest: dict, execution_id: str) -> tuple[int, bool]:
    """Append one briefing per execution and verify every block by type and exact text."""
    blocks = build_deep_briefing_blocks(latest, manifest, execution_id)
    existing = list_page_blocks(page_id, token)
    marker = f"執行識別：{execution_id}"
    marker_exists = any(marker in block_signature(block)[1] for block in existing)
    if marker_exists:
        if not verify_block_sequence(existing, blocks, execution_id):
            raise RuntimeError(
                "Notion already contains this execution marker but its complete block sequence differs; "
                "refusing duplicate append or false PASS."
            )
        return len(blocks), True

    for offset in range(0, len(blocks), 100):
        request_json("PATCH", f"/blocks/{page_id}/children", token, {"children": blocks[offset:offset + 100]})

    readback = list_page_blocks(page_id, token)
    if not verify_block_sequence(readback, blocks, execution_id):
        raise RuntimeError(
            "Notion deep briefing readback failed: execution marker or full block sequence is missing/mismatched."
        )
    return len(blocks), True

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

    validate_target_page_id(page_id)

    if latest.get("execution_id") != execution_id or manifest.get("execution_id") != execution_id:
        raise RuntimeError("Data and report manifest execution IDs do not match the current GitHub run.")

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
        "page_id": page_id,
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
            "error": str(exc)[:1000],
        }
        write_audit(record)
        raise SystemExit(1)
