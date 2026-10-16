"""Conservative evidence metadata for the daily YouTube research summary."""
from datetime import datetime, timezone


WORK_MAP = (
    ("教學／實習工場", ("教學", "老師", "教育", "實習", "工場", "課程")),
    ("採購／材料管理", ("採購", "材料", "庫存", "供應鏈", "成本")),
    ("Notion／AI 自動化", ("notion", "agent", "mcp", "自動化", "workflow", "工作流")),
    ("行政／知識工作", ("行政", "文件", "報告", "知識管理")),
)


def _parse_date(value):
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


def evidence_metadata(videos, generated_at=None):
    """Annotate sample freshness, source concentration, and explicit work relevance.

    This is a deterministic screening aid. Channel count is not proof of source
    independence; the output deliberately labels independence as unverified.
    """
    generated = _parse_date(generated_at)
    valid = [v for v in videos if isinstance(v, dict) and v.get("video_id")]
    deduped = {}
    for video in valid:
        deduped.setdefault(str(video["video_id"]), video)
    rows = list(deduped.values())
    prepared = []
    for video in rows:
        published = _parse_date(video.get("published_at"))
        if generated is None or published is None:
            freshness = "不可判定"
        else:
            age_hours = (generated - published).total_seconds() / 3600
            freshness = "未來時間異常" if age_hours < 0 else ("72h 內" if age_hours <= 72 else "超過 72h")
        channel = str(video.get("channel_id") or video.get("channel_title") or "").strip()
        text = " ".join(str(video.get(k) or "") for k in ("title", "description", "tags")).lower()
        relevance = [label for label, keywords in WORK_MAP if any(k.lower() in text for k in keywords)]
        prepared.append({
            "video_id": str(video["video_id"]),
            "title": str(video.get("title") or "(無標題)"),
            "url": str(video.get("url") or ""),
            "channel": channel or "頻道未提供",
            "published_at": video.get("published_at") or "未提供",
            "freshness": freshness,
            "source_independence": "未驗證（頻道不同不代表來源獨立）",
            "work_relevance": relevance or ["未發現明確工作關聯"],
            "action": "安排小型實驗" if relevance else "持續觀察／暫不處理",
        })
    channels = {v["channel"] for v in prepared if v["channel"] != "頻道未提供"}
    stale = sum(v["freshness"] == "超過 72h" for v in prepared)
    unknown_freshness = sum(v["freshness"] == "不可判定" for v in prepared)
    return {
        "sample_count": len(prepared),
        "duplicate_count": len(valid) - len(rows),
        "channel_count": len(channels),
        "stale_count": stale,
        "freshness_unknown_count": unknown_freshness,
        "trend_status": "資料不足，不判定已證實趨勢",
        "signals": prepared[:3],
        "limitations": [
            "頻道數不等於獨立來源數；引用關係及共同來源尚未驗證。",
            "觀看量只代表曝光訊號，不能單獨證明需求、效果或趨勢。",
            "工作關聯依標題／描述關鍵字初篩，需人工確認；未命中不代表完全無關。",
        ],
    }
