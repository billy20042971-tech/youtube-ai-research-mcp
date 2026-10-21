"""Taipei-local date naming for daily research artifacts."""
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

TAIPEI = ZoneInfo("Asia/Taipei")


def report_date_taipei(now: datetime | None = None) -> str:
    """Return the Asia/Taipei calendar date for a timestamp."""
    if now is None:
        now = datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    return now.astimezone(TAIPEI).strftime("%Y-%m-%d")
