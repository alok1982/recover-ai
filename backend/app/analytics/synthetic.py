"""Synthetic bank data for BigQuery (PRD §12.3) — deterministic, timestamps relative to the seed time.

* 40 accounts: 2 demo mule beneficiaries (IN VPA + MY account), 8 other mule-like accounts, 30 benign accounts
  (two of them are the "contrast" accounts shown in the demo).
* ~3,000 transactions: a 24 h pattern per account that realises its target features, plus up to 90 days of history.
* 50 anonymised case_events for the Scam intelligence tab (the IN demo beneficiary hash appears in 2 earlier cases).

Everything is generated from a fixed RNG seed, so the same seed time always yields identical rows; the same rows are
loaded into BigQuery (scripts/seed_bigquery.py) and into the offline LocalAnalytics backend (mock mode, tests).
"""
from __future__ import annotations

import hashlib
import random
from datetime import datetime, timedelta

from ..bank.rules import normalize_account_key
from ..timeutil import ensure_utc

RNG_SEED = 2026
HISTORY_DAYS = 90

# Target 24 h features per account (what §12.3 promises the feature query will return).
ANCHORS: list[dict] = [
    {"account_key": "cbi.verify.desk@okdemo", "country": "IN", "bank": "Sample Co-operative Bank", "holder_name": "R. K. (synthetic)",
     "account_type": "UPI VPA", "currency": "INR", "declared_profile": "student", "age_days": 21, "monthly_avg_credit": 12000,
     "credits_24h": 9, "distinct_senders_24h": 9, "credit_amount_24h": 980000, "outflow_pct": 82, "outflow_within_min": 40,
     "burst_hours_ago": 1.0, "current_balance": 264500, "is_mule": True, "role": "demo"},
    {"account_key": "514012345678", "country": "MY", "bank": "Bank Contoh Berhad", "holder_name": "PUSAT KASTAM PARCEL (synthetic)",
     "account_type": "Savings", "currency": "MYR", "declared_profile": "student", "age_days": 21, "monthly_avg_credit": 900,
     "credits_24h": 9, "distinct_senders_24h": 9, "credit_amount_24h": 21600, "outflow_pct": 82, "outflow_within_min": 40,
     "burst_hours_ago": 1.0, "current_balance": 6150, "is_mule": True, "role": "demo"},
    {"account_key": "grocer.sharma@okdemo", "country": "IN", "bank": "Bank of Demo", "holder_name": "Sharma General Store (synthetic)",
     "account_type": "UPI VPA", "currency": "INR", "declared_profile": "merchant", "age_days": 2190, "monthly_avg_credit": 450000,
     "credits_24h": 64, "distinct_senders_24h": 58, "credit_amount_24h": 18500, "outflow_pct": 5, "outflow_within_min": 55,
     "current_balance": 212000, "is_mule": False, "role": "contrast"},
    {"account_key": "112233445566", "country": "MY", "bank": "Bank Demo Malaysia", "holder_name": "Kedai Runcit Aminah (synthetic)",
     "account_type": "Current", "currency": "MYR", "declared_profile": "merchant", "age_days": 1460, "monthly_avg_credit": 30000,
     "credits_24h": 40, "distinct_senders_24h": 35, "credit_amount_24h": 1200, "outflow_pct": 3, "outflow_within_min": 55,
     "current_balance": 15800, "is_mule": False, "role": "contrast"},
]

_NAMES = ["Asha", "Vikas", "Meena", "Arjun", "Farah", "Lim", "Siti", "Ravi", "Neha", "Kumar", "Tan", "Nur", "Deepa", "Ali",
          "John", "Mira", "Priya", "Hafiz", "Anil", "Mei", "Sunita", "Azlan", "Rohit", "Aisyah", "Kavya", "Wei", "Imran", "Lakshmi",
          "Zul", "Pooja", "Iqbal", "Rina", "Suresh", "Hana", "Gopal", "Yusof"]
_HISTORY_CREDITS_PER_MONTH = {"merchant": 120, "business": 30, "self-employed": 10, "salaried": 6, "student": 4, "homemaker": 4}


def beneficiary_hash(account: str | None) -> str | None:
    key = normalize_account_key(account)
    return hashlib.sha256(key.encode()).hexdigest() if key else None


