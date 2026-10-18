"""F14 BigQuery analytics: synthetic data (§12.3), SQL ↔ Python parity on DuckDB, Scam intelligence, S2 ML score."""
import re
from datetime import datetime, timedelta, timezone

import pytest

from app.analytics import bq, synthetic
from app.analytics.bq import LocalAnalytics, load_sql, sql_sections

NOW = datetime(2026, 10, 17, 9, 0, tzinfo=timezone.utc)
DEMO = ("cbi.verify.desk@okdemo", "514012345678")


@pytest.fixture(scope="module")
def local():
    return LocalAnalytics(None, seed_time=NOW)


def test_synthetic_dataset_shape(local):
    d = local.data
    roles = [a["role"] for a in d["accounts"]]
    assert len(d["accounts"]) == 40 and roles.count("demo") == 2 and roles.count("mule_like") == 8
    assert sum(not a["is_mule"] for a in d["accounts"]) == 30 and roles.count("contrast") == 2
    assert 2500 <= len(d["txns"]) <= 3500
    assert len(d["case_events"]) == 50
    assert synthetic.generate(NOW)["txns"] == d["txns"]  # deterministic for a given seed time
    keys = {a["account_key"] for a in d["accounts"]}
    assert len(keys) == 40 and all(t["account_key"] in keys for t in d["txns"])


@pytest.mark.parametrize("key", DEMO)
def test_demo_beneficiaries_produce_prd_signal_values(local, key):
    f = local.features(key, NOW)
    assert f["account_age_days"] == 21 and f["credits_24h"] == 9 and f["distinct_senders_24h"] == 9
    assert 81.5 <= f["outflow_60m_pct"] <= 82.5 and f["declared_profile"] == "student" and f["credit_ratio_vs_avg"] > 10


def test_demo_values_hold_for_the_whole_demo_day(local):
    later = local.features(DEMO[0], NOW + timedelta(hours=22))
    assert later["credits_24h"] == 9 and later["outflow_60m_pct"] >= 70


def test_unknown_account_is_none(local):
    assert local.features("nobody@okdemo", NOW) is None


def test_beneficiary_hash_is_sha256_of_normalised_key():
    h = synthetic.beneficiary_hash(" CBI.Verify.Desk@okdemo ")
    assert re.fullmatch(r"[0-9a-f]{64}", h) and h == synthetic.beneficiary_hash("cbi.verify.desk@okdemo")
    assert "cbi" not in h


# ---------------------------------------------------------------- SQL ↔ Python parity (BigQuery SQL run on DuckDB)
duckdb = pytest.importorskip("duckdb")
sqlglot = pytest.importorskip("sqlglot")


def _bind(sql: str, params: dict) -> str:
    sql = re.sub(r"--[^\n]*", "", sql)

    def lit(m):
        v = params[m.group(1)]
        if isinstance(v, datetime):
            return f"TIMESTAMP '{v.strftime('%Y-%m-%d %H:%M:%S')}+00'"
        return f"'{v}'" if isinstance(v, str) else str(v)
    return re.sub(r"@(\w+)", lit, sql)


def _duck(sql: str, params: dict, con):
    out = sqlglot.transpile(_bind(sql, params), read="bigquery", write="duckdb")
    for stmt in out[:-1]:
        con.execute(stmt)
    cur = con.execute(out[-1])
    if cur.description is None:
        return []
    cols = [c[0] for c in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


@pytest.fixture(scope="module")
def con(local):
    c = duckdb.connect()
    c.execute("SET TimeZone='UTC'")
    c.execute("CREATE SCHEMA recoverai_analytics")
    c.execute("""CREATE TABLE recoverai_analytics.bank_accounts (account_key VARCHAR, country VARCHAR, bank VARCHAR,
        opened_at TIMESTAMPTZ, declared_profile VARCHAR, monthly_avg_credit DOUBLE, is_mule BOOLEAN, holder_name VARCHAR,
        account_type VARCHAR, currency VARCHAR, current_balance DOUBLE)""")
    c.execute("""CREATE TABLE recoverai_analytics.bank_txn (txn_id VARCHAR, account_key VARCHAR, direction VARCHAR, amount DOUBLE,
        currency VARCHAR, counterparty_key VARCHAR, txn_time TIMESTAMPTZ)""")
    c.execute("""CREATE TABLE recoverai_analytics.case_events (event_id VARCHAR, case_id VARCHAR, event_type VARCHAR, country VARCHAR,
        scam_type VARCHAR, amount DOUBLE, currency VARCHAR, beneficiary_hash VARCHAR, risk_level VARCHAR, decision VARCHAR,
        sandbox BOOLEAN, event_time TIMESTAMPTZ)""")
    d = local.data
    c.executemany("INSERT INTO recoverai_analytics.bank_accounts VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                  [[a[k] for k in bq.ACCOUNT_COLUMNS] for a in d["accounts"]])
    c.executemany("INSERT INTO recoverai_analytics.bank_txn VALUES (?,?,?,?,?,?,?)",
                  [[t[k] for k in ("txn_id", "account_key", "direction", "amount", "currency", "counterparty_key", "txn_time")] for t in d["txns"]])
    c.executemany("INSERT INTO recoverai_analytics.case_events VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                  [[e.get(k) for k in ("event_id", "case_id", "event_type", "country", "scam_type", "amount", "currency", "beneficiary_hash",
                                       "risk_level", "decision", "sandbox", "event_time")] for e in d["case_events"]])
    return c


