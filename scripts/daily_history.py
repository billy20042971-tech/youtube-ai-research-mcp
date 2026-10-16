"""Bounded cross-day history for daily YouTube research summaries.

This records observations across successful report-generation runs. Repeated
appearance is a tracking signal, not proof of a market trend.
"""
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

try:
    from scripts.daily_summary import classify_topic
except ModuleNotFoundError:
    from daily_summary import classify_topic


def _parse_date(value):
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


def update_history(videos, summary, evidence, generated_at=None,
                   history_path="data/daily-summary-history.json", max_snapshots=90):
    """Append or replace today's snapshot and compare topics with prior runs."""
    generated = _parse_date(generated_at) or datetime.now(timezone.utc)
    snapshot_date = generated.date().isoformat()
    valid = [v for v in videos if isinstance(v, dict) and v.get("video_id")]
    topic_counts = Counter(classify_topic(video) for video in valid)
    snapshot = {
        "snapshot_date": snapshot_date,
        "generated_at": generated.isoformat(),
        "sample_count": len(valid),
        "video_ids": sorted({str(v["video_id"]) for v in valid}),
        "topic_counts": dict(sorted(topic_counts.items())),
        "stale_count": int(evidence.get("stale_count", 0)),
        "freshness_unknown_count": int(evidence.get("freshness_unknown_count", 0)),
    }

    path = Path(history_path)
    if path.exists():
        try:
            prior_data = json.loads(path.read_text(encoding="utf-8"))
            snapshots = prior_data.get("snapshots", [])
            if not isinstance(snapshots, list):
                raise ValueError("snapshots must be a list")
        except (json.JSONDecodeError, OSError, AttributeError, ValueError) as exc:
            raise RuntimeError(f"Cannot safely read daily history at {path}: {exc}") from exc
    else:
        snapshots = []

    # A same-day rerun replaces that day's record rather than inflating recurrence.
    prior_snapshots = [s for s in snapshots if s.get("snapshot_date") != snapshot_date]
    prior_snapshots.sort(key=lambda s: str(s.get("snapshot_date", "")))
    previous = prior_snapshots[-1] if prior_snapshots else None
    comparison = prior_snapshots[-6:]
    history_available = bool(comparison)
    current_ids = set(snapshot["video_ids"])
    previous_ids = set(previous.get("video_ids", [])) if previous else set()

    topic_observations = []
    for topic, count in sorted(topic_counts.items(), key=lambda item: (-item[1], item[0])):
        prior_runs = sum(
            int((s.get("topic_counts") or {}).get(topic, 0)) > 0
            for s in comparison
        )
        observed_runs = prior_runs + 1
        topic_observations.append({
            "topic": topic,
            "current_video_count": count,
            "prior_runs_in_last_6": prior_runs,
            "observed_runs_in_last_7": observed_runs,
            "classification": (
                "歷史基準，尚無前次資料" if not history_available
                else "多次出現的觀察訊號，仍需驗證" if prior_runs >= 2
                else "近期觀察訊號，尚未形成重複證據"
            ),
        })

    snapshots = sorted(prior_snapshots + [snapshot], key=lambda s: str(s.get("snapshot_date", "")))
    snapshots = snapshots[-max(1, int(max_snapshots)):]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"schema_version": 1, "retention_days": max_snapshots, "snapshots": snapshots},
                   ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    return {
        "status": "history_available" if history_available else "baseline",
        "snapshot_date": snapshot_date,
        "previous_snapshot_date": previous.get("snapshot_date") if previous else None,
        "historical_snapshot_count": len(prior_snapshots),
        "comparison_runs": len(comparison),
        "new_video_count": len(current_ids - previous_ids) if previous else None,
        "topic_observations": topic_observations,
        "limitations": [
            "歷史快照只代表本系統每次研究的有限樣本，不代表整個 AI 市場。",
            "同一主題多次出現是觀察訊號，不等於已證實趨勢、需求或投資機會。",
            "同日重跑會更新當日快照；最多保留最近 90 次記錄。",
        ],
    }
