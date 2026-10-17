"""Deterministic bank recommendation rules (PRD §10). The model never decides the action or the amount.

Inputs: the A2A case payload + the beneficiary's transaction features from the BigQuery feature query (F14,
backend/sql/features.sql). Feature dict keys: account_age_days, credits_24h, distinct_senders_24h,
outflow_60m_pct, credit_ratio_vs_avg, declared_profile, current_balance. ``None`` = account not found or
transaction data unavailable: only the case signals (VICTIM_REPORT, RECENT_TXN, FLAGGED_NUMBER) can fire.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta
from functools import lru_cache
from pathlib import Path

from ..timeutil import ensure_utc, parse_iso

DATA_DIR = Path(__file__).resolve().parent / "data"

SIGNALS = {
    "VICTIM_REPORT": ("Victim report with evidence", 30),
    "RECENT_TXN": ("Transaction less than 24 h ago", 15),
    "NEW_ACCOUNT": ("Beneficiary account younger than 90 days", 15),
    "FAN_IN": ("≥ 5 credits from distinct senders in last 24 h", 20),
    "RAPID_OUTFLOW": ("≥ 70% of credited amount moved out within 60 min", 20),
    "FLAGGED_NUMBER": ("Scammer number on high-risk list", 10),
    "PROFILE_MISMATCH": ("Student/homemaker profile with 24 h credits > 10× monthly average", 10),
}
HOLD_NOTE = "Temporary, amount-limited hold. Final decision by analyst."


def normalize_account_key(value: str | None) -> str:
    """Join key for bank_accounts: lower-case VPA / account number without spaces or dashes."""
    return re.sub(r"[\s\-]", "", (value or "").strip().lower())


def normalize_phone(value: str) -> str:
    digits = re.sub(r"\D", "", value or "")
    return digits


@lru_cache
def high_risk_numbers() -> frozenset[str]:
    data = json.loads((DATA_DIR / "high_risk_numbers.json").read_text())
    return frozenset(normalize_phone(n) for n in data["numbers"])


def _phone_match(contact: str, risky: frozenset[str]) -> bool:
    d = normalize_phone(contact)
    if not d:
        return False
    return any(d == r or (len(d) >= 9 and (r.endswith(d) or d.endswith(r[-10:]))) for r in risky)


def compute_signals(payload: dict, features: dict | None, now: datetime,
                    risky_numbers: frozenset[str] | None = None) -> list[dict]:
    risky = risky_numbers if risky_numbers is not None else high_risk_numbers()
    fired: list[str] = []
    if payload.get("evidence_count", 0) > 0:
        fired.append("VICTIM_REPORT")
    occurred = parse_iso(payload.get("occurred_at_utc"))
    if occurred and timedelta(0) <= ensure_utc(now) - occurred < timedelta(hours=24):
        fired.append("RECENT_TXN")
    if features:
        age = features.get("account_age_days")
        if age is not None and age < 90:
            fired.append("NEW_ACCOUNT")
        if (features.get("distinct_senders_24h") or 0) >= 5:
            fired.append("FAN_IN")
        if (features.get("outflow_60m_pct") or 0) >= 70:
            fired.append("RAPID_OUTFLOW")
        if features.get("declared_profile") in ("student", "homemaker") and (features.get("credit_ratio_vs_avg") or 0) > 10:
            fired.append("PROFILE_MISMATCH")
    if any(_phone_match(c, risky) for c in payload.get("scammer_contacts") or []):
        fired.append("FLAGGED_NUMBER")
    order = list(SIGNALS)
    return [{"code": c, "label": SIGNALS[c][0], "weight": SIGNALS[c][1]} for c in sorted(set(fired), key=order.index)]


def risk_level(score: int) -> str:
    if score >= 70:
        return "HIGH"
    if score >= 40:
        return "MEDIUM"
    return "LOW"


def recommend(payload: dict, features: dict | None, now: datetime,
              risky_numbers: frozenset[str] | None = None) -> dict:
    signals = compute_signals(payload, features, now, risky_numbers)
    score = min(100, sum(s["weight"] for s in signals))
    level = risk_level(score)
    action = {"HIGH": "TEMPORARY_HOLD", "MEDIUM": "ESCALATE_ANALYST", "LOW": "MONITOR"}[level]
    amount = float(payload.get("amount") or 0)
    hold = 0.0
    if action == "TEMPORARY_HOLD":
        balance = features.get("current_balance") if features else None
        hold = min(amount, float(balance)) if balance is not None else amount
    return {"signals": signals, "riskScore": score, "riskLevel": level, "recommendedAction": action,
            "holdLimitAmount": hold, "note": HOLD_NOTE}