def _generated_specs(rng: random.Random) -> list[dict]:
    specs: list[dict] = []
    for i in range(36):  # 8 mule-like + 28 benign
        mule = i < 8
        country = "IN" if i % 2 == 0 else "MY"
        name = _NAMES[i]
        key = f"{name.lower()}{i}@okdemo" if country == "IN" else f"7{rng.randrange(10**10, 10**11)}"
        monthly = rng.choice([4000, 8000, 15000, 25000, 60000]) if country == "IN" else rng.choice([800, 1500, 3000, 5000])
        if mule:
            credits = rng.randint(5, 14)
            profile = rng.choice(["student", "homemaker", "student", "salaried", "self-employed"])
            spec = {"declared_profile": profile, "age_days": rng.choice([9, 14, 30, 45, 60, 75, 150, 300]),
                    "credits_24h": credits, "distinct_senders_24h": credits - rng.randint(0, 1),
                    "credit_amount_24h": round(monthly * rng.uniform(6, 60)), "outflow_pct": rng.randint(71, 95),
                    "outflow_within_min": rng.randint(15, 55), "burst_hours_ago": rng.uniform(1, 10)}
        else:
            profile = rng.choice(["salaried", "salaried", "student", "homemaker", "self-employed", "business"])
            credits = rng.randint(4, 15) if profile == "business" else rng.randint(0, 3)
            spec = {"declared_profile": profile, "age_days": rng.choice([200, 450, 800, 1500, 2400, 3600, 60]),
                    "credits_24h": credits, "distinct_senders_24h": max(0, credits - rng.randint(0, 2)) if credits else 0,
                    "credit_amount_24h": round(monthly * rng.uniform(0.05, 1.2)) if credits else 0,
                    "outflow_pct": rng.randint(0, 35) if credits else 0, "outflow_within_min": 55}
            if credits and spec["distinct_senders_24h"] == 0:
                spec["distinct_senders_24h"] = 1
        specs.append({
            "account_key": key, "country": country, "bank": "Bank of Demo" if country == "IN" else "Bank Demo Malaysia",
            "holder_name": f"{name} (synthetic)", "account_type": "UPI VPA" if country == "IN" else "Savings",
            "currency": "INR" if country == "IN" else "MYR", "monthly_avg_credit": monthly, "is_mule": mule,
            "role": "mule_like" if mule else "benign", **spec,
        })
    return specs


def _txn_id(key: str, n: int) -> str:
    return hashlib.sha1(f"{key}|{n}".encode()).hexdigest()[:16]


def _split(rng: random.Random, total: int, n: int) -> list[int]:
    if n <= 0:
        return []
    w = [rng.uniform(0.6, 1.4) for _ in range(n)]
    s = sum(w)
    parts = [max(1, int(total * x / s)) for x in w]
    parts[-1] += total - sum(parts)
    return parts


def _realise(spec: dict, seed_time: datetime, rng: random.Random) -> list[dict]:
    key, cur = spec["account_key"], spec["currency"]
    txns: list[dict] = []

    def add(direction: str, amount: int, cp: str, when: datetime) -> None:
        txns.append({"txn_id": _txn_id(key, len(txns)), "account_key": key, "direction": direction, "amount": int(amount),
                     "currency": cur, "counterparty_key": cp, "txn_time": when.replace(microsecond=0)})

    n, distinct = spec["credits_24h"], spec["distinct_senders_24h"]
    amounts = _split(rng, int(spec["credit_amount_24h"]), n)
    senders = [hashlib.sha1(f"{key}|sender|{j}".encode()).hexdigest()[:10] + ("@okpay" if cur == "INR" else "@duitnow")
               for j in range(max(distinct, 1))]
    if spec.get("burst_hours_ago") is not None:  # mule burst: credits close together, each moved out within minutes
        start = seed_time - timedelta(hours=spec["burst_hours_ago"])
        window = max(1, spec["outflow_within_min"] - 8)
        times = [start + timedelta(minutes=window * j / max(n - 1, 1)) for j in range(n)]
        lags = [rng.randint(3, 8) for _ in range(n)]
    else:  # benign: credits spread over the last 24 h; the small outflow follows a credit within the hour
        times = sorted(seed_time - timedelta(minutes=rng.randint(15, 23 * 60)) for _ in range(n))
        lags = [rng.randint(20, 55) for _ in range(n)]
    for j, (amt, when) in enumerate(zip(amounts, times)):
        add("CREDIT", amt, senders[j % len(senders)], when)
    target_out = round(sum(amounts) * spec["outflow_pct"] / 100)
    if target_out and n:
        outs = [round(target_out * a / sum(amounts)) for a in amounts]
        outs[-1] += target_out - sum(outs)
        mule_out = hashlib.sha1(f"{key}|out".encode()).hexdigest()[:10] + ("@okpay" if cur == "INR" else "@duitnow")
        for amt, when, lag in zip(outs, times, lags):
            if amt > 0:
                add("DEBIT", amt, mule_out, when + timedelta(minutes=lag))

    # History: from account opening (max 90 days back) to 25 h before the seed time.
    opened = seed_time - timedelta(days=spec["age_days"], hours=2)
    hist_start = max(opened, seed_time - timedelta(days=HISTORY_DAYS))
    hist_end = seed_time - timedelta(hours=25)
    if hist_end > hist_start:
        months = (hist_end - hist_start).total_seconds() / (30 * 86400)
        per_month = _HISTORY_CREDITS_PER_MONTH.get(spec["declared_profile"], 4)
        if spec["is_mule"]:
            per_month = 2
        count = max(1, round(per_month * months))
        each = max(1, round(spec["monthly_avg_credit"] / per_month))
        span = int((hist_end - hist_start).total_seconds())
        pool = [hashlib.sha1(f"{key}|hist|{j}".encode()).hexdigest()[:10] + "@hist" for j in range(12)]
        for _ in range(count):
            when = hist_start + timedelta(seconds=rng.randint(0, span))
            amt = max(1, round(each * rng.uniform(0.5, 1.5)))
            add("CREDIT", amt, rng.choice(pool), when)
            if rng.random() < 0.7:  # spending happens hours/days later, never inside the 60-min window
                add("DEBIT", round(amt * rng.uniform(0.3, 0.9)), rng.choice(pool), min(hist_end, when + timedelta(hours=rng.randint(3, 72))))
    return txns


