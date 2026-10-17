from datetime import datetime, timedelta, timezone

from app.bank.rules import compute_signals, high_risk_numbers, normalize_account_key, recommend, synthetic_accounts
from app.rules.formatting import format_amount

NOW = datetime(2026, 10, 17, 9, 0, tzinfo=timezone.utc)
ACCTS = {normalize_account_key(a["id"]): a for a in synthetic_accounts()}


def payload(amount, acct, contacts, occurred=NOW - timedelta(minutes=30)):
    return {"amount": amount, "evidence_count": 2, "occurred_at_utc": occurred.isoformat(),
            "beneficiary": {"account_or_vpa": acct}, "scammer_contacts": contacts}


def test_join_key_normalisation():
    assert normalize_account_key("5140 1234 5678") == "514012345678"
    assert normalize_account_key(" CBI.Verify.Desk@okdemo ") == "cbi.verify.desk@okdemo"
    assert "cbi.verify.desk@okdemo" in ACCTS and "514012345678" in ACCTS
    assert len(ACCTS) == 20


def test_india_demo_account_is_high_risk_hold_limited_to_amount():
    r = recommend(payload(195000, "cbi.verify.desk@okdemo", ["+91 90000 12345"]), ACCTS["cbi.verify.desk@okdemo"], NOW)
    codes = [s["code"] for s in r["signals"]]
    assert codes == ["VICTIM_REPORT", "RECENT_TXN", "NEW_ACCOUNT", "FAN_IN", "RAPID_OUTFLOW", "FLAGGED_NUMBER", "PROFILE_MISMATCH"]
    assert r["riskScore"] == 100 and r["riskLevel"] == "HIGH" and r["recommendedAction"] == "TEMPORARY_HOLD"
    assert format_amount(r["holdLimitAmount"], "INR") == "₹1,95,000"


def test_malaysia_demo_account():
    r = recommend(payload(4800, "5140 1234 5678", ["+60 11-0000 4321"]), ACCTS["514012345678"], NOW)
    assert r["riskScore"] >= 70 and format_amount(r["holdLimitAmount"], "MYR") == "RM 4,800"


def test_hold_is_capped_by_balance():
    acct = dict(ACCTS["cbi.verify.desk@okdemo"], currentBalance=50000)
    r = recommend(payload(195000, "x", []), acct, NOW)
    assert r["holdLimitAmount"] == 50000


def test_unknown_account_uses_case_signals_only():
    r = recommend(payload(195000, "nobody@okdemo", []), None, NOW)
    assert [s["code"] for s in r["signals"]] == ["VICTIM_REPORT", "RECENT_TXN"]
    assert r["riskLevel"] == "MEDIUM" and r["recommendedAction"] == "ESCALATE_ANALYST" and r["holdLimitAmount"] == 0


def test_benign_account_and_old_transaction_low():
    p = payload(500, "grocer.sharma@okdemo", [], occurred=NOW - timedelta(days=3))
    p["evidence_count"] = 0
    r = recommend(p, ACCTS["grocer.sharma@okdemo"], NOW)
    assert [s["code"] for s in r["signals"]] == ["FAN_IN"]  # a busy merchant: fan-in alone stays LOW
    assert r["riskScore"] == 20 and r["riskLevel"] == "LOW" and r["recommendedAction"] == "MONITOR"


def test_recent_txn_uses_supplied_demo_clock():
    p = payload(1, "x", [], occurred=NOW)
    assert "RECENT_TXN" in [s["code"] for s in compute_signals(p, None, NOW + timedelta(hours=23))]
    assert "RECENT_TXN" not in [s["code"] for s in compute_signals(p, None, NOW + timedelta(hours=25))]
    assert "919000012345" in high_risk_numbers()
