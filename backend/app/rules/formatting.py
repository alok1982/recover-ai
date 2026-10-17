"""Locale formatting done in code (never by the model): amounts and playbook-timezone dates."""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal
from zoneinfo import ZoneInfo

CURRENCY_SYMBOL = {"INR": "₹", "MYR": "RM "}
TZ_LABELS = {"Asia/Kolkata": "IST", "Asia/Kuala_Lumpur": "MYT", "UTC": "UTC"}
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def indian_group(int_str: str) -> str:
    """'195000' -> '1,95,000' (lakh/crore grouping)."""
    neg = int_str.startswith("-")
    s = int_str.lstrip("-")
    if len(s) <= 3:
        out = s
    else:
        head, tail = s[:-3], s[-3:]
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        out = ",".join(groups + [tail])
    return ("-" if neg else "") + out


def western_group(int_str: str) -> str:
    neg = int_str.startswith("-")
    s = f"{int(int_str.lstrip('-')):,}"
    return ("-" if neg else "") + s


def format_number(amount: float | int | Decimal, currency: str | None) -> str:
    d = Decimal(str(amount)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    int_part, frac = f"{d:.2f}".split(".")
    grouped = indian_group(int_part) if (currency or "").upper() == "INR" else western_group(int_part)
    return grouped if frac == "00" else f"{grouped}.{frac}"


def format_amount(amount: float | int | Decimal | None, currency: str | None) -> str | None:
    """₹1,95,000 (Indian grouping) / RM 4,800 / USD 1,000."""
    if amount is None:
        return None
    cur = (currency or "").upper()
    num = format_number(amount, cur)
    sym = CURRENCY_SYMBOL.get(cur)
    return f"{sym}{num}" if sym else (f"{cur} {num}" if cur else num)


def tz_label(tz_name: str) -> str:
    return TZ_LABELS.get(tz_name, tz_name)


def to_local(dt: datetime, tz_name: str) -> datetime:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(ZoneInfo(tz_name))


def format_dt(dt: datetime | None, tz_name: str) -> str | None:
    """'17 Oct 2026, 14:02 IST' in the playbook's time zone."""
    if dt is None:
        return None
    loc = to_local(dt, tz_name)
    return f"{loc.day} {MONTHS[loc.month - 1]} {loc.year}, {loc:%H:%M} {tz_label(tz_name)}"


def format_date(dt: datetime | None, tz_name: str) -> str | None:
    if dt is None:
        return None
    loc = to_local(dt, tz_name)
    return f"{loc.day} {MONTHS[loc.month - 1]} {loc.year}"


def parse_local_datetime(value: str | None, tz_name: str) -> datetime | None:
    """Parse an extracted ISO datetime. With an offset it is honoured; without one it is local to the playbook tz.
    Returns UTC."""
    if not value:
        return None
    v = value.strip().replace("Z", "+00:00")
    if "T" not in v and " " in v:
        v = v.replace(" ", "T", 1)
    try:
        dt = datetime.fromisoformat(v)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=ZoneInfo(tz_name))
    return dt.astimezone(timezone.utc)
