"""Evidence-grounded helpers for the daily Traditional Chinese AI intelligence report.

This module does not call an LLM or paid translation API. It uses supplied
translation fields and conservative heuristics; unknown foreign-language
content is explicitly marked for translation review rather than fabricated.
"""
from __future__ import annotations

import re
from collections import Counter
import math

CATEGORIES = {
    "AI 副業變現": ("副業", "賺錢", "變現", "收入", "kdp", "side hustle", "make money", "business", "monetize", "盈利", "營利", "數位產品", "接案", "pod", "print on demand", "ebay"),
    "職場自動化與省時": ("自動化", "工作流", "效率", "省時", "辦公", "excel", "agent", "workflow", "automation", "productivity", "省人工", "降本", "claude code"),
    "AI 影音／數位人": ("影片", "影音", "視頻", "數位人", "虛擬人", "avatar", "video", "youtube", "tts", "配音", "短影音", "剪輯", "higgsfield"),
    "產業與投資觀點": ("投資", "股市", "台股", "半導體", "晶片", "產業", "營收", "黃仁勳", "台積電", "ai bubble", "stock", "finance", "market"),
}
PROMO_PATTERNS = (
    r"https?://", r"www\\.", r"訂閱.{0,12}(頻道|通知)", r"按讚.{0,12}(分享|訂閱)?",
    r"點擊.{0,12}連結", r"加入.{0,12}(會員|社群|課程|line)", r"折扣碼", r"優惠碼",
    r"私訊", r"聯絡我", r"telegram", r"whatsapp", r"discord\\.gg", r"affiliate",
    r"sponsor", r"amazon\\.(com|co\\.jp)", r"line official", r"官方帳號",
    r"下載.{0,20}(prompt|提示詞)", r"(prompt|提示詞).{0,20}(雲端|drive|下載)",
)
CREATOR_BIO_PATTERNS = (
    r"歡迎來到我的頻道", r"我是.{0,20}(youtuber|創作者|主持人)", r"關於我",
    r"about me", r"welcome to my channel", r"subscribe to my channel",
    r"don't forget to subscribe", r"thanks for watching", r"感謝收看",
)
TITLE_TRANSLATIONS = {
    "the easiest claude ai side hustle everyone is overlooking": "多數人忽略的 Claude AI 簡易副業機會",
    "websites in 2026": "2026 年的網站製作新樣貌",
    "easiest way to make a website": "製作網站最簡單的方法",
    "the time for an ai side hustle is now": "現在正是嘗試 AI 副業的時候",
}
TOOL_GUIDES = {
    "claude code": {
        "label": "Claude Code（AI 程式開發代理工具）",
        "workflow": "在指定專案目錄讀取程式與 Git 狀態，依明確需求修改檔案，再檢查差異並執行測試。",
        "steps": [
            "先確認專案根目錄、目前 Git 分支與未提交變更，避免 AI 改到錯誤專案或覆蓋既有工作。",
            "一次指定一項需求、允許修改的檔案及可驗收條件；要求先提出計畫，再檢視 diff。",
            "執行專案既有測試與 lint，人工檢查安全、相依套件及設定檔變更後才提交。",
        ],
    },
    "higgsfield": {
        "label": "Higgsfield（AI 影片生成工具）",
        "workflow": "以固定腳本、畫面比例與提示詞建立可比較的生成版本，再檢查畫面一致性及商用授權。",
        "steps": [
            "將同一段腳本拆成鏡頭清單，固定角色、場景、畫面比例與輸出長度作為比較基準。",
            "每次只調整一個提示詞變因，保存版本與輸出，逐項比較角色一致性、動作連貫及重製成本。",
            "正式商用前核對當前方案的生成額度、素材權利、商用授權與平台內容規範。",
        ],
    },
    "zazzle": {
        "label": "Zazzle（按需印製／客製化商品平台）",
        "workflow": "選定單一細分商品與受眾，研究站內搜尋詞及競品，再以少量設計測試曝光與轉換。",
        "steps": [
            "先選定一個明確受眾與商品類型，檢查站內搜尋詞、熱門設計及競品價格，不要一開始大量上架。",
            "製作少量原創設計，逐一檢查商品預覽、印刷安全區、商標與著作權風險。",
            "按週記錄曝光、點擊、加入購物車與成交；分辨沒有流量、商品頁轉換差或利潤不足。",
        ],
    },
    "ebay": {
        "label": "eBay（跨境電商平台）",
        "workflow": "以單一商品類別試用 AI 輔助刊登，逐欄人工核對品況、規格、運費與平台政策。",
        "steps": [
            "先選定一個商品類別，整理真實照片、型號、尺寸、品況及瑕疵等可驗證資料。",
            "讓 AI 協助草擬標題與描述後，逐欄核對規格、關鍵字、禁售規範及退貨條件，不可讓 AI 猜商品資訊。",
            "小量刊登並追蹤曝光、點擊、成交率、平台費用、物流與退貨成本，確認淨利再擴大。",
        ],
    },
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
    supplied = video.get("title_zh") or video.get("translated_title") or video.get("chinese_title")
    if supplied:
        return str(supplied).strip()
    key = re.sub(r"[^a-z0-9 ]", "", title.lower()).strip()
    if key in TITLE_TRANSLATIONS:
        return TITLE_TRANSLATIONS[key]
    if re.search(r"[一-鿿]", title):
        return title
    return "中文意譯待確認（原始標題見附註）"

def clean_description(description: str, max_chars: int = 1800) -> str:
    """Remove obvious channel boilerplate, ads and link-dump lines."""
    kept = []
    for raw_line in str(description or "").splitlines():
        line = " ".join(raw_line.split()).strip(" |•-")
        if not line:
            continue
        if any(re.search(pattern, line, re.I) for pattern in PROMO_PATTERNS + CREATOR_BIO_PATTERNS):
            continue
        # Strip standalone URLs and tracking fragments without discarding useful prose.
        line = re.sub(r"https?://\\S+|www\\.\\S+", "", line, flags=re.I).strip(" |,，。")
        if re.search(r"[ぁ-ゟ゠-ヿ]", line):
            continue
        if not re.search(r"[一-鿿]", line):
            continue
        if len(line) >= 8:
            kept.append(line)
    return "\\n".join(kept)[:max_chars].strip()

def useful_comments(video: dict, limit: int = 3) -> list[str]:
    comments = video.get("comments", [])
    if not isinstance(comments, list):
        return []
    kept = []
    for item in comments:
        text = (item.get("translated_text") or item.get("text", "")) if isinstance(item, dict) else str(item)
        text = " ".join(str(text).split()).strip()
        if re.search(r"[ぁ-ゟ゠-ヿ]", text) or not re.search(r"[一-鿿]", text):
            continue
        if len(text) < 12 or any(re.search(pattern, text, re.I) for pattern in PROMO_PATTERNS + CREATOR_BIO_PATTERNS):
            continue
        if text not in kept:
            kept.append(text[:400])
        if len(kept) >= limit:
            break
    return kept

def tool_guidance(video: dict) -> dict:
    text = _text(video)
    for key, guide in TOOL_GUIDES.items():
        if key in text:
            return guide
    return {
        "label": "來源未提供可確認的具體工具",
        "workflow": "影片描述或可取得內容不足，無法可靠還原工具與操作流程。",
        "steps": [
            "先取得影片逐字稿或實際操作畫面，確認工具名稱、版本及輸入／輸出。",
            "核對工具官方文件中的功能、價格、使用限制與商用授權。",
            "補齊來源證據後再制定對應操作步驟；目前不推測影片未提供的做法。",
        ],
    }

def recommendation_reason(video: dict) -> str:
    text = _text(video)
    if any(x in text for x in ("case study", "案例", "營收", "revenue", "sales", "成交", "賣出")):
        return "AI 商業化真實案例（仍須核對數據與成本）"
    if any(x in text for x in ("教程", "tutorial", "step by step", "workflow", "工作流", "claude code", "higgsfield")):
        return "極具實操價值（需依來源確認完整步驟）"
    if any(x in text for x in ("突破", "解決", "破解", "技術", "技術破局", "automation", "agent")):
        return "技術破局點"
    return "值得關注的應用訊號"

def engagement_score(video: dict) -> float:
    views = max(0, int(video.get("views") or 0))
    likes = max(0, int(video.get("likes") or 0))
    comments = max(0, int(video.get("comments_count") or (len(video.get("comments", [])) if isinstance(video.get("comments"), list) else 0)))
    return math.log1p(views) + 2 * math.log1p(likes) + 3 * math.log1p(comments)

def analyze_sample(videos: list[dict]) -> dict:
    buckets = {name: [] for name in (*CATEGORIES.keys(), "其他 AI 應用")}
    for video in videos:
        buckets[classify_video(video)].append(video)
    ordered = sorted(videos, key=engagement_score, reverse=True)
    signals = []
    for name, entries in sorted(buckets.items(), key=lambda pair: len(pair[1]), reverse=True):
        if entries:
            examples = "、".join(chinese_title(v) for v in entries[:2])
            signals.append({
                "name": name, "count": len(entries),
                "summary": f"本日樣本有 {len(entries)} 部影片涉及此主題；代表內容包括：{examples}。這是樣本分布訊號，不等同整體市場規模或已證實趨勢。"
            })
    top = ordered[:10]
    return {"buckets": buckets, "signals": signals[:3], "top": top, "top3": top[:3]}
