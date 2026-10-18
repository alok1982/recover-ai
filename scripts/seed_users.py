#!/usr/bin/env python3
"""CR-03: seed the three fictional demo victims (phone + password; password Demo@2026 for all).

  live (Firebase Auth + Firestore users/{uid}, ADC):
      GOOGLE_CLOUD_PROJECT=<id> python scripts/seed_users.py
  local mock backend (AUTH_MODE=mock):
      python scripts/seed_users.py --api http://localhost:8080

Re-running resets the three profiles to the states below (00002 stays incomplete to show the gate). Cases are untouched.

CR-04: also seeds one PENDING bank-staff applicant (pending.applicant@demo-bank.example, same demo password) so the
admin queue is not empty. `--applicant-only` seeds just that (victim profiles untouched).
"""
import argparse
import os
import sys

import _path  # noqa: F401
import httpx

from app import profile as P
from app.timeutil import utcnow

PASSWORD = "Demo@2026"  # fictional demo accounts, published in CR-03
USERS = [
    {"phone": "+91 90000 00001", "country": "IN", "profile": {
        "fullName": "Asha Verma", "country": "IN", "language": "hi", "state": "Uttar Pradesh", "district": "Lucknow",
        "postalCode": "226001", "primaryBank": "State Bank of India", "addressLine": "12 Hazratganj"}},
    {"phone": "+91 90000 00002", "country": "IN", "profile": {
        "fullName": "Ravi Kumar", "country": "IN", "language": "hi", "state": "Uttar Pradesh", "district": "Kanpur",
        "postalCode": "", "primaryBank": ""}},  # missing PIN code and bank
    {"phone": "+60 10000 0001", "country": "MY", "profile": {
        "fullName": "Aiman Rahman", "country": "MY", "language": "en", "state": "Selangor", "district": "Petaling Jaya",
        "postalCode": "46000", "primaryBank": "Maybank"}},
]


APPLICANT = {"email": "pending.applicant@demo-bank.example", "fullName": "Kavya Menon", "country": "IN",
             "bankName": "ICICI Bank", "employeeId": "ICI-55821", "designation": "Fraud risk officer",
             "note": "Demo applicant (fictional) — Chennai fraud operations"}


def applicant_api(base: str) -> None:
    h = {"Authorization": f"Bearer mock:staff:{APPLICANT['email']}"}
    body = {k: v for k, v in APPLICANT.items() if k != "email"}
    r = httpx.post(f"{base}/api/bank-access/request", json=body, headers=h, timeout=20)
    r.raise_for_status()
    print(f"applicant {APPLICANT['email']}: {r.json()['status']}")


def applicant_live() -> None:
    import firebase_admin
    from firebase_admin import auth
    from google.cloud import firestore

    project = os.environ.get("GOOGLE_CLOUD_PROJECT")
    if not firebase_admin._apps:
        firebase_admin.initialize_app(options={"projectId": project} if project else None)
    db = firestore.Client(project=project or None)
    try:
        rec = auth.get_user_by_email(APPLICANT["email"])
        auth.update_user(rec.uid, password=PASSWORD, display_name=APPLICANT["fullName"], disabled=False)
    except auth.UserNotFoundError:
        rec = auth.create_user(email=APPLICANT["email"], password=PASSWORD, display_name=APPLICANT["fullName"])
    auth.set_custom_user_claims(rec.uid, None)  # never a bank role until an admin approves
    now = utcnow()
    db.collection("bank_access_requests").document(rec.uid).set({
        "id": rec.uid, "uid": rec.uid, "email": APPLICANT["email"], "fullName": APPLICANT["fullName"],
        "country": APPLICANT["country"], "bankName": APPLICANT["bankName"], "bankOther": None,
        "employeeId": APPLICANT["employeeId"], "designation": APPLICANT["designation"], "note": APPLICANT["note"],
        "status": "PENDING", "createdAt": now, "updatedAt": now, "decidedBy": None, "decidedAt": None, "reason": None,
        "bankId": None, "seed": True})
    print(f"applicant {APPLICANT['email']} (uid {rec.uid}): PENDING")


def via_api(base: str) -> None:
    for u in USERS:
        e164 = P.normalize_phone(u["phone"], u["country"])
        h = {"Authorization": f"Bearer mock:phone:{e164}"}
        httpx.post(f"{base}/api/me/terms", json={"version": P.TERMS_VERSION}, headers=h, timeout=20).raise_for_status()
        r = httpx.put(f"{base}/api/me/profile", json={"profile": u["profile"]}, headers=h, timeout=20)
        r.raise_for_status()
        print(f"{u['phone']}: mock uid ph-{e164[1:]} · profile {r.json()['profileStatus']}")


def live() -> None:
    import firebase_admin
    from firebase_admin import auth
    from google.cloud import firestore

    project = os.environ.get("GOOGLE_CLOUD_PROJECT")
    firebase_admin.initialize_app(options={"projectId": project} if project else None)
    db = firestore.Client(project=project or None)
    for u in USERS:
        e164 = P.normalize_phone(u["phone"], u["country"])
        email = P.phone_email(e164)
        name = u["profile"]["fullName"]
        try:
            rec = auth.get_user_by_email(email)
            auth.update_user(rec.uid, password=PASSWORD, display_name=name, disabled=False)
            action = "updated"
        except auth.UserNotFoundError:
            rec = auth.create_user(email=email, password=PASSWORD, display_name=name)
            action = "created"
        prof = {k: v for k, v in u["profile"].items() if v}
        ref = db.collection("users").document(rec.uid)
        old = ref.get()
        created = (old.to_dict() or {}).get("createdAt") if old.exists else None
        ref.set({"uid": rec.uid, "phoneE164": e164, "phoneVerified": False, "createdAt": created or utcnow(),
                 "termsAcceptedAt": utcnow(), "termsVersion": P.TERMS_VERSION, "profile": prof,
                 "profileStatus": P.compute_status(prof), "profileUpdatedAt": utcnow(), "seed": True})
        print(f"{action} {u['phone']} (uid {rec.uid}) · profile {P.compute_status(prof)}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--api", help="seed a local mock backend through its API instead of Firebase")
    ap.add_argument("--applicant-only", action="store_true", help="CR-04: seed only the pending bank applicant")
    a = ap.parse_args()
    if a.api:
        if not a.applicant_only:
            via_api(a.api.rstrip("/"))
        applicant_api(a.api.rstrip("/"))
    else:
        if not a.applicant_only:
            live()
        applicant_live()


if __name__ == "__main__":
    sys.exit(main())
