#!/usr/bin/env python3
"""CR-04: create/update the seeded admin (admin@recoverai-demo.example) with the custom claim role=admin.

Run from the box with your gcloud ADC (setting claims needs Firebase Auth admin rights; Cloud Run never runs this):
    GOOGLE_CLOUD_PROJECT=<id> python scripts/create_admin.py
The password is generated once into the git-ignored deploy/.state/admin_password and never printed.
Re-running keeps that password (and re-applies it and the claim)."""
import os
import secrets
import string
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATE = ROOT / "deploy" / ".state"
EMAIL = os.environ.get("ADMIN_EMAIL", "admin@recoverai-demo.example")
NAME = "Demo Admin"


def password() -> str:
    f = STATE / "admin_password"
    if not f.exists():
        STATE.mkdir(parents=True, exist_ok=True)
        alphabet = string.ascii_letters + string.digits
        pw = "".join(secrets.choice(alphabet) for _ in range(20)) + "9a"  # letters + digits (password rule)
        f.write_text(pw + "\n")
        f.chmod(0o600)
    return f.read_text().strip()


def main() -> None:
    import firebase_admin
    from firebase_admin import auth

    project = os.environ.get("GOOGLE_CLOUD_PROJECT")
    firebase_admin.initialize_app(options={"projectId": project} if project else None)
    pw = password()
    try:
        u = auth.get_user_by_email(EMAIL)
        auth.update_user(u.uid, password=pw, display_name=NAME, email_verified=True, disabled=False)
        action = "updated"
    except auth.UserNotFoundError:
        u = auth.create_user(email=EMAIL, password=pw, display_name=NAME, email_verified=True)
        action = "created"
    auth.set_custom_user_claims(u.uid, {"role": "admin", "name": NAME})
    print(f"{action} admin {EMAIL} (uid {u.uid}) with claim role=admin; password in deploy/.state/admin_password")


if __name__ == "__main__":
    sys.exit(main())
