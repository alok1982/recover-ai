#!/usr/bin/env python3
"""One-off, idempotent: move bank cases created before CR-01 (no `sandbox` field) into the sandbox.

For each bank case: bank_cases.sandbox=true (+ sandboxMigratedAt), the victim case (if it still exists)
sandbox=true + sandboxLocked=true, case_events.sandbox=TRUE in BigQuery, and one SANDBOX_MIGRATED audit entry.
Re-running changes nothing (cases already migrated are skipped; the BigQuery UPDATE only touches non-TRUE rows).

  GOOGLE_CLOUD_PROJECT=recoverai-511917 python scripts/migrate_legacy_to_sandbox.py            # dry run
  GOOGLE_CLOUD_PROJECT=recoverai-511917 python scripts/migrate_legacy_to_sandbox.py --apply    # write
"""
import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))
os.environ.setdefault("MOCK_MODE", "false")  # FirestoreStore

from app.store import get_store  # noqa: E402
from app.timeutil import utcnow  # noqa: E402

LEGACY = ["b_0a72f91f6ae8bc550e8c78bf", "b_4064f47e383036d835620b0d", "b_fce8288f6bbe8bdde8de1d4a",
          "b_c282a9bac4592769a3913358", "b_64a67190a739f71b1f127f7f", "b_332b54452ea39d935b328039",
          "b_8da42cc7f71fe6c2f4c7636f"]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="write changes (default: dry run)")
    ap.add_argument("--dataset", default=os.environ.get("BQ_DATASET", "recoverai_analytics"))
    ap.add_argument("ids", nargs="*", default=LEGACY)
    a = ap.parse_args()
    project = os.environ["GOOGLE_CLOUD_PROJECT"]
    store = get_store()
    case_ids = []
    for bid in a.ids:
        bc = store.get_bank_case(bid)
        if not bc:
            print(f"{bid}: not found — skipped")
            continue
        cid = bc.get("caseId")
        case_ids.append(cid)
        victim = store.get_case(cid) if cid else None
        done = bc.get("sandbox") is True and bc.get("sandboxMigratedAt")
        print(f"{bid}: status={bc.get('status')} sandbox={bc.get('sandbox')} victim={cid} "
              f"({'exists' if victim else 'deleted'}){' — already migrated' if done else ''}")
        if done or not a.apply:
            continue
        now = utcnow()
        store.update_bank_case(bid, {"sandbox": True, "sandboxMigratedAt": now})
        if victim and not (victim.get("sandbox") is True and victim.get("sandboxLocked") is True):
            store.update_case(cid, {"sandbox": True, "sandboxLocked": True})
        store.add_audit({"actor": "recoverai.migration", "action": "SANDBOX_MIGRATED", "bankCaseId": bid, "caseId": cid,
                         "details": {"reason": "Created before CR-01 (no sandbox flag); demo/test data moved to the sandbox",
                                     "victimCaseUpdated": bool(victim)}, "at": now})
        print(f"  → migrated (audit SANDBOX_MIGRATED)")
    from google.cloud import bigquery

    bq = bigquery.Client(project=project)
    table = f"`{project}.{a.dataset}.case_events`"
    params = [bigquery.ArrayQueryParameter("ids", "STRING", [c for c in case_ids if c])]
    cnt = list(bq.query(f"SELECT COUNTIF(sandbox IS NOT TRUE) n, COUNT(*) total FROM {table} WHERE case_id IN UNNEST(@ids)",
                        job_config=bigquery.QueryJobConfig(query_parameters=params)).result())[0]
    print(f"case_events: {cnt.total} row(s) for these cases, {cnt.n} not yet sandbox")
    if a.apply and cnt.n:
        job = bq.query(f"UPDATE {table} SET sandbox = TRUE WHERE case_id IN UNNEST(@ids) AND sandbox IS NOT TRUE",
                       job_config=bigquery.QueryJobConfig(query_parameters=params))
        job.result()
        print(f"  → case_events updated: {job.num_dml_affected_rows} row(s)")
    if not a.apply:
        print("dry run — re-run with --apply to write")


if __name__ == "__main__":
    main()
