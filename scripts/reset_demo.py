#!/usr/bin/env python3
"""Reset demo data before recording / judging: delete victim cases, bank cases, audit entries and Pub/Sub dedupe
records in Firestore, then re-seed the BigQuery synthetic bank data (fresh timestamps) and case_events.

  GOOGLE_CLOUD_PROJECT=recoverai-511917 MOCK_MODE=false ANALYTICS_BACKEND=bigquery BQ_LOCATION=asia-south1 \\
      python scripts/reset_demo.py --yes
  MOCK_MODE=true LOCAL_DATA_DIR=backend/.localdata python scripts/reset_demo.py --yes   # local mock store
Evidence objects in GCS expire via the bucket lifecycle rule; local blobs live under LOCAL_DATA_DIR.
"""
import argparse
import sys

import _path  # noqa: F401
from app.seed import seed_bank_data
from app.store import get_store


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--yes", action="store_true", help="really delete")
    ap.add_argument("--keep-victim-cases", action="store_true")
    ap.add_argument("--no-ml", action="store_true")
    a = ap.parse_args()
    if not a.yes:
        sys.exit("refusing to delete without --yes")
    s = get_store()
    nc = 0
    if not a.keep_victim_cases:
        for c in s.list_cases():
            s.delete_case(c["id"])
            nc += 1
    nb = 0
    for b in s.list_bank_cases(limit=1000):
        s.delete_bank_case(b["id"])
        nb += 1
    na = 0
    for x in s.list_audit():
        s.delete_audit(x["id"])
        na += 1
    npe = s.delete_processed_events()
    stats = seed_bank_data(with_ml=not a.no_ml)
    print(f"deleted {nc} cases, {nb} bank cases, {na} audit entries, {npe} processed events; re-seeded bank data: {stats}")


if __name__ == "__main__":
    main()
