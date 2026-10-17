"""UTC helpers. All timestamps are stored in UTC; display conversion lives in rules/formatting.py."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def ensure_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def effective_now(case: dict, real_now: datetime | None = None) -> datetime:
    """Demo clock: real time shifted by the per-case clockOffsetDays (stored timestamps never change)."""
    now = ensure_utc(real_now or utcnow())
    return now + timedelta(days=float(case.get("clockOffsetDays") or 0))


def to_iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    return ensure_utc(dt).isoformat().replace("+00:00", "Z")


def parse_iso(value: str | datetime | None) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return ensure_utc(value)
    v = value.strip().replace("Z", "+00:00")
    return datetime.fromisoformat(v)
