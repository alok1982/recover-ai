#!/usr/bin/env python3
"""Delete leftover QA throw-away logins (+91 90000 011xx only) with the operator's gcloud ADC (Identity Toolkit admin API).
Refuses any other number. Usage: cleanup_logins.py 919000001101 919000001102 ..."""
import subprocess
import sys

import httpx

P = "recoverai-511917"
tok = subprocess.run(["/home/box/tools/google-cloud-sdk/bin/gcloud", "auth", "application-default", "print-access-token"],
                     capture_output=True, text=True, check=True).stdout.strip()
H = {"Authorization": f"Bearer {tok}", "x-goog-user-project": P}
B = f"https://identitytoolkit.googleapis.com/v1/projects/{P}"
for d in sys.argv[1:]:
    if not d.startswith("9190000011"):
        print("refusing", d)
        continue
    r = httpx.post(f"{B}/accounts:lookup", json={"email": [f"{d}@phone.recoverai.app"]}, headers=H, timeout=30).json()
    for u in r.get("users") or []:
        x = httpx.post(f"{B}/accounts:delete", json={"localId": u["localId"]}, headers=H, timeout=30)
        print("deleted login", d[:-4] + "xxxx", x.status_code)
    if not r.get("users"):
        print("no login", d[:-4] + "xxxx")
