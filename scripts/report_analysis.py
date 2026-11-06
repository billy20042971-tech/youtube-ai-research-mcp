"""Evidence-grounded helpers for the daily Taiwan Traditional Chinese AI report."""
from __future__ import annotations

import re
from collections import Counter
import math

try:
    from scripts.content_enrichment import translate_to_traditional_chinese
except ModuleNotFoundError:
    from content_enrichment import translate_to_traditional_chinese

CATEGORIES = {
    "AI 副業變現": ("副業", "賺錢", "變現", "收入", "kdp", "side hustle", "make money", "business", "monetize", "盈利", "營利", "數位產品", "接案", "pod", "print on demand", "ebay"),
    "職場自動化與省時": ("自動化", "工作流", "效率", "省時", "辦公", "excel", "agent", "workflow", "automation", "productivity", "省人工", "降本", "claude code"),
    "AI 影音／數位人": ("影片", "影音", "視頻", "數位人", "虛擬人", "avatar", "video", "youtube", "tts", "配音", "短影音", "剪輯", "higgsfield"),
    "產業與投資觀點": ("投資", "股市", "台股", "半導體", "晶片", "產業", "營收", "黃仁勳", "台積電", "ai bubble", "stock", "finance", "market"),
}
PROMO_PATTERNS = (
    r"https?://", r"www\.", r"訂閱.{0,12}(頻道|通知)", r"按讚.{0,12}(分享|訂閱)?",
    r"點擊.{0,12}連結", r"加入.{0,12}(會員|社群|課程|line)", r"折扣碼", r"優惠碼",
    r"私訊", r"聯絡我", r"telegram", r"whatsapp", r"discord\.gg", r"affiliate",
    r"sponsor", r"amazon\.(com|co\.jp)", r"line official", r"官方帳號",
    r"下載.{0,20}(prompt|提示詞)", r"(prompt|提示詞).{0,20}(雲端|drive|下載)",
    r"(加我|添加|搜尋|加入).{0,12}(微信|微\s*信|line\s*id|line)",
    r"(官方)?line.{0,15}(領取|加入|聯絡|私訊|報名)",
    r"(免費)?(線上)?(課程|講座|研討會|workshop).{0,20}(報名|預約|領取|加入)",
    r"(報名|預約|立即參加).{0,20}(連結|網址|席位|講座|課程)",
    r"(免費領取|免費下載|領取福利|領取贈品|加好友領取)",
    r"(購買|下單|訂購|立即購買).{0,20}(連結|網址|商品|課程)",
    r"(推薦連結|聯盟連結|affiliate link|佣金|返佣)",
    r"(限時優惠|專屬優惠|立即領取|點此報名|點此購買)",
)
PROMO_CONTEXT_PATTERNS = (
    r"(免費|優惠|折扣|報名|領取|下載|購買|下單|訂購|加入|加我|私訊|聯絡)",
    r"(課程|講座|研討會|會員|社群|微信|line|商品|購物|推薦連結|affiliate)",
)

CREATOR_BIO_PATTERNS = (
    r"歡迎來到我的頻道", r"我是.{0,20}(youtuber|創作者|主持人)", r"關於我",
    r"about me", r"welcome to my channel", r"subscribe to my channel",
    r"don't forget to subscribe", r"thanks for watching", r"感謝收看",
)
SIMPLIFIED_MARKERS = set("这们为与发后里时个来对说还会学过没开关问题点实业数体国经产务应变网软认让进远间长头东车马书门电云见听场万无从两边条优价请该种样现将并实务员组织办专术义条开关间应数进还变点时后发过没个来对说会学")
TRADITIONAL_MARKERS = set("這們為與發後裡時個來對說還會學過沒開關問題點實業數體國經產務應變網軟認讓進遠間長頭東車馬書門電雲見聽場萬無從兩邊條優價請該種樣現將並員組織辦專術義")
LEGACY_GENERIC_ADVICE = ("選一個低風險、可在 30 分鐘內驗證", "記錄原本耗時、導入後耗時、品質差異與額外成本")

