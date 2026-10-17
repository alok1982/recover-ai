"""F14 transaction & risk analytics: beneficiary feature query, case_events inserts, Scam intelligence; S2 ML score.

Two interchangeable backends:
* BigQueryAnalytics — production: parameterised SQL in backend/sql/*.sql against dataset `recoverai_analytics`.
* LocalAnalytics    — offline mock mode/tests: the same synthetic rows (analytics/synthetic.py) and a pure-Python
  implementation of the same queries. tests/test_analytics.py proves the SQL and the Python agree by running the
  BigQuery SQL (transpiled with sqlglot) on DuckDB over identical data.

The query only runs on the bank path (Bank Case Receiver), never in the victim's chat path.
"""
from __future__ import annotations

import json
import logging
import math
import re
import threading
import time
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, Protocol

from ..config import BACKEND_DIR, get_settings
from ..timeutil import ensure_utc, parse_iso, to_iso, utcnow
from . import synthetic

log = logging.getLogger("recoverai.analytics")
SQL_DIR = BACKEND_DIR / "sql"
FEATURE_KEYS = ("account_age_days", "credits_24h", "distinct_senders_24h", "outflow_60m_pct", "credit_ratio_vs_avg")
ACCOUNT_COLUMNS = ("account_key", "country", "bank", "opened_at", "declared_profile", "monthly_avg_credit", "is_mule",
                   "holder_name", "account_type", "currency", "current_balance")


class AnalyticsError(RuntimeError):
    pass


class Analytics(Protocol):
    name: str

    def features(self, account_key: str, now: datetime) -> dict | None: ...
    def insert_case_event(self, event: dict) -> None: ...
    def scam_intelligence(self, now: datetime) -> dict: ...
    def ml_score(self, features: dict) -> float | None: ...
    def seed(self, seed_time: datetime | None = None, with_ml: bool = True) -> dict: ...


def load_sql(name: str, dataset: str = "recoverai_analytics") -> str:
    sql = (SQL_DIR / f"{name}.sql").read_text(encoding="utf-8")
    return sql.replace("recoverai_analytics.", f"{dataset}.") if dataset != "recoverai_analytics" else sql