def generate(seed_time: datetime) -> dict:
    """Return {"accounts", "txns", "case_events", "seed_time"} for the given seed time (UTC)."""
    seed_time = ensure_utc(seed_time).replace(microsecond=0)
    rng = random.Random(RNG_SEED)
    specs = [dict(a) for a in ANCHORS] + _generated_specs(rng)
    accounts, txns = [], []
    for spec in specs:
        arng = random.Random(f"{RNG_SEED}|{spec['account_key']}")
        t = _realise(spec, seed_time, arng)
        txns.extend(t)
        if "current_balance" not in spec:
            cr = sum(x["amount"] for x in t if x["direction"] == "CREDIT")
            db = sum(x["amount"] for x in t if x["direction"] == "DEBIT")
            spec["current_balance"] = max(0, cr - db)
        accounts.append({
            "account_key": spec["account_key"], "country": spec["country"], "bank": spec["bank"],
            "opened_at": (seed_time - timedelta(days=spec["age_days"], hours=2)), "declared_profile": spec["declared_profile"],
            "monthly_avg_credit": spec["monthly_avg_credit"], "is_mule": spec["is_mule"],
            "holder_name": spec["holder_name"], "account_type": spec["account_type"], "currency": spec["currency"],
            "current_balance": spec["current_balance"], "role": spec["role"],
        })
    return {"seed_time": seed_time, "accounts": accounts, "txns": txns, "case_events": _case_events(seed_time, accounts, rng)}


_SCAM_MIX = [("digital_arrest", 6), ("investment_trading", 5), ("fake_courier_customs", 4), ("job_task", 4),
             ("kyc_update", 2), ("romance", 1), ("phishing_link", 2), ("loan_app", 1)]


def _case_events(seed_time: datetime, accounts: list[dict], rng: random.Random) -> list[dict]:
    mules = [a for a in accounts if a["is_mule"] and a["role"] != "demo"]
    benign = [a for a in accounts if not a["is_mule"]]
    demo_in = next(a for a in accounts if a["account_key"] == "cbi.verify.desk@okdemo")
    types = [t for t, w in _SCAM_MIX for _ in range(w)]
    events: list[dict] = []
    case_no = 0

    def case(acct: dict, scam: str, days_ago: float, decided: bool) -> None:
        nonlocal case_no
        case_no += 1
        cid = f"c_synth{case_no:03d}"
        when = seed_time - timedelta(days=days_ago)
        amount = rng.choice([25000, 48000, 95000, 150000, 310000]) if acct["country"] == "IN" else rng.choice([1200, 2500, 4800, 9000])
        base = {"case_id": cid, "country": acct["country"], "scam_type": scam, "amount": amount, "currency": acct["currency"],
                "beneficiary_hash": beneficiary_hash(acct["account_key"])}
        events.append({**base, "event_id": f"{cid}-confirmed", "event_type": "case_confirmed", "risk_level": None,
                       "decision": None, "event_time": when.replace(microsecond=0)})
        if decided:
            level = "HIGH" if acct["is_mule"] else rng.choice(["LOW", "MEDIUM"])
            decision = "APPROVE_HOLD" if level == "HIGH" else rng.choice(["REJECT", "REQUEST_INFO"])
            events.append({**base, "event_id": f"{cid}-decision", "event_type": "bank_decision", "risk_level": level,
                           "decision": decision, "event_time": (when + timedelta(hours=rng.uniform(1, 20))).replace(microsecond=0)})

    case(demo_in, "digital_arrest", 6.5, True)   # the demo beneficiary already appeared in 2 earlier cases
    case(demo_in, "digital_arrest", 3.2, True)
    while len(events) < 50:
        acct = rng.choice(mules) if rng.random() < 0.7 else rng.choice(benign)
        decided = rng.random() < 0.5 and len(events) <= 48
        case(acct, rng.choice(types), rng.uniform(0.5, 28), decided)
    return events[:50]
