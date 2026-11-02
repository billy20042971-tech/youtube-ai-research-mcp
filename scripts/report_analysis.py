"""Source-grounded analysis helpers for the daily AI intelligence report.

No external/paid LLM is called here. Summaries are deliberately evidence-limited:
classification uses metadata keywords; claims about methods are only made when
supported by the supplied title/description. The companion prompt requests
semantic synthesis from an AI reviewer when one is available.
"""
from __future__ import annotations

import re
from collections import Counter

CATEGORIES = {
    "AI 副業變現": ("副業", "賺錢", "變現", "收入", "kdp", "side hustle", "make money", "business", "monetize", "盈利", "營利", "數位產品", "接案"),
    "職場自動化與省時": ("自動化", "工作流", "效率", "省時", "辦公", "excel", "agent", "workflow", "automation", "productivity", "省人工", "降本"),
    "AI 影音／數位人": ("影片", "影音", "視頻", "數位人", "虛擬人", "avatar", "video", "youtube", "tts", "配音", "短影音", "剪輯"),
    "產業與投資觀點": ("投資", "股市", "台股", "半導體", "晶片", "產業", "營收", "黃仁勳", "台積電", "ai bubble", "stock", "finance", "market"),
}
PROMO_PATTERNS = (
    r"https?://", r"www\\.", r"訂閱.{0,8}頻道", r"按讚", r"點擊.{0,8}連結",
    r"加入.{0,8}(會員|社群|課程)", r"折扣碼", r"優惠碼", r"私訊", r"聯絡我",
    r"telegram", r"whatsapp", r"discord\\.gg", r"affiliate", r"sponsor",
)
TITLE_TRANSLATIONS = {
    "the easiest claude ai side hustle everyone is overlooking": "多數人忽略的 Claude AI 簡易副業機會",
    "websites in 2026": "2026 年的網站製作新樣貌",
    "easiest way to make a website": "製作網站最簡單的方法",
    "the time for an ai side hustle is now": "現在正是嘗試 AI 副業的時候",
}

def _text(video: dict) -> str:
    values = []
    for key in ("title", "description", "tags", "query", "channel_title"):
        value = video.get(key, "")
        if isinstance(value, list):
            value = " ".join(map(str, value))
        values.append(str(value or ""))
    return " ".join(values).lower()

def classify_video(video: dict) -> str:
    text = _text(video)
    scores = {name: sum(1 for word in words if word.lower() in text) for name, words in CATEGORIES.items()}
    best = max(scores, key=scores.get)
    return best if scores[best] else "其他 AI 應用"

def chinese_title(video: dict) -> str:
    title = str(video.get("title") or "（來源未提供標題）").strip()
    supplied = video.get("title_zh") or video.get("translated_title")
    if supplied:
        return str(supplied).strip()
    key = re.sub(r"[^a-z0-9 ]", "", title.lower()).strip()
    if key in TITLE_TRANSLATIONS:
        return TITLE_TRANSLATIONS[key]
    if re.search(r"[\\u3400-\\u9fff]", title):
        return title
    # Never fabricate a translation when no translation model/output is present.
    return "中文意譯待確認：" + title

def useful_comments(video: dict, limit: int = 3) -> list[str]:
    comments = video.get("comments", [])
    if not isinstance(comments, list):
        return []
    kept = []
    for item in comments:
        text = item.get("text", "") if isinstance(item, dict) else str(item)
        text = " ".join(str(text).split()).strip()
        if len(text) < 12 or any(re.search(pattern, text, re.I) for pattern in PROMO_PATTERNS):
            continue
        if text not in kept:
            kept.append(text[:400])
        if len(kept) >= limit:
            break
    return kept

def engagement_score(video: dict) -> float:
    views = max(0, int(video.get("views") or 0))
    likes = max(0, int(video.get("likes") or 0))
    comments = max(0, int(video.get("comments_count") or (len(video.get("comments", [])) if isinstance(video.get("comments"), list) else 0)))
    # Log-scaled reach plus interaction signals; not a claim of sentiment.
    import math
    return math.log1p(views) + 2 * math.log1p(likes) + 3 * math.log1p(comments)

def analyze_sample(videos: list[dict]) -> dict:
    buckets = {name: [] for name in (*CATEGORIES.keys(), "其他 AI 應用")}
    for video in videos:
        buckets[classify_video(video)].append(video)
    ordered = sorted(videos, key=engagement_score, reverse=True)
    signals = []
    for name, entries in sorted(buckets.items(), key=lambda pair: len(pair[1]), reverse=True):
        if entries:
            examples = "、".join(str(v.get("title") or "未提供標題") for v in entries[:2])
            signals.append({
                "name": name, "count": len(entries),
                "summary": f"本日樣本有 {len(entries)} 部影片涉及此主題；代表性內容包括：{examples}。這是樣本分布訊號，不等同整體市場規模或已證實趨勢。"
            })
    return {"buckets": buckets, "signals": signals[:3], "top": ordered[:10]}