def classify_language(text: str) -> str:
    """Conservative script/language gate; mixed/ambiguous text is never accepted."""
    value = str(text or "").strip()
    if not value:
        return "unknown"
    if re.search(r"[ぁ-ゟ゠-ヿ]", value):
        return "japanese"
    han = re.findall(r"[\u3400-\u9fff]", value)
    if not han:
        return "english" if re.search(r"[A-Za-z]", value) else "unknown"
    if any(char in SIMPLIFIED_MARKERS for char in han):
        return "simplified_chinese"
    latin = len(re.findall(r"[A-Za-z]", value))
    meaningful = len(re.sub(r"[\s\W_0-9]", "", value, flags=re.UNICODE))
    if latin and latin / max(1, meaningful) > 0.18:
        return "mixed"
    if any(char in TRADITIONAL_MARKERS for char in han):
        return "traditional_chinese"
    return "unknown"

def is_traditional_chinese(text: str) -> bool:
    return classify_language(text) == "traditional_chinese"

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
    if is_traditional_chinese(title):
        return title
    translated = translate_to_traditional_chinese(title)
    return translated or re.sub(r"\s+", " ", title).strip()

def _normalize_description(text: str) -> str:
    value = str(text or "")
    value = re.sub(r"<br\s*/?>", "\n", value, flags=re.I)
    value = re.sub(r"</?(?:p|div|li|h[1-6])\b[^>]*>", "\n", value, flags=re.I)
    value = re.sub(r"<[^>]+>", " ", value)
    value = value.replace("\\n", "\n")
    return value

def _is_promotional_line(line: str) -> bool:
    if any(re.search(pattern, line, re.I) for pattern in PROMO_PATTERNS + CREATOR_BIO_PATTERNS):
        return True
    has_context = any(re.search(pattern, line, re.I) for pattern in PROMO_CONTEXT_PATTERNS)
    has_action = bool(re.search(r"(點擊|點此|報名|預約|領取|下載|購買|下單|訂購|加入|加我|私訊|掃碼|立即)", line, re.I))
    has_link = bool(re.search(r"https?://|www\.|短網址|連結如下|網址如下", line, re.I))
    return has_context and (has_action or has_link)

def clean_description(description: str, max_chars: int = 1800) -> str:
    """Normalize HTML and remove ads; only confirmed Traditional Chinese survives."""
    kept = []
    for raw_line in _normalize_description(description).splitlines():
        line = " ".join(raw_line.split()).strip(" |•-")
        if not line or _is_promotional_line(line):
            continue
        line = re.sub(r"https?://\S+|www\.\S+", "", line, flags=re.I).strip(" |,，。")
        if classify_language(line) != "traditional_chinese":
            translated = translate_to_traditional_chinese(line)
            if translated:
                line = translated
        if classify_language(line) == "traditional_chinese" and len(line) >= 8:
            kept.append(line)
    return "\n".join(dict.fromkeys(kept))[:max_chars].strip()

def useful_comments(video: dict, limit: int = 3) -> list[str]:
    comments = video.get("comments", [])
    if not isinstance(comments, list):
        return []
    kept = []
    for item in comments:
        text = (item.get("translated_text") or item.get("text", "")) if isinstance(item, dict) else str(item)
        text = " ".join(str(text).split()).strip()
        if not is_traditional_chinese(text):
            continue
        if len(text) < 12 or any(re.search(pattern, text, re.I) for pattern in PROMO_PATTERNS + CREATOR_BIO_PATTERNS):
            continue
        if text not in kept:
            kept.append(text[:400])
        if len(kept) >= limit:
            break
    return kept

GENERIC_TOOL_GUIDES = {
    "chatgpt": ("ChatGPT", "對話式 AI 助理", "將需求拆成背景、目標、限制與輸出格式，先要求草稿，再以來源與事實逐項校對。"),
    "midjourney": ("Midjourney", "AI 圖像生成平台", "先固定主體、場景、構圖與比例，再逐次調整風格參數並保存可重現提示詞。"),
    "notebooklm": ("NotebookLM", "來源導向 AI 研究助理", "匯入可信文件或網址，針對來源提問，並回查引用段落後整理摘要。"),
    "kimi": ("Kimi", "長文本 AI 助理", "提供文件或長文本，指定摘要架構與待回答問題，再抽查原文段落確認結論。"),
    "cursor": ("Cursor", "AI 程式碼編輯器", "先限定工作目錄與檔案範圍，要求提出修改計畫，檢查 diff 並執行測試。"),
    "claude": ("Claude", "生成式 AI 助理", "提供任務背景、限制及評估標準，要求列出依據與不確定處，再人工核對。"),
    "gemini": ("Gemini", "Google 生成式 AI 助理", "以明確任務與來源材料進行分析，要求列出引用依據並核對關鍵事實。"),
    "perplexity": ("Perplexity", "AI 搜尋與研究平台", "將問題拆成可查證子題，檢查引用來源日期、原始文件與不同來源是否一致。"),
    "runway": ("Runway", "AI 影音生成平台", "先定義鏡頭、時長與畫面比例，小批次生成並比較一致性、可控性及素材權利。"),
    "suno": ("Suno", "AI 音樂生成平台", "先描述曲風、情緒、段落與人聲需求，生成多個版本並核對授權條款。"),
    "lovable": ("Lovable", "AI 網頁與應用程式建置平台", "先寫清楚使用者流程與資料欄位，逐頁生成原型，再測試表單、權限與資料保存。"),
}