def sql_sections(sql: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for block in re.split(r"^-- name:\s*", sql, flags=re.M)[1:]:
        name, _, body = block.partition("\n")
        out[name.strip()] = body.strip().rstrip(";")
    return out


def _num(v: Any) -> Any:
    if isinstance(v, Decimal):
        return float(v)
    return v


# ------------------------------------------------------------------ pure-Python reference implementation
def compute_features(accounts: dict[str, dict], txns_by_acct: dict[str, list[dict]], key: str, now: datetime) -> dict | None:
    a = accounts.get(key)
    if not a:
        return None
    now = ensure_utc(now)
    lo = now - timedelta(hours=24)
    rows = txns_by_acct.get(key, [])
    c = [t for t in rows if t["direction"] == "CREDIT" and lo <= t["txn_time"] <= now]
    d = [t for t in rows if t["direction"] == "DEBIT" and lo <= t["txn_time"] <= now]
    d60 = [x for x in d if any(y["txn_time"] <= x["txn_time"] <= y["txn_time"] + timedelta(minutes=60) for y in c)]
    credit_sum = sum(t["amount"] for t in c)
    out = (sum(t["amount"] for t in d60) / credit_sum * 100) if credit_sum else None
    return {
        "account_found": True,
        "account_age_days": math.floor(int((now - ensure_utc(a["opened_at"])).total_seconds()) / 86400),
        "credits_24h": len(c),
        "distinct_senders_24h": len({t["counterparty_key"] for t in c}),
        "outflow_60m_pct": None if out is None else min(100.0, out),
        "credit_ratio_vs_avg": (credit_sum / a["monthly_avg_credit"]) if c and a.get("monthly_avg_credit") else None,
        "credit_amount_24h": credit_sum if c else None,
        "declared_profile": a.get("declared_profile"), "current_balance": a.get("current_balance"),
        "monthly_avg_credit": a.get("monthly_avg_credit"), "bank": a.get("bank"), "holder_name": a.get("holder_name"),
        "account_type": a.get("account_type"), "currency": a.get("currency"),
    }


def _ml_vector(f: dict) -> list[float]:
    return [math.log1p(max(0.0, float(f.get("account_age_days") or 0))), float(f.get("credits_24h") or 0),
            float(f.get("distinct_senders_24h") or 0), float(f.get("outflow_60m_pct") or 0),
            math.log1p(max(0.0, float(f.get("credit_ratio_vs_avg") or 0)))]


def train_logistic(rows: list[tuple[list[float], bool]], l2: float = 0.1, iters: int = 3000, lr: float = 0.3) -> dict:
    """Standardised L2 logistic regression (what BigQuery ML's logistic_reg does), batch gradient descent."""
    n, k = len(rows), len(rows[0][0])
    mean = [sum(r[0][j] for r in rows) / n for j in range(k)]
    std = [max(1e-9, math.sqrt(sum((r[0][j] - mean[j]) ** 2 for r in rows) / n)) for j in range(k)]
    xs = [[(r[0][j] - mean[j]) / std[j] for j in range(k)] for r in rows]
    ys = [1.0 if r[1] else 0.0 for r in rows]
    w, b = [0.0] * k, 0.0
    for _ in range(iters):
        gw, gb = [0.0] * k, 0.0
        for x, y in zip(xs, ys):
            p = 1 / (1 + math.exp(-(b + sum(wi * xi for wi, xi in zip(w, x)))))
            for j in range(k):
                gw[j] += (p - y) * x[j]
            gb += p - y
        w = [wi - lr * (g / n + l2 * wi / n) for wi, g in zip(w, gw)]
        b -= lr * gb / n
    return {"w": w, "b": b, "mean": mean, "std": std}


def predict_logistic(model: dict, f: dict) -> float:
    x = [(v - m) / s for v, m, s in zip(_ml_vector(f), model["mean"], model["std"])]
    z = model["b"] + sum(wi * xi for wi, xi in zip(model["w"], x))
    return 1 / (1 + math.exp(-z))


# ------------------------------------------------------------------ offline backend
class LocalAnalytics:
    """In-process analytics over the synthetic rows; persisted to LOCAL_DATA_DIR/analytics.json when a path is given."""

    name = "local"

    def __init__(self, path: str | None = None, seed_time: datetime | None = None):
        self.path = Path(path) if path else None
        self._lock = threading.RLock()
        self._mtime = None
        self.data: dict | None = None
        if seed_time is not None:
            self.seed(seed_time)

    # -- persistence
    def _load(self) -> dict:
        with self._lock:
            if self.path and self.path.exists():
                m = self.path.stat().st_mtime
                if self.data is None or m != self._mtime:
                    raw = json.loads(self.path.read_text())
                    self.data = self._index(_decode(raw))
                    self._mtime = m
            if self.data is None:
                self.seed()
            return self.data

    def _save(self) -> None:
        if not self.path or self.data is None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        raw = {k: v for k, v in self.data.items() if not k.startswith("_")}
        self.path.write_text(json.dumps(_encode(raw)))
        self._mtime = self.path.stat().st_mtime

    @staticmethod
    def _index(d: dict) -> dict:
        d["_accounts"] = {a["account_key"]: a for a in d["accounts"]}
        by: dict[str, list[dict]] = {}
        for t in d["txns"]:
            by.setdefault(t["account_key"], []).append(t)
        d["_txns"] = by
        return d

    # -- API
    def seed(self, seed_time: datetime | None = None, with_ml: bool = True) -> dict:
        with self._lock:
            d = synthetic.generate(seed_time or utcnow())
            d = self._index(d)
            rows = []
            for a in d["accounts"]:
                f = compute_features(d["_accounts"], d["_txns"], a["account_key"], d["seed_time"])
                rows.append((_ml_vector(f), bool(a["is_mule"])))
            d["model"] = train_logistic(rows) if with_ml else None
            self.data = d
            self._save()
            return {"accounts": len(d["accounts"]), "txns": len(d["txns"]), "case_events": len(d["case_events"]),
                    "seed_time": to_iso(d["seed_time"])}

    def features(self, account_key: str, now: datetime) -> dict | None:
        d = self._load()
        return compute_features(d["_accounts"], d["_txns"], account_key, now)

    def insert_case_event(self, event: dict) -> None:
        with self._lock:
            d = self._load()
            if any(e["event_id"] == event["event_id"] for e in d["case_events"]):
                return
            d["case_events"].append(dict(event))
            self._save()

    def case_events(self) -> list[dict]:
        return list(self._load()["case_events"])

    def scam_intelligence(self, now: datetime) -> dict:
        now = ensure_utc(now)
        ev = self._load()["case_events"]
        recent = [e for e in ev if now - timedelta(days=30) <= e["event_time"] <= now]
        by_type: dict[str, set] = {}
        for e in recent:
            by_type.setdefault(e.get("scam_type") or "other", set()).add(e["case_id"])
        reps: dict[str, dict] = {}
        for e in ev:
            h = e.get("beneficiary_hash")
            if not h:
                continue
            r = reps.setdefault(h, {"beneficiary_hash": h, "_cases": set(), "_countries": set(), "first_seen": e["event_time"], "last_seen": e["event_time"]})
            r["_cases"].add(e["case_id"])
            r["_countries"].add(e["country"])
            r["first_seen"] = min(r["first_seen"], e["event_time"])
            r["last_seen"] = max(r["last_seen"], e["event_time"])
        repeat = [{"beneficiary_hash": r["beneficiary_hash"], "cases": len(r["_cases"]), "countries": ",".join(sorted(r["_countries"])),
                   "first_seen": r["first_seen"], "last_seen": r["last_seen"]} for r in reps.values() if len(r["_cases"]) >= 2]
        repeat.sort(key=lambda r: (-r["cases"], -r["last_seen"].timestamp()))
        days: dict[tuple, dict] = {}
        for e in recent:
            if e["event_type"] != "case_confirmed":
                continue
            k = (e["country"], e["event_time"].date())
            r = days.setdefault(k, {"country": k[0], "day": k[1], "_cases": set(), "amount": 0, "currency": e.get("currency")})
            r["_cases"].add(e["case_id"])
            r["amount"] += e.get("amount") or 0
        return {
            "by_scam_type": sorted(({"scam_type": k, "cases": len(v)} for k, v in by_type.items()), key=lambda r: (-r["cases"], r["scam_type"])),
            "repeat_beneficiaries": repeat[:20],
            "by_country_day": [{"country": r["country"], "day": r["day"], "cases": len(r["_cases"]), "amount": r["amount"], "currency": r["currency"]}
                               for r in sorted(days.values(), key=lambda r: (r["day"], r["country"]))],
        }

    def ml_score(self, features: dict) -> float | None:
        model = self._load().get("model")
        return round(predict_logistic(model, features), 3) if model else None


def _encode(o: Any) -> Any:
    if isinstance(o, datetime):
        return {"$t": to_iso(o)}
    if isinstance(o, dict):
        return {k: _encode(v) for k, v in o.items()}
    if isinstance(o, list):
        return [_encode(v) for v in o]
    return o


def _decode(o: Any) -> Any:
    if isinstance(o, dict):
        if set(o) == {"$t"}:
            return parse_iso(o["$t"])
        return {k: _decode(v) for k, v in o.items()}
    if isinstance(o, list):
        return [_decode(v) for v in o]
    return o


# ------------------------------------------------------------------ BigQuery backend
class BigQueryAnalytics:
    name = "bigquery"

    def __init__(self, project: str | None = None, dataset: str = "recoverai_analytics", location: str | None = None,
                 timeout_s: float = 10.0):
        from google.cloud import bigquery

        self.bq = bigquery
        self.client = bigquery.Client(project=project or None, location=location or None)
        self.dataset = dataset
        self.timeout_s = timeout_s

    def _table(self, name: str) -> str:
        return f"{self.client.project}.{self.dataset}.{name}"

    def _query(self, sql: str, params: list) -> list[dict]:
        cfg = self.bq.QueryJobConfig(query_parameters=params, use_query_cache=False)
        job = self.client.query(sql, job_config=cfg, timeout=self.timeout_s)
        return [{k: _num(v) for k, v in dict(r).items()} for r in job.result(timeout=self.timeout_s)]

    def features(self, account_key: str, now: datetime) -> dict | None:
        P = self.bq.ScalarQueryParameter
        rows = self._query(load_sql("features", self.dataset),
                           [P("acct", "STRING", account_key), P("now", "TIMESTAMP", ensure_utc(now))])
        if not rows or not rows[0].get("account_found"):
            return None
        r = rows[0]
        r["account_found"] = True
        return r

    def insert_case_event(self, event: dict) -> None:
        row = {k: (to_iso(v) if isinstance(v, datetime) else v) for k, v in event.items()}
        errors = self.client.insert_rows_json(self._table("case_events"), [row], row_ids=[event["event_id"]])
        if errors:
            raise AnalyticsError(f"case_events insert failed: {errors}")

    def scam_intelligence(self, now: datetime) -> dict:
        P = self.bq.ScalarQueryParameter
        out = {}
        for name, sql in sql_sections(load_sql("scam_intel", self.dataset)).items():
            params = [P("now", "TIMESTAMP", ensure_utc(now))] if "@now" in sql else []
            out[name] = self._query(sql, params)
        return out

    def ml_score(self, features: dict) -> float | None:
        P = self.bq.ScalarQueryParameter
        params = [P("account_age_days", "FLOAT64", float(features.get("account_age_days") or 0)),
                  P("credits_24h", "FLOAT64", float(features.get("credits_24h") or 0)),
                  P("distinct_senders_24h", "FLOAT64", float(features.get("distinct_senders_24h") or 0)),
                  P("outflow_60m_pct", "FLOAT64", float(features.get("outflow_60m_pct") or 0)),
                  P("credit_ratio_vs_avg", "FLOAT64", float(features.get("credit_ratio_vs_avg") or 0))]
        rows = self._query(load_sql("ml_predict", self.dataset), params)
        return round(float(rows[0]["mule_probability"]), 3) if rows else None

    def seed(self, seed_time: datetime | None = None, with_ml: bool = True) -> dict:
        d = synthetic.generate(seed_time or utcnow())

        def load(table: str, rows: list[dict], cols: tuple[str, ...] | None = None) -> None:
            tbl = self.client.get_table(self._table(table))
            payload = [{k: (to_iso(v) if isinstance(v, datetime) else v) for k, v in r.items() if cols is None or k in cols} for r in rows]
            cfg = self.bq.LoadJobConfig(schema=tbl.schema, write_disposition="WRITE_TRUNCATE",
                                        source_format=self.bq.SourceFormat.NEWLINE_DELIMITED_JSON)
            self.client.load_table_from_json(payload, tbl, job_config=cfg).result(timeout=120)

        load("bank_accounts", d["accounts"], ACCOUNT_COLUMNS)
        load("bank_txn", d["txns"])
        load("case_events", d["case_events"])
        if with_ml:
            P = self.bq.ScalarQueryParameter
            self.client.query(load_sql("account_features", self.dataset),
                              job_config=self.bq.QueryJobConfig(query_parameters=[P("now", "TIMESTAMP", d["seed_time"])])).result(timeout=300)
            self.client.query(load_sql("ml_model", self.dataset)).result(timeout=600)
        return {"accounts": len(d["accounts"]), "txns": len(d["txns"]), "case_events": len(d["case_events"]),
                "seed_time": to_iso(d["seed_time"]), "ml_model": with_ml}


# ------------------------------------------------------------------ selection + resilient helpers
_analytics: Analytics | None = None


def get_analytics() -> Analytics:
    global _analytics
    if _analytics is None:
        s = get_settings()
        if s.effective_analytics_backend == "bigquery":
            _analytics = BigQueryAnalytics(s.project_id or None, s.bq_dataset, s.bq_location or None)
        else:
            path = None if s.local_data_dir in ("", ":memory:") else str(Path(s.local_data_dir) / "analytics.json")
            _analytics = LocalAnalytics(path)
    return _analytics


def set_analytics(a: Analytics | None) -> None:
    global _analytics
    _analytics = a


def beneficiary_features(account_key: str | None, now: datetime) -> dict:
    """Never raises: returns {"status": ok|not_found|unavailable, "features": {...}|None, "queryMs", "source"}."""
    if not account_key:
        return {"status": "not_found", "features": None, "queryMs": 0, "source": None}
    a = get_analytics()
    t0 = time.perf_counter()
    try:
        f = a.features(account_key, now)
    except Exception as e:  # noqa: BLE001 - F14 AC: a BigQuery failure must not block the bank case
        log.warning("feature query failed", extra={"step": "bq_features", "err": str(e)[:300]})
        return {"status": "unavailable", "features": None, "queryMs": int((time.perf_counter() - t0) * 1000), "source": a.name}
    ms = int((time.perf_counter() - t0) * 1000)
    log.info("feature query", extra={"step": "bq_features", "latencyMs": ms, "found": f is not None, "source": a.name})
    return {"status": "ok" if f else "not_found", "features": f, "queryMs": ms, "source": a.name}


def safe_ml_score(features: dict | None) -> float | None:
    if not features or not get_settings().enable_ml_score:
        return None
    try:
        return get_analytics().ml_score(features)
    except Exception as e:  # noqa: BLE001 - advisory only
        log.warning("ML.PREDICT failed", extra={"step": "bq_ml", "err": str(e)[:300]})
        return None


def record_case_event(event: dict) -> None:
    try:
        get_analytics().insert_case_event(event)
    except Exception as e:  # noqa: BLE001 - analytics must never break the victim or bank flow
        log.warning("case_events insert failed", extra={"step": "bq_insert", "err": str(e)[:300], "eventId": event.get("event_id")})


def run_queries(now: datetime | None = None) -> dict:
    return get_analytics().scam_intelligence(now or utcnow())
