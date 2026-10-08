import json
from pathlib import Path
from datetime import datetime, timezone
from collections import Counter
import re

def safe_int(v):
    try:
        return int(v or 0)
    except Exception:
        return 0

def slug(s):
    return re.sub(r"[^0-9A-Za-z_\-一-龥]+", "_", s)[:80].strip("_") or "report"

src = json.loads(Path("data/latest.json").read_text(encoding="utf-8"))
recent = src.get("recent_72h_sample", {})

# MCP returns a compact per_query list where "comments" is a numeric count,
# plus an enriched top-level "videos" list where "comments" is the actual list.
# Always enrich per-query records from the top-level list before reporting.
enriched_by_id = {
    v.get("video_id"): v
    for v in recent.get("videos", [])
    if v.get("video_id")
}

videos = []
for q, d in recent.get("per_query", {}).items():
    for raw in d.get("videos", []):
        x = dict(raw)
        x["query"] = q
        enriched = enriched_by_id.get(x.get("video_id"))
        if enriched:
            for key in (
                "title", "channel_id", "channel_title", "published_at", "description",
                "tags", "views", "likes", "comments", "url", "comments_obtained_count",
                "comments_requested", "comments_unavailable"
            ):
                if key in enriched:
                    x[key] = enriched[key]
        comments = x.get("comments")
        if not isinstance(comments, list):
            x["comments_count"] = safe_int(comments)
            x["comments"] = []
        else:
            x["comments_count"] = len(comments)
        videos.append(x)

seen = {}
for v in videos:
    seen[v.get("video_id")] = v
videos = list(seen.values())
videos.sort(key=lambda x: safe_int(x.get("views")), reverse=True)

now = datetime.now(timezone.utc)
date = now.strftime("%Y-%m-%d")
out = Path("reports") / date
out.mkdir(parents=True, exist_ok=True)

# Visuals
try:
    import matplotlib.pyplot as plt
    top = videos[:10]
    labels = [str(v.get("title", ""))[:22] for v in top][::-1]
    values = [safe_int(v.get("views")) for v in top][::-1]
    fig, ax = plt.subplots(figsize=(10, 6))
    ax.barh(labels, values)
    ax.set_title("YouTube AI Research Radar — Top 10 by Views")
    ax.set_xlabel("Views")
    fig.tight_layout()
    fig.savefig(out / "top10_views.png", dpi=160)
    plt.close(fig)
except Exception as e:
    (out / "chart_error.txt").write_text(str(e), encoding="utf-8")

channels = Counter(v.get("channel_title", "") for v in videos if v.get("channel_title"))
queries = Counter(v.get("query", "") for v in videos if v.get("query"))

# Word
from docx import Document
from docx.shared import Inches

doc = Document()
doc.add_heading(f"YouTube AI趨勢研究雷達｜{date}", 0)
doc.add_paragraph(
    f"自動產出時間：{now.isoformat()} | 資料來源：YouTube Research MCP | "
    f"近72h去重樣本：{len(videos)}"
)
doc.add_heading("1. 一分鐘摘要", level=1)
doc.add_paragraph(
    "本報告由每日 MCP 固定採樣自動產生。排名主要反映觀看量，正式趨勢判定仍需結合發布時間、"
    "跨頻道、留言、持續性與交叉驗證。"
)
doc.add_heading("2. 今日高訊號影片", level=1)
for i, v in enumerate(videos[:10], 1):
    doc.add_paragraph(
        f"{i}. {v.get('title')}｜{v.get('channel_title')}｜"
        f"{safe_int(v.get('views')):,} views｜{v.get('published_at')}\n{v.get('url', '')}"
    )

if (out / "top10_views.png").exists():
    doc.add_picture(str(out / "top10_views.png"), width=Inches(6.4))

doc.add_heading("3. 留言與證據", level=1)
for v in videos[:8]:
    comments = v.get("comments")
    if not isinstance(comments, list):
        comments = []
    obtained = v.get("comments_obtained_count")
    if obtained is None:
        obtained = len(comments)
    doc.add_paragraph(
        f"{v.get('title')}｜實際取得留言 {safe_int(obtained)} 則"
    )
    for c in comments[:3]:
        if isinstance(c, dict):
            txt = str(c.get("text", "")).replace("\n", " ")
        else:
            txt = str(c).replace("\n", " ")
        if txt:
            doc.add_paragraph("・" + txt[:220])

