#!/usr/bin/env python3
"""Idempotent migration: the bank side becomes the fictional "RecoverAI Demo Bank (fictional)" (demo-recoverai-bank).

  GOOGLE_CLOUD_PROJECT=<id> python scripts/migrate_demo_bank.py [--dry-run] [--purge-test-audit]

- bank_cases/*: receivingBankId / receivingBankName set to the demo bank.
- bank_access_requests/*: bankName → demo bank (the applicant's original choice kept in originalBankName);
  bankId → demo bank for approved/revoked requests.
- custom claims: every role=bank user (approved applicants and the seeded analyst) gets bankId=demo-recoverai-bank.
- --purge-test-audit: deletes admin_audit entries that belong to this project's own throwaway check accounts
  (cr04.ui.<hex>@demo-bank.example / cr04.e2e.<hex>@demo-bank.example), which named real banks in their bankIds.
Re-running changes nothing once migrated. Runs from the box with gcloud ADC (needs Firestore + Firebase Auth admin)."""
import argparse
import os
import re
import sys

import _path  # noqa: F401
from app.demobank import DEMO_BANK_ID, DEMO_BANK_NAME

ANALYST_EMAIL = os.environ.get("BANK_USER_EMAIL", "analyst@recoverai-demo.example")
TEST_EMAIL = re.compile(r"^cr04\.(ui|e2e)\.[0-9a-f]{8}@demo-bank\.example$")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--purge-test-audit", action="store_true")
    a = ap.parse_args()
    import firebase_admin
    from firebase_admin import auth
    from google.cloud import firestore

    project = os.environ.get("GOOGLE_CLOUD_PROJECT")
    firebase_admin.initialize_app(options={"projectId": project} if project else None)
    db = firestore.Client(project=project or None)
    out = {"bank_cases": [0, 0], "bank_access_requests": [0, 0], "claims": [0, 0], "test_audit_deleted": 0}

    for d in db.collection("bank_cases").stream():
        b = d.to_dict()
        out["bank_cases"][0] += 1
        if b.get("receivingBankId") != DEMO_BANK_ID or b.get("receivingBankName") != DEMO_BANK_NAME:
            out["bank_cases"][1] += 1
            if not a.dry_run:
                d.reference.update({"receivingBankId": DEMO_BANK_ID, "receivingBankName": DEMO_BANK_NAME})

    bank_uids = set()
    for d in db.collection("bank_access_requests").stream():
        r = d.to_dict()
        out["bank_access_requests"][0] += 1
        patch = {}
        if r.get("bankName") != DEMO_BANK_NAME:
            orig = r.get("bankOther") if r.get("bankName") == "Other" else r.get("bankName")
            patch.update({"bankName": DEMO_BANK_NAME, "bankOther": None})
            if orig and not r.get("originalBankName"):
                patch["originalBankName"] = orig
        if r.get("status") in ("APPROVED", "REVOKED") and r.get("bankId") and r.get("bankId") != DEMO_BANK_ID:
            patch["bankId"] = DEMO_BANK_ID
        if r.get("status") == "APPROVED":
            bank_uids.add(d.id)
        if patch:
            out["bank_access_requests"][1] += 1
            if not a.dry_run:
                d.reference.update(patch)

    try:
        bank_uids.add(auth.get_user_by_email(ANALYST_EMAIL).uid)
    except auth.UserNotFoundError:
        pass
    for uid in sorted(bank_uids):
        try:
            u = auth.get_user(uid)
        except auth.UserNotFoundError:
            continue
        c = dict(u.custom_claims or {})
        if c.get("role") != "bank":
            continue
        out["claims"][0] += 1
        if c.get("bankId") != DEMO_BANK_ID:
            out["claims"][1] += 1
            if not a.dry_run:
                auth.set_custom_user_claims(uid, {**c, "bankId": DEMO_BANK_ID})

    if a.purge_test_audit:
        entries = [(d.reference, d.to_dict()) for d in db.collection("admin_audit").stream()]
        test_uids = {e.get("targetUid") for _, e in entries
                     if e.get("action") == "request_submitted" and TEST_EMAIL.match(e.get("actorEmail") or "")}
        for ref, e in entries:
            if e.get("targetUid") in test_uids:
                out["test_audit_deleted"] += 1
                if not a.dry_run:
                    ref.delete()

    fmt = lambda k: f"{k}: {out[k][0]} checked, {out[k][1]} {'to update' if a.dry_run else 'updated'}"  # noqa: E731
    print(("DRY RUN — " if a.dry_run else "") + "; ".join(fmt(k) for k in ("bank_cases", "bank_access_requests", "claims"))
          + f"; test audit entries {'to delete' if a.dry_run else 'deleted'}: {out['test_audit_deleted']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
