"""Fail-closed guard for delayed GitHub scheduled research runs.

GitHub Actions cron is best-effort. This guard does not trigger retries or
recovery; it prevents a materially late scheduled run from publishing data.
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone


SCHEDULE_HOUR_UTC = 22  # 06:00 Asia/Taipei
DEFAULT_MAX_LATENESS_MINUTES = 15


def expected_slot(now: datetime, schedule_hour_utc: int = SCHEDULE_HOUR_UTC) -> datetime:
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    utc_now = now.astimezone(timezone.utc)
    slot_date = utc_now.date()
    slot = datetime(slot_date.year, slot_date.month, slot_date.day, schedule_hour_utc, tzinfo=timezone.utc)
    if utc_now < slot:
        slot -= timedelta(days=1)
    return slot


def schedule_lateness_minutes(now: datetime, schedule_hour_utc: int = SCHEDULE_HOUR_UTC) -> float:
    return (now.astimezone(timezone.utc) - expected_slot(now, schedule_hour_utc)).total_seconds() / 60


def validate_schedule_start(
    now: datetime,
    max_lateness_minutes: int = DEFAULT_MAX_LATENESS_MINUTES,
    schedule_hour_utc: int = SCHEDULE_HOUR_UTC,
) -> None:
    if max_lateness_minutes < 0:
        raise ValueError("max_lateness_minutes must be non-negative")
    expected = expected_slot(now, schedule_hour_utc)
    actual = now.astimezone(timezone.utc)
    lateness = (actual - expected).total_seconds() / 60
    if lateness > max_lateness_minutes:
        raise RuntimeError(
            "Scheduled run missed its start deadline: "
            f"expected_slot={expected.isoformat()}, actual_start={actual.isoformat()}, "
            f"lateness_minutes={lateness:.1f}, allowed_minutes={max_lateness_minutes}. "
            "No research API call or Notion write was started; wait for human review."
        )


def main() -> int:
    if os.getenv("GITHUB_EVENT_NAME") != "schedule":
        print("Schedule timing gate: skipped for non-scheduled event.")
        return 0
    raw = os.getenv("SCHEDULE_MAX_LATENESS_MINUTES", str(DEFAULT_MAX_LATENESS_MINUTES))
    try:
        tolerance = int(raw)
        validate_schedule_start(datetime.now(timezone.utc), tolerance)
    except (ValueError, RuntimeError) as exc:
        print(f"::error::{exc}", file=sys.stderr)
        return 1
    print(f"Schedule timing gate: PASS (maximum lateness {tolerance} minutes).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