def _close(a, b):
    if a is None or b is None:
        return a is None and b is None
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return abs(float(a) - float(b)) < 1e-6
    return a == b


@pytest.mark.parametrize("when", [NOW, NOW + timedelta(hours=7, minutes=13)])
def test_feature_sql_matches_python_for_every_account(local, con, when):
    for a in local.data["accounts"] + [{"account_key": "nobody@okdemo"}]:
        rows = _duck(load_sql("features"), {"acct": a["account_key"], "now": when}, con)
        assert len(rows) == 1
        r, f = rows[0], local.features(a["account_key"], when)
        if f is None:
            assert r["account_found"] == 0
            continue
        for k in bq.FEATURE_KEYS + ("credit_amount_24h", "declared_profile", "current_balance"):
            assert _close(r[k], f[k]), (a["account_key"], k, r[k], f[k])


def test_account_features_sql_matches_python(local, con):
    _duck(load_sql("account_features"), {"now": NOW}, con)
    cur = con.execute("SELECT * FROM recoverai_analytics.account_features")
    cols = [c[0] for c in cur.description]
    rows = {r[0]: dict(zip(cols, r)) for r in cur.fetchall()}
    assert len(rows) == 40
    for a in local.data["accounts"]:
        f = local.features(a["account_key"], NOW)
        for k in bq.FEATURE_KEYS:
            assert _close(float(rows[a["account_key"]][k]), float(f[k] or 0)), (a["account_key"], k)


def test_scam_intel_sql_matches_python(local, con):
    py = local.scam_intelligence(NOW)
    for name, sql in sql_sections(load_sql("scam_intel")).items():
        rows = _duck(sql, {"now": NOW}, con)
        assert len(rows) == len(py[name]), name
        for r, p in zip(rows, py[name]):
            for k, v in p.items():
                rv = r[k]
                if hasattr(rv, "isoformat") and hasattr(v, "isoformat"):
                    rv, v = rv.isoformat()[:10], v.isoformat()[:10]
                assert _close(rv, v), (name, k, rv, v)


def test_sql_files_parse_as_bigquery():
    for name in ("create_tables", "features", "scam_intel", "account_features"):
        assert sqlglot.parse(_bind(load_sql(name), {"acct": "x", "now": NOW}), read="bigquery")


# ---------------------------------------------------------------- Scam intelligence + S2
def test_scam_intelligence_panels(local):
    si = local.scam_intelligence(NOW)
    assert si["by_scam_type"] and si["by_country_day"]
    demo_hash = synthetic.beneficiary_hash(DEMO[0])
    rep = {r["beneficiary_hash"]: r for r in si["repeat_beneficiaries"]}
    assert rep[demo_hash]["cases"] >= 2  # the demo beneficiary shows as a repeat mule account
    assert {r["country"] for r in si["by_country_day"]} == {"IN", "MY"}


def test_ml_score_separates_demo_and_benign(local):
    for key in DEMO:
        assert local.ml_score(local.features(key, NOW)) > 0.8
    for a in local.data["accounts"]:
        if not a["is_mule"]:
            assert local.ml_score(local.features(a["account_key"], NOW)) < 0.3, a["account_key"]


def test_local_persistence_roundtrip(tmp_path):
    p = tmp_path / "analytics.json"
    a = LocalAnalytics(str(p), seed_time=NOW)
    a.insert_case_event({"event_id": "e1", "case_id": "c1", "event_type": "case_confirmed", "country": "IN", "scam_type": "other",
                         "amount": 1, "currency": "INR", "beneficiary_hash": None, "risk_level": None, "decision": None, "event_time": NOW})
    b = LocalAnalytics(str(p))
    assert b.features(DEMO[0], NOW)["credits_24h"] == 9
    assert any(e["event_id"] == "e1" for e in b.case_events())
    b.insert_case_event({"event_id": "e1", "case_id": "c1", "event_type": "case_confirmed", "event_time": NOW})
    assert sum(e["event_id"] == "e1" for e in b.case_events()) == 1  # idempotent on event_id


def test_sandbox_case_events_are_excluded_from_scam_intelligence(local):
    """CR-01: sandbox (test) submissions never count in the Scam intelligence panels (python mirror + SQL text)."""
    before = local.scam_intelligence(NOW)
    ev = dict(local.data["case_events"][-1])
    for i in range(3):
        local.data["case_events"].append({**ev, "event_id": f"sbx-{i}", "case_id": f"c_sbx{i}", "beneficiary_hash": "sbx-hash",
                                          "sandbox": True, "event_type": "case_confirmed", "event_time": NOW})
    after = local.scam_intelligence(NOW)
    assert after == before
    assert all("sandbox IS NOT TRUE" in sql for sql in sql_sections(load_sql("scam_intel")).values())
