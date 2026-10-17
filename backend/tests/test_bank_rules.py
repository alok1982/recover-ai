"""PRD §10 rules over the F14 transaction features (computed from the synthetic BigQuery rows)."""
from datetime import datetime, timedelta, timezone

import pytest

from app.analytics.bq import LocalAnalytics
from app.bank.rules import compute_signals, high_risk_numbers, normalize_account_key, recommend
from app.rules.formatting import format_amount

NOW = datetime(2026, 10, 17, 9, 0, tzinfo=timezone.utc)


@pytest.fixture(scope="module")
def feats():
    a = LocalAnalytics(None, seed_time=NOW)
    return lambda key: a.features(normalize_account_key(key), NOW)


def payload(amount, acct, contacts, occurred=NOW - timedelta(minutes=30)):
    return {"amount": amount, "evidence_count": 2, "occurred_at_utc": occurred.isoformat(),
            "beneficiary": {"account_or_vpa": acct}, "scammer_contacts": contacts}


def test_join_key_normalisation():
    assert normalize_account_key("5140 1234 5678") == "514012345678"
    assert normalize_account_key(" CBI.Verify.Desk@okdemo ") == "cbi.verify.desk@okdemo"


def test_india_demo_account_is_high_risk_hold_limited_to_amount(feats):
    r = recommend(payload(195000, "cbi.verify.desk@okdemo", ["+91 90000 12345"]), feats("cbi.verify.desk@okdemo"), NOW)
    codes = [s["code"] for s in r["signals"]]
    assert codes == ["VICTIM_REPORT", "RECENT_TXN", "NEW_ACCOUNT", "FAN_IN", "RAPID_OUTFLOW", "FLAGGED_NUMBER", "PROFILE_MISMATCH"]
    assert r["riskScore"] == 100 and r["riskLevel"] == "HIGH" and r["recommendedAction"] == "TEMPORARY_HOLD"
    assert format_amount(r["holdLimitAmount"], "INR") == "₹1,95,000"


def test_malaysia_demo_account(feats):
    r = recommend(payload(4800, "5140 1234 5678", ["+60 11-0000 4321"]), feats("5140 1234 5678"), NOW)
    assert r["riskScore"] >= 70 and format_amount(r["holdLimitAmount"], "MYR") == "RM 4,800"


def test_hold_is_capped_by_balance(feats):
    f = dict(feats("cbi.verify.desk@okdemo"), current_balance=50000)
    assert recommend(payload(195000, "x", []), f, NOW)["holdLimitAmount"] == 50000


def test_unknown_account_uses_case_signals_only():
    r = recommend(payload(195000, "nobody@okdemo", []), None, NOW)
    assert [s["code"] for s in r["signals"]] == ["VICTIM_REPORT", "RECENT_TXN"]
    assert r["riskLevel"] == "MEDIUM" and r["recommendedAction"] == "ESCALATE_ANALYST" and r["holdLimitAmount"] == 0


def test_benign_contrast_accounts_low(feats):
    for key in ("grocer.sharma@okdemo", "112233445566"):
        p = payload(500, key, [], occurred=NOW - timedelta(days=3))
        p["evidence_count"] = 0
        r = recommend(p, feats(key), NOW)
        assert [s["code"] for s in r["signals"]] == ["FAN_IN"]  # a busy merchant: fan-in alone stays LOW
        assert r["riskScore"] == 20 and r["riskLevel"] == "LOW" and r["recommendedAction"] == "MONITOR"


def test_signal_thresholds_are_strict():
    base = {"account_age_days": 90, "distinct_senders_24h": 4, "outflow_60m_pct": 69.9, "credit_ratio_vs_avg": 10,
            "declared_profile": "student"}
    p = {"evidence_count": 0, "occurred_at_utc": None, "scammer_contacts": []}
    assert compute_signals(p, base, NOW) == []
    hot = {"account_age_days": 89, "distinct_senders_24h": 5, "outflow_60m_pct": 70, "credit_ratio_vs_avg": 10.01,
           "declared_profile": "homemaker"}
    assert [s["code"] for s in compute_signals(p, hot, NOW)] == ["NEW_ACCOUNT", "FAN_IN", "RAPID_OUTFLOW", "PROFILE_MISMATCH"]
    assert "PROFILE_MISMATCH" not in [s["code"] for s in compute_signals(p, dict(hot, declared_profile="salaried"), NOW)]


def test_recent_txn_uses_supplied_demo_clock():
    p = payload(1, "x", [], occurred=NOW)
    assert "RECENT_TXN" in [s["code"] for s in compute_signals(p, None, NOW + timedelta(hours=23))]
    assert "RECENT_TXN" not in [s["code"] for s in compute_signals(p, None, NOW + timedelta(hours=25))]
    assert "919000012345" in high_risk_numbers()
