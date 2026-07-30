from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from app.core.config import settings


def _local_tz() -> ZoneInfo:
    return ZoneInfo(settings.reminder_timezone)


def local_now() -> datetime:
    """Current time in the configured local timezone (tz-aware)."""
    return datetime.now(_local_tz())


def local_today() -> date:
    """Today's calendar date in the configured local timezone."""
    return local_now().date()


def to_local_date(dt: datetime) -> date:
    """Convert a naive UTC datetime (how timestamps are stored, e.g.
    WorkoutSession.completed_at) to its calendar date in the local timezone."""
    if dt.tzinfo is not None:
        raise ValueError("to_local_date expects a naive UTC datetime, got a tz-aware one")
    return dt.replace(tzinfo=timezone.utc).astimezone(_local_tz()).date()


def local_day_bounds_utc(day: date) -> tuple[datetime, datetime]:
    """Midnight-to-midnight bounds of a local calendar day, as naive UTC
    datetimes — for range-filtering columns stored as naive UTC."""
    start_local = datetime.combine(day, datetime.min.time(), tzinfo=_local_tz())
    end_local = start_local + timedelta(days=1)
    start_utc = start_local.astimezone(timezone.utc).replace(tzinfo=None)
    end_utc = end_local.astimezone(timezone.utc).replace(tzinfo=None)
    return start_utc, end_utc