doc.add_heading("4. AI OS 整合研究框架", level=1)
for s in [
    "Agent：負責規劃、工具選擇、執行與停止條件；複雜任務採可恢復的多步驟 loop。",
    "MCP：作為工具／資料連接層；工具輸入輸出採結構化資料，外部不可信文字不得直接驅動高風險寫入。",
    "Verification：工具結果、輸入、輸出、寫回前後都設檢查點；必要時以第二次讀取驗證。",
    "State：保存 task_id、step、input_hash、tool_result、checkpoint、last_success、next_step，讓 Context reset 不等於任務遺失。",
    "Recovery：失敗從最近成功 checkpoint 繼續；可重試步驟與不可重試副作用分離，避免重複寫入。",
    "Automation：排程層只負責叫醒流程；Agent 負責決策與執行；Notion 保存正式狀態與 Audit；GitHub 保存程式與產物。",
    "本數位大腦優先採：Notion=State/Memory，MCP=Tool Bus，Agent=Orchestrator，GitHub Actions=Scheduler/Worker，Verification=Gate，Audit=Evidence。"
]:
    doc.add_paragraph("• " + s)

doc.add_heading("5. 今日自動化檢查", level=1)
doc.add_paragraph(
    "固定採樣 → 原始資料保存 → 去重 → 報告產出 → 產物驗證 → 後續 AI 分析／Notion 寫回。"
    "任何資料過期、MCP 失敗或產物缺失，應停止宣稱完成。"
)
doc.add_heading("6. 下一步", level=1)
doc.add_paragraph(
    "持續觀察跨頻道訊號；優先把可驗證的 Agent/MCP/State/Recovery/Verification/Automation "
    "pattern 轉成可重複工作流程，而不是追逐單一熱門工具。"
)
doc.save(out / f"YouTube_AI趨勢研究雷達_{date}_完整報告.docx")

# PowerPoint
from pptx import Presentation
from pptx.util import Inches as PInches

prs = Presentation()
slides = [
    ("YouTube AI趨勢研究雷達", f"{date}｜MCP 自動採樣"),
    ("一分鐘摘要", f"近72h去重樣本：{len(videos)}\n固定查詢：" + ", ".join(queries.keys())),
    ("高訊號影片", "\n".join(
        f"{i}. {v.get('title', '')[:55]}｜{safe_int(v.get('views')):,}"
        for i, v in enumerate(videos[:7], 1)
    )),
    ("Agent × MCP", "Agent：規劃與執行\nMCP：工具／資料連接\n結構化輸入輸出，隔離不可信文字"),
    ("Verification × State", "Verification：每個副作用前後設 Gate\nState：保存 checkpoint / next_step / evidence\nContext reset 不等於任務遺失"),
    ("Recovery × Automation", "Recovery：從最近成功 checkpoint 繼續\nAutomation：排程叫醒；Agent 執行；Notion 保存狀態；GitHub 保存產物"),
    ("今日結論", "目標不是每天抓更多資料，而是每天讓 AI OS 少一個人工步驟。")
]
for title, body in slides:
    s = prs.slides.add_slide(prs.slide_layouts[1])
    s.shapes.title.text = title
    s.placeholders[1].text = body

if (out / "top10_views.png").exists():
    s = prs.slides.add_slide(prs.slide_layouts[5])
    s.shapes.add_picture(
        str(out / "top10_views.png"), PInches(0.6), PInches(1.1), width=PInches(8.8)
    )

prs.save(out / f"YouTube_AI趨勢研究雷達_{date}_簡報.pptx")

manifest = {
    "generated_at": now.isoformat(),
    "source": "YouTube Research MCP",
    "sample_count": len(videos),
    "word": str(out / f"YouTube_AI趨勢研究雷達_{date}_完整報告.docx"),
    "pptx": str(out / f"YouTube_AI趨勢研究雷達_{date}_簡報.pptx"),
    "chart": str(out / "top10_views.png"),
    "automation_status": "generated"
}
Path("reports/latest-manifest.json").write_text(
    json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
)
print(json.dumps(manifest, ensure_ascii=False, indent=2))
