#!/usr/bin/env python3
"""Reset demo data between runs: deletes victim cases, bank cases and audit entries, then re-seeds bank accounts.

  GOOGLE_CLOUD_PROJECT=<id> MOCK_MODE=false python scripts/reset_demo.py --yes
  MOCK_MODE=true LOCAL_DATA_DIR=.localdata python scripts/reset_demo.py --yes   # local mock store
Evidence objects in GCS expire via the bucket lifecycle rule; local blobs live under LOCAL_DATA_DIR.
"""
import argparse
import sys

import _path  # noqa: F401
from app.seed import seed_bank_accounts
from app.store import get_store


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--yes", action="store_true", help="really delete")
    ap.add_argument("--keep-victim-cases", action="store_true")
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
    seed_bank_accounts(s, force=True)
    print(f"deleted {nc} cases, {nb} bank cases, {na} audit entries; bank accounts re-seeded")


if __name__ == "__main__":
    main()
