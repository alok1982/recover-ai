#!/usr/bin/env python3
"""Move a victim's cases from one Firebase account to another (e.g. cases started under a pre-CR-03 anonymous
session, which victim routes no longer accept, onto the person's new phone + password account).

Authorization for cases is a single field, cases/{id}.ownerUid (backend get_owned_case, list_cases and the Firestore
rules). Messages and evidence live in subcollections keyed by case id, evidence blobs live under
gs://…/cases/{caseId}/…, and co-pilot history is replayed from cases/{id}/messages — none of them carry the uid, so
only ownerUid changes. bank_cases do not reference the victim uid. Nothing is deleted; the old account is kept.
Each moved case gets previousOwnerUid + ownerReassignedAt for traceability. Idempotent (already-moved cases skip).

  # dry run (default): show what would move
  GOOGLE_CLOUD_PROJECT=<id> python scripts/reassign_cases.py --case c_123 --to-phone "+91 98xxxxxxxx"
  # create the phone account first if missing (normal signup shape; password from $NEW_ACCOUNT_PASSWORD or prompt)
  ... --create-account --full-name "Name" --language en --apply

Source owner: --from-uid <uid>, or --case <caseId> (its current owner). Target: --to-uid <uid> or --to-phone.
"""
import argparse
import getpass
import os
import sys
from datetime import datetime, timedelta, timezone

import _path  # noqa: F401

from app import profile as P
from app.timeutil import utcnow

IST = timezone(timedelta(hours=5, minutes=30))


def ist(ts) -> str:
    return ts.astimezone(IST).strftime("%d %b %Y %H:%M IST") if ts else "-"


def create_phone_account(auth, db, e164: str, full_name: str, language: str, apply: bool) -> str | None:
    """Same records the web signup produces: Firebase Email/Password user on the synthetic email, users/{uid} with
    phoneVerified false, terms accepted (current version) and profile {fullName, country, language}."""
    email = P.phone_email(e164)
    try:
        rec = auth.get_user_by_email(email)
        print(f"account exists: {email} uid={rec.uid} (password NOT changed)")
        return rec.uid
    except auth.UserNotFoundError:
        pass
    if not apply:
        print(f"[dry-run] would create {email}")
        return None
    pw = os.environ.get("NEW_ACCOUNT_PASSWORD") or getpass.getpass("password for the new account: ")
    if len(pw) < 8 or not any(c.isalpha() for c in pw) or not any(c.isdigit() for c in pw):
        sys.exit("password must be 8+ chars with a letter and a digit (signup rule)")
    rec = auth.create_user(email=email, password=pw)
    country = P.country_of_phone(e164)
    prof = {"fullName": full_name, "country": country, "language": language}
    now = utcnow()
    db.collection("users").document(rec.uid).set({
        "uid": rec.uid, "phoneE164": e164, "phoneVerified": False, "createdAt": now, "termsAcceptedAt": now,
        "termsVersion": P.TERMS_VERSION, "profile": prof, "profileStatus": P.compute_status(prof), "profileUpdatedAt": now})
    print(f"created {email} uid={rec.uid}")
    return rec.uid


def main() -> None:
    ap = argparse.ArgumentParser()
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--from-uid")
    src.add_argument("--case", help="use this case's current owner as the source account")
    dst = ap.add_mutually_exclusive_group(required=True)
    dst.add_argument("--to-uid")
    dst.add_argument("--to-phone")
    ap.add_argument("--country", default="IN")
    ap.add_argument("--create-account", action="store_true", help="create the --to-phone account if it does not exist")
    ap.add_argument("--full-name", default="")
    ap.add_argument("--language", default="en")
    ap.add_argument("--apply", action="store_true", help="write changes (default is a dry run)")
    a = ap.parse_args()

    import firebase_admin
    from firebase_admin import auth
    from google.cloud import firestore

    project = os.environ.get("GOOGLE_CLOUD_PROJECT")
    firebase_admin.initialize_app(options={"projectId": project} if project else None)
    db = firestore.Client(project=project or None)

    old = a.from_uid
    if a.case:
        snap = db.collection("cases").document(a.case).get()
        if not snap.exists:
            sys.exit(f"case {a.case} not found")
        old = snap.to_dict().get("ownerUid")
        prev = snap.to_dict().get("previousOwnerUid")
        print(f"case {a.case} ownerUid={old}" + (f" (previousOwnerUid={prev})" if prev else ""))
    try:
        o = auth.get_user(old)
        kind = "anonymous" if not o.provider_data and not o.email else (o.email or "provider account")
        print(f"source account {old}: {kind}, created {ist(datetime.fromtimestamp(o.user_metadata.creation_timestamp / 1000, timezone.utc))}")
    except auth.UserNotFoundError:
        print(f"source account {old}: not in Firebase Auth")

    new = a.to_uid
    if a.to_phone:
        e164 = P.normalize_phone(a.to_phone, a.country)
        if not e164:
            sys.exit(f"invalid phone {a.to_phone}")
        if a.create_account:
            if not a.full_name:
                sys.exit("--full-name is required with --create-account")
            new = create_phone_account(auth, db, e164, a.full_name, a.language, a.apply)
        else:
            try:
                new = auth.get_user_by_email(P.phone_email(e164)).uid
            except auth.UserNotFoundError:
                sys.exit(f"no account for {P.phone_email(e164)} (use --create-account)")
    if new and new == old:
        sys.exit("source and target are the same account")

    q = db.collection("cases").where(filter=firestore.FieldFilter("ownerUid", "==", old))
    cases = sorted(q.stream(), key=lambda s: s.to_dict().get("createdAt"))
    already = list(db.collection("cases").where(filter=firestore.FieldFilter("previousOwnerUid", "==", old)).stream())
    print(f"\n{len(cases)} case(s) owned by {old}; {len(already)} already moved earlier")
    for s in cases:
        d = s.to_dict()
        msgs = sum(1 for _ in s.reference.collection("messages").stream())
        ev = sum(1 for _ in s.reference.collection("evidence").stream())
        stray = [k for k, v in d.items() if k != "ownerUid" and old in repr(v)]
        print(f"  {s.id}  {ist(d.get('createdAt'))}  status={d.get('status')}  ref={d.get('publicRef')}  "
              f"sandbox={d.get('sandbox')}  messages={msgs} evidence={ev}" + (f"  WARN uid also in {stray}" if stray else ""))
        if a.apply and new:
            s.reference.update({"ownerUid": new, "previousOwnerUid": old, "ownerReassignedAt": utcnow()})
            print(f"    → moved to {new}")
    if not a.apply:
        print("\n[dry-run] nothing written; re-run with --apply")


if __name__ == "__main__":
    sys.exit(main())
