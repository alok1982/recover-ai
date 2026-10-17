from datetime import datetime, timezone

import pytest

from app.rules.formatting import format_amount, format_dt, indian_group, parse_local_datetime


@pytest.mark.parametrize("raw,expected", [
    ("0", "0"), ("999", "999"), ("1000", "1,000"), ("25000", "25,000"), ("195000", "1,95,000"),
    ("1000000", "10,00,000"), ("12345678", "1,23,45,678"), ("-195000", "-1,95,000"),
])
def test_indian_lakh_grouping(raw, expected):
    assert indian_group(raw) == expected


def test_format_amount_by_currency():
    assert format_amount(195000, "INR") == "₹1,95,000"
    assert format_amount(195000.0, "inr") == "₹1,95,000"
    assert format_amount(4800, "MYR") == "RM 4,800"
    assert format_amount(4800.5, "MYR") == "RM 4,800.50"
    assert format_amount(1234567.891, "INR") == "₹12,34,567.89"
    assert format_amount(1000, "USD") == "USD 1,000"
    assert format_amount(None, "INR") is None


def test_format_dt_in_playbook_timezone():
    utc = datetime(2026, 10, 17, 8, 32, tzinfo=timezone.utc)
    assert format_dt(utc, "Asia/Kolkata") == "17 Oct 2026, 14:02 IST"
    assert format_dt(utc, "Asia/Kuala_Lumpur") == "17 Oct 2026, 16:32 MYT"
    # crossing midnight changes the local date
    late = datetime(2026, 12, 31, 20, 0, tzinfo=timezone.utc)
    assert format_dt(late, "Asia/Kolkata") == "1 Jan 2027, 01:30 IST"


def test_parse_local_datetime():
    # explicit offset honoured
    assert parse_local_datetime("2026-10-17T14:02:00+05:30", "Asia/Kolkata") == datetime(2026, 10, 17, 8, 32, tzinfo=timezone.utc)
    # naive time is local to the playbook tz, stored in UTC
    assert parse_local_datetime("2026-10-17T10:15:00", "Asia/Kuala_Lumpur") == datetime(2026, 10, 17, 2, 15, tzinfo=timezone.utc)
    assert parse_local_datetime("2026-10-17 14:02", "Asia/Kolkata") == datetime(2026, 10, 17, 8, 32, tzinfo=timezone.utc)
    assert parse_local_datetime("2026-10-17T08:32:00Z", "Asia/Kolkata") == datetime(2026, 10, 17, 8, 32, tzinfo=timezone.utc)
    assert parse_local_datetime("yesterday", "Asia/Kolkata") is None
    assert parse_local_datetime(None, "Asia/Kolkata") is None