def tool_guidance(video: dict) -> dict:
    text = _text(video)
    for key, guide in TOOL_GUIDES.items():
        if key in text:
            return guide
    for key, (name, kind, workflow) in GENERIC_TOOL_GUIDES.items():
        if re.search(rf"(?<![a-z0-9]){re.escape(key)}(?![a-z0-9])", text, re.I):
            return {
                "label": f"{name}（{kind}）",
                "workflow": workflow,
                "steps": [
                    f"先確認影片實際使用的 {name} 功能、方案與輸入資料，避免把推測當成示範。",
                    "依影片案例建立小型可重現測試，保存提示詞、設定、輸入與輸出。",
                    "檢查結果品質、時間成本、資料隱私及當前授權條款，再決定是否導入。",
                ],
            }
    return {
        "label": "通用 AI 工具辨識與驗證流程",
        "workflow": "先從標題、描述、章節與逐字稿辨識工具線索，再依影片任務選擇可驗證的 AI 工作流程。",
        "steps": [
            "從影片內容整理工具名稱、任務、輸入資料與產出；沒有明確名稱時，將工具標示為尚未識別，不虛構品牌。",
            "選擇可取得的同類工具，以相同輸入建立小型測試，記錄輸出品質、耗時與限制。",
            "核對官方功能、費用、資料使用政策與商用授權，再將有效步驟寫成 SOP。",
        ],
    }


def actionable_guidance(video: dict) -> dict:
    """Return practical steps; distinguish identified tools from generic validation."""
    guide = dict(tool_guidance(video))
    combined = " ".join([str(guide.get("workflow", "")), *map(str, guide.get("steps", []))])
    if any(phrase in combined for phrase in LEGACY_GENERIC_ADVICE) or "30 分鐘" in combined:
        raise ValueError("Legacy generic advice is prohibited")
    return guide

def core_insights(video: dict, limit: int = 3) -> list[str]:
    """Build concise insights from translated description, transcript, and chapter evidence."""
    candidates = []
    for key in ("description_zh", "translated_description", "transcript_zh", "transcript"):
        value = str(video.get(key) or "").strip()
        if value:
            candidates.extend(re.split(r"(?<=[。！？.!?])\s+|[\r\n]+", value))
    chapters = video.get("chapters") or []
    if isinstance(chapters, list):
        candidates.extend(str(item).strip() for item in chapters if str(item).strip())
    cleaned = []
    for item in candidates:
        line = " ".join(item.split()).strip(" -•")
        if len(line) < 12 or _is_promotional_line(line):
            continue
        if classify_language(line) != "traditional_chinese":
            line = translate_to_traditional_chinese(line)
        if line and classify_language(line) == "traditional_chinese" and line not in cleaned:
            cleaned.append(line[:260])
        if len(cleaned) >= limit:
            break
    if cleaned:
        return cleaned
    title = chinese_title(video)
    category = classify_video(video)
    tool = next((name for name in GENERIC_TOOL_GUIDES if name in _text(video)), "")
    focus = f"內容線索指向 {tool.title()} 的應用" if tool else f"內容主題歸類為「{category}」"
    return [
        f"本片標題為「{title}」，{focus}；此處先作為研究線索，不將標題推論當成影片已證實的成果。",
        "建議先核對影片中的實際操作、輸入資料與輸出結果，再判斷是否適合複製到工作流程。",
    ]


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
