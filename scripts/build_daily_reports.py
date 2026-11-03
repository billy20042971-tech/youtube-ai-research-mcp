import json
from pathlib import Path
from datetime import datetime, timezone
from collections import Counter
import re

try:
    from scripts.report_analysis import chinese_title, clean_description, tool_guidance, recommendation_reason
except ModuleNotFoundError:
    from report_analysis import chinese_title

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

# Visuals: explicitly use a CJK font and wrap long labels for legibility.
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager
from textwrap import wrap

available_fonts = {f.name for f in font_manager.fontManager.ttflist}
cjk_candidates = ["Noto Sans CJK TC", "Noto Sans CJK HK", "Noto Sans CJK SC", "Noto Sans CJK JP"]
chosen_font = next((name for name in cjk_candidates if name in available_fonts), None)
if not chosen_font:
    raise RuntimeError(
        "No supported CJK font found. Install fonts-noto-cjk before generating charts; "
        f"available candidates checked: {cjk_candidates}"
    )
plt.rcParams["font.family"] = chosen_font
plt.rcParams["axes.unicode_minus"] = False

top = videos[:10]
def chart_label(title):
    # Keep chart labels readable; retain full titles and URLs in the Word report.
    text = re.sub(r"\s+", " ", str(title or "")).strip()
    if not text:
        return "(無標題)"
    lines = wrap(text, width=18, break_long_words=True, break_on_hyphens=False)
    if len(lines) > 2:
        lines = [lines[0], lines[1][:15] + "…"]
    return "\n".join(lines)

labels = [chart_label(chinese_title(v)) for v in top][::-1]
values = [safe_int(v.get("views")) for v in top][::-1]
fig_height = max(7.0, 0.72 * len(labels) + 1.8)
fig, ax = plt.subplots(figsize=(12, fig_height))
ax.barh(labels, values, color="#2878B5")
ax.set_title("YouTube AI 趨勢研究雷達｜觀看數前 10 名", fontsize=15, pad=16)
ax.set_xlabel("觀看次數", fontsize=11)
ax.tick_params(axis="y", labelsize=9)
ax.tick_params(axis="x", labelsize=9)
ax.grid(axis="x", linestyle=":", alpha=0.35)
ax.set_axisbelow(True)
fig.subplots_adjust(left=0.38, right=0.97, top=0.94, bottom=0.08)
chart_path = out / "top10_views.png"
fig.savefig(chart_path, dpi=180, bbox_inches="tight", facecolor="white")
plt.close(fig)

# Basic artifact sanity checks: image must be readable PNG and non-trivial size.
from PIL import Image
with Image.open(chart_path) as chart:
    chart.verify()
with Image.open(chart_path) as chart:
    if chart.width < 1000 or chart.height < 600:
        raise RuntimeError(f"Chart dimensions too small: {chart.size}")
if chart_path.stat().st_size < 20_000:
    raise RuntimeError(f"Chart file suspiciously small: {chart_path.stat().st_size} bytes")

channels = Counter(v.get("channel_title", "") for v in videos if v.get("channel_title"))
queries = Counter(v.get("query", "") for v in videos if v.get("query"))

# Word：以使用者決策與實際應用為中心，避免工程日誌。
from docx import Document
from docx.shared import Inches
try:
    from scripts.report_analysis import analyze_sample, chinese_title, useful_comments
except ModuleNotFoundError:  # Direct execution: python scripts/<file>.py
    from report_analysis import analyze_sample, chinese_title, useful_comments, clean_description, tool_guidance, recommendation_reason

analysis = analyze_sample(videos)
doc = Document()
doc.add_heading(f"每日 AI 情報研究報告｜{date}", 0)
doc.add_paragraph(f"資料範圍：近 72 小時｜去重影片：{len(videos)} 部｜資料來源：YouTube Research MCP")
doc.add_heading("⭐ 今日 Top 3 必看推薦", level=1)
for idx, v in enumerate(analysis["top3"], 1):
    doc.add_heading(f"{idx}. {chinese_title(v)}", level=2)
    doc.add_paragraph(f"推薦原因：{recommendation_reason(v)}｜頻道：{v.get('channel_title') or '未提供'}")
    summary_text = clean_description(v.get("description_zh") or v.get("translated_description") or v.get("description") or "")
    doc.add_paragraph(f"閱讀收穫：{summary_text[:320] or '來源資訊不足；請先查看原始影片或逐字稿，再判斷實際價值。'}")
    if v.get("url"):
        doc.add_paragraph(f"影片連結：{v['url']}")
    doc.add_paragraph(f"原始標題（核對用）：{str(v.get('title') or '未提供')}", style="Caption")
doc.add_heading("🚀 今日 3 分鐘核心趨勢摘要", level=1)
doc.add_paragraph("今日最值得關注的 AI 變化，依有效樣本中的具體工具、商業模式與可驗證流程歸納；資料不足處明確標示，不以觀看數單獨推論趨勢。")
for idx, signal in enumerate(analysis["signals"], 1):
    doc.add_heading(f"訊號 {idx}｜{signal['name']}（{signal['count']} 部）", level=2)
    doc.add_paragraph(signal["summary"])
