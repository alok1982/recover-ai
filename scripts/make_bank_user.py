#!/usr/bin/env python3
"""Create/update the demo bank analyst (email+password) and set the custom claim role=bank.

  GOOGLE_CLOUD_PROJECT=<id> BANK_USER_EMAIL=... BANK_USER_PASSWORD=... python scripts/make_bank_user.py
The password is read from the environment only (deploy.sh keeps it in the git-ignored deploy/.state/).
"""
import os
import sys

import firebase_admin
from firebase_admin import auth


def main() -> None:
    email = os.environ.get("BANK_USER_EMAIL")
    password = os.environ.get("BANK_USER_PASSWORD")
    name = os.environ.get("BANK_USER_NAME", "Demo Analyst")
    if not email or not password:
        sys.exit("BANK_USER_EMAIL and BANK_USER_PASSWORD are required")
    project = os.environ.get("GOOGLE_CLOUD_PROJECT")
    firebase_admin.initialize_app(options={"projectId": project} if project else None)
    try:
        user = auth.get_user_by_email(email)
        auth.update_user(user.uid, password=password, display_name=name, email_verified=True, disabled=False)
        action = "updated"
    except auth.UserNotFoundError:
        user = auth.create_user(email=email, password=password, display_name=name, email_verified=True)
        action = "created"
    auth.set_custom_user_claims(user.uid, {"role": "bank", "name": name})
    print(f"{action} bank analyst {email} (uid {user.uid}) with claim role=bank")


if __name__ == "__main__":
    main()
