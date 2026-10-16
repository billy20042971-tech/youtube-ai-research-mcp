"""Conservative, evidence-aware daily summary from a small YouTube sample.

This is a deterministic triage aid, not a claim that views prove a market trend.
"""
from collections import Counter, defaultdict
from datetime import datetime, timezone
from zoneinfo import ZoneInfo


TOPIC_RULES = [
    ("AI 副業／賺錢", ("副業", "賺錢", "收入", "變現", "接案", "財富")),
    ("AI Agent／自動化", ("agent", "代理", "自動化", "workflow", "工作流", "mcp")),
    ("AI 工具／模型", ("工具", "模型", "gpt", "claude", "gemini", "llm")),
    ("AI 影片／影音生成", ("影片", "影音", "剪輯", "sora", "veo", "生成影片")),
    ("AI 教學／學習", ("教學", "學習", "課程", "老師", "教育")),
]


def classify_topic(video):
    text = " ".join(str(video.get(k) or "") for k in ("title", "description", "tags")).lower()
    for label, keywords in TOPIC_RULES:
        if any(word.lower() in text for word in keywords):
            return label
    return "其他／尚未分類"


def build_summary(videos, generated_at=None, previous_video_ids=None):
    """Return compact summary facts without overclaiming trend status."""
    previous_video_ids = set(previous_video_ids or [])
    valid = [v for v in videos if isinstance(v, dict) and v.get("video_id")]
    if not valid:
        return {
            "headline": "今日樣本不足，暫不判定趨勢。",
            "sample_count": 0,
            "signals": [],
            "limitations": ["沒有可分析的有效影片樣本。"],
            "deep_dive": None,
        }

    topic_videos = defaultdict(list)
    for video in valid:
        topic_videos[classify_topic(video)].append(video)

    ranked = sorted(
        topic_videos.items(),
        key=lambda item: (
            len({v.get("channel_id") or v.get("channel_title") or v.get("video_id") for v in item[1]}),
            len(item[1]),
            max(_int(v.get("views")) for v in item[1]),
        ),
        reverse=True,
    )
    signals = []
    for topic, group in ranked[:3]:
        channels = {v.get("channel_id") or v.get("channel_title") or v.get("video_id") for v in group}
        ids = {v.get("video_id") for v in group}
        is_new_sample = bool(ids) and ids.issubset(previous_video_ids) is False and not previous_video_ids
        if len(channels) >= 3 and len(group) >= 3:
            evidence = "中低：樣本內多部影片、跨頻道出現；仍需跨日驗證"
            confidence = "中低"
        elif len(group) >= 2 and len(channels) >= 2:
            evidence = "低：至少兩部影片／頻道提及，尚不足以證實趨勢"
            confidence = "低"
        else:
            evidence = "很低：單一或高度集中的樣本訊號"
            confidence = "很低"
        representative = max(group, key=lambda v: _int(v.get("views")))
        signals.append({
            "topic": topic,
            "video_count": len(group),
            "channel_count": len(channels),
            "confidence": confidence,
            "evidence": evidence,
            "classification": "樣本訊號／待跨日確認",
            "representative_title": representative.get("title") or "(無標題)",
            "representative_url": representative.get("url") or "",
            "views": _int(representative.get("views")),
            "published_at": representative.get("published_at") or "未提供",
        })

    top = max(valid, key=lambda v: _int(v.get("views")))
    return {
        "headline": f"本次分析 {len(valid)} 部近 72 小時影片；以下是樣本訊號，不等於已證實的市場趨勢。",
        "sample_count": len(valid),
        "signals": signals,
        "limitations": [
            "資料僅來自固定查詢「AI賺錢／AI副業」的有限樣本，存在查詢偏差。",
            "觀看數代表曝光／注意力，不直接證明需求、效果、收入或工具能力。",
            "未具備足夠歷史快照時，不把話題標記為新趨勢或持續趨勢。",
            "留言可能偏向自我選擇的觀眾，且創作者主張未經獨立驗證。",
        ],
        "deep_dive": {
            "title": top.get("title") or "(無標題)",
            "url": top.get("url") or "",
            "reason": "僅作為高觀看量候選影片；觀看數不代表內容可靠，需人工核對主張與時間戳。",
            "timestamp": None,
        },
    }


def report_date_taipei(value=None):
    """Return the calendar date in Taiwan time for a timezone-aware or UTC timestamp."""
    if value is None:
        value = datetime.now(timezone.utc)
    elif isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            raise ValueError("Invalid report timestamp")
    if not isinstance(value, datetime):
        raise TypeError("Report timestamp must be a datetime, ISO timestamp, or None")
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(ZoneInfo("Asia/Taipei")).date().isoformat()


def _int(value):
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0