doc.add_heading("📊 主題分類洞察", level=1)
for name, entries in analysis["buckets"].items():
    if not entries:
        continue
    examples = "；".join(chinese_title(v) for v in entries[:3])
    doc.add_heading(f"{name}｜{len(entries)} 部", level=2)
    doc.add_paragraph(
        f"本主題在今日樣本中共 {len(entries)} 部，代表內容：{examples}。"
        "閱讀時應區分影片展示、作者主張與可獨立驗證的成果；單一案例不能直接推論普遍成效。"
    )
doc.add_heading("💡 精選高價值影片拆解", level=1)
doc.add_paragraph("依觀看數、按讚與留言量的對數加權排序；互動分數僅用於挑選閱讀順序，不代表內容品質或觀眾認同。")
for idx, v in enumerate(analysis["top"][:10], 1):
    original = str(v.get("title") or "（未提供標題）")
    doc.add_heading(f"{idx}. {chinese_title(v)}", level=2)
    doc.add_paragraph(f"原始標題（小字附註）：{original}｜頻道：{v.get('channel_title') or '未提供'}", style="Caption")
    doc.add_paragraph(f"觀看數：{safe_int(v.get('views')):,}｜按讚：{safe_int(v.get('likes')):,}｜發布：{v.get('published_at') or '未提供'}")
    description = clean_description(v.get("description_zh") or v.get("translated_description") or v.get("description") or "")
    guide = tool_guidance(v)
    doc.add_heading("🎯 核心商業價值", level=3)
    doc.add_paragraph(description[:700] if description else "來源資訊不足：目前未取得可確認的繁體中文內容摘要，不能推定商業成果或作者主張。")
    doc.add_heading("🛠️ 使用的 AI 工具與工作流", level=3)
    doc.add_paragraph(guide["label"] + "｜" + guide["workflow"])
    doc.add_heading("💡 實操建議與注意事項", level=3)
    for step in guide["steps"][:3]:
        doc.add_paragraph(step, style="List Number")
    if v.get("url"):
        doc.add_paragraph(f"原始影片連結：{v['url']}")
    doc.add_paragraph(f"推薦理由：{recommendation_reason(v)}；工具指引依可辨識線索提供，未經來源證實的內容不得視為影片示範。", style="Caption")
doc.add_heading("💬 社群觀眾反應與避坑指南", level=1)
for v in analysis["top"][:10]:
    comments = useful_comments(v, 3)
    if not comments:
        continue
    doc.add_heading(chinese_title(v), level=2)
    for comment in comments:
        doc.add_paragraph("觀眾回饋：" + comment)
doc.add_paragraph("避坑提醒：留言是自選樣本，不能視為整體觀眾民調。特別留意獲利／銷量承諾、平台政策變動、隱藏訂閱費、工具學習門檻，以及缺乏可重現步驟的成功案例。")
doc.add_picture(str(chart_path), width=Inches(6.4))
doc.save(out / f"YouTube_AI趨勢研究雷達_{date}_完整報告.docx")

# PowerPoint：與 Word 相同的四章結構，適合手機快速瀏覽。
from pptx import Presentation
from pptx.util import Inches as PInches
prs = Presentation()
slides = [
    ("每日 AI 情報研究雷達", f"{date}｜近 72 小時樣本 {len(videos)} 部"),
    ("⭐ 今日 Top 3 必看推薦", "\n".join(f"{i+1}. {chinese_title(v)}｜{recommendation_reason(v)}" for i, v in enumerate(analysis["top3"]))),
    ("🚀 今日 3 分鐘核心趨勢摘要", "\n".join(f"{x['name']}：{x['count']} 部" for x in analysis["signals"])),
]
for name, entries in analysis["buckets"].items():
    if entries:
        sample_titles = "\n".join(f"・{str(v.get('title') or '')[:42]}" for v in entries[:3])
        slides.append((f"📊 {name}（{len(entries)} 部）", sample_titles))
for idx, v in enumerate(analysis["top"][:5], 1):
    guide = tool_guidance(v)
    detail = clean_description(v.get("description_zh") or v.get("translated_description") or v.get("description") or "")
    slides.append((f"🎬 精選 {idx}｜{chinese_title(v)}", f"🎯 核心商業價值：{detail[:220] or '來源資訊不足'}\n🛠️ 工具與工作流：{guide['label']}｜{guide['workflow']}\n💡 實操建議：{guide['steps'][0]}\n原始標題：{v.get('title', '')}"))
slides.append(("💬 社群反應與避坑", "過濾推廣與無關留言；檢查獲利承諾、平台政策、訂閱成本與實作門檻。\n留言為自選樣本，不代表整體觀眾。"))
for title, body in slides:
    slide = prs.slides.add_slide(prs.slide_layouts[1])
    slide.shapes.title.text = title
    slide.placeholders[1].text = body
slide = prs.slides.add_slide(prs.slide_layouts[5])
slide.shapes.add_picture(str(chart_path), PInches(0.6), PInches(1.1), width=PInches(8.8))
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
