#!/usr/bin/env python3
"""Drive both PRD §4 storylines (India + Malaysia) and the bank side end-to-end over HTTP.

Local mock stack:   python scripts/e2e_demo.py --mock --api http://localhost:8080
Deployed stack:     API_BASE=$(cat deploy/.state/run_url) python scripts/e2e_demo.py
  (anonymous victim sign-in + analyst password sign-in via the Firebase Auth REST API, using
   deploy/.state/sdkconfig.json and deploy/.state/bank_password written by deploy/deploy.sh)
Exits non-zero on the first failed check. DEMO_MODE must be on for the time-travel step.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import uuid
from pathlib import Path
from urllib.parse import urljoin

import httpx

ROOT = Path(__file__).resolve().parent.parent
FIX = ROOT / "fixtures"
STATE = ROOT / "deploy" / ".state"
IDT = "https://identitytoolkit.googleapis.com/v1/accounts"


def check(cond: bool, what: str) -> None:
    print(("  ✔ " if cond else "  ✘ ") + what)
    if not cond:
        sys.exit(1)


class Api:
    def __init__(self, base: str, token: str):
        self.base = base.rstrip("/")
        self.c = httpx.Client(timeout=120, headers={"Authorization": f"Bearer {token}"})

    def url(self, p: str) -> str:
        return urljoin(self.base + "/", p.lstrip("/")) if not p.startswith("http") else p

    def get(self, p):
        r = self.c.get(self.url(p))
        r.raise_for_status()
        return r.json()

    def post(self, p, body=None):
        r = self.c.post(self.url(p), json=body or {})
        if r.status_code >= 400:
            raise SystemExit(f"POST {p} -> {r.status_code}: {r.text[:300]}")
        return r.json()

    def patch(self, p, body):
        r = self.c.patch(self.url(p), json=body)
        r.raise_for_status()
        return r.json()

    def chat(self, cid, body) -> list[dict]:
        evs = []
        with self.c.stream("POST", self.url(f"/api/cases/{cid}/chat"), json=body) as r:
            r.raise_for_status()
            for line in r.iter_lines():
                if line.startswith("data: "):
                    evs.append(json.loads(line[6:]))
        return evs

    def upload(self, cid, fname, mime):
        data = (FIX / fname).read_bytes()
        u = self.post(f"/api/cases/{cid}/evidence/upload-url", {"mimeType": mime, "sizeBytes": len(data)})
        put_headers = {"Content-Type": mime, **(u.get("headers") or {})}
        r = httpx.put(self.url(u["url"]), content=data, headers=put_headers, timeout=60)
        r.raise_for_status()
        return self.post(f"/api/cases/{cid}/evidence", {"type": "image", "gcsPath": u["path"], "mimeType": mime, "fileName": fname})

    def paste(self, cid, fname):
        return self.post(f"/api/cases/{cid}/evidence", {"type": "text", "textContent": (FIX / fname).read_text()})


def kinds(evs):
    return [e["card"]["kind"] for e in evs if e.get("type") == "card"]


def card(evs, kind):
    return next(e["card"]["data"] for e in evs if e.get("type") == "card" and e["card"]["kind"] == kind)


def text(evs):
    return "".join(e.get("text", "") for e in evs if e.get("type") == "token")


def tokens(mock: bool) -> tuple[str, str]:
    if mock:
        return f"mock:e2e-{uuid.uuid4().hex[:8]}", "mock:bank:E2E Analyst"
    key = os.environ.get("FIREBASE_API_KEY") or json.loads((STATE / "sdkconfig.json").read_text())["apiKey"]
    victim = httpx.post(f"{IDT}:signUp?key={key}", json={"returnSecureToken": True}, timeout=30).json()["idToken"]
    email = os.environ.get("BANK_USER_EMAIL", "analyst@recoverai-demo.example")
    pw = os.environ.get("BANK_USER_PASSWORD") or (STATE / "bank_password").read_text().strip()
    r = httpx.post(f"{IDT}:signInWithPassword?key={key}", json={"email": email, "password": pw, "returnSecureToken": True}, timeout=30)
    r.raise_for_status()
    return victim, r.json()["idToken"]


def india(v: Api, bank: Api) -> None:
    print("India storyline")
    t0 = time.time()
    cid = v.post("/api/cases", {"country": "IN", "language": "hi"})["caseId"]
    check("upload" in kinds(v.chat(cid, {"text": "मैंने CBI वाले को 1,95,000 भेज दिए"})), "upload card")
    v.upload(cid, "in_upi_success.png", "image/png")
    w = v.paste(cid, "in_whatsapp_scam.txt")
    f = card(v.chat(cid, {"trigger": "evidence_added", "evidenceIds": [w["evidence"]["id"]]}), "facts")
    by = {x["key"]: x for x in f["fields"]}
    check(by["reference_id"]["value"] == "612345678901", "UTR extracted")
    check(by["amount"]["display"] == "₹1,95,000", "amount in lakh format")
    v.patch(f"/api/cases/{cid}/extraction", {"fields": {"beneficiary.bank": "Sample Co-operative Bank"}, "confirm": True})
    evs = v.chat(cid, {"trigger": "facts_confirmed"})
    plan = card(evs, "plan")
    check([s["id"] for s in plan["steps"]] == ["call_1930", "file_ncrp", "report_bank"], "IN plan steps")
    check(any(c["status"] == "recommended" for c in plan["clocks"]), "RBI 5-day rule shown as recommended (not yet in force)")
    evs = v.chat(cid, {"trigger": "generate_all"})
    check(kinds(evs) == ["drafts", "consent"], "drafts + consent cards")
    check(all("612345678901" in d["en"] and "612345678901" in d["local"] for d in card(evs, "drafts")["drafts"]), "drafts carry UTR")
    pack = v.post(f"/api/cases/{cid}/evidence-pack")
    check(httpx.get(v.url(pack["url"]), timeout=60).content[:4] == b"%PDF", "evidence pack PDF downloads")
    case = v.post(f"/api/cases/{cid}/send-to-bank", {"consent": True})["case"]
    check(case["bankStatus"] == "SENT", "case sent to bank via A2A")
    print(f"  (victim flow {time.time() - t0:.1f}s)")
    bc = next(b for b in bank.get("/api/bank/cases")["cases"] if b["caseId"] == cid)
    d = bank.get(f"/api/bank/cases/{bc['id']}")["case"]
    check(d["riskLevel"] == "HIGH" and d["recommendedAction"] == "TEMPORARY_HOLD", "bank: HIGH risk, temporary hold recommended")
    bank.post(f"/api/bank/cases/{bc['id']}/decision", {"decision": "APPROVE_HOLD"})
    check(v.get(f"/api/cases/{cid}")["case"]["bankStatus"] == "HOLD_APPROVED", "victim sees hold approved")
    check(kinds(v.chat(cid, {"text": "Pay ₹5,000 fee and we recover your money"}))[:1] == ["warning"], "recovery-scam warning first")
    r = v.post(f"/api/cases/{cid}/clock", {"jumpToDay": 31})
    check([m["card"]["kind"] for m in r["messages"] if m.get("card")] == ["escalation"], "day-31 ombudsman escalation")
    check(v.post(f"/api/cases/{cid}/clock", {"addDays": 1})["messages"] == [], "escalation fires exactly once")


def malaysia(v: Api) -> None:
    print("Malaysia storyline")
    cid = v.post("/api/cases", {"country": "MY", "language": "ms"})["caseId"]
    v.upload(cid, "my_bank_transfer.png", "image/png")
    v.paste(cid, "my_sms.txt")
    check(kinds(v.chat(cid, {"trigger": "evidence_added"})) == ["facts"], "facts card")
    v.patch(f"/api/cases/{cid}/extraction", {"confirm": True})
    plan = card(v.chat(cid, {"trigger": "facts_confirmed"}), "plan")
    check([s["id"] for s in plan["steps"]][:2] == ["call_997", "call_bank"], "MY plan: 997 then bank")
    drafts = card(v.chat(cid, {"trigger": "generate_all"}), "drafts")["drafts"]
    check(any(d["stepId"] == "police_statement" for d in drafts), "police-statement note")
    v.c.delete(v.url(f"/api/cases/{cid}"))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--api", default=os.environ.get("API_BASE", "http://localhost:8080"))
    ap.add_argument("--mock", action="store_true", help="use mock tokens (backend running with MOCK_MODE=true)")
    a = ap.parse_args()
    vt, bt = tokens(a.mock)
    v, bank = Api(a.api, vt), Api(a.api, bt)
    check(httpx.get(v.url("/healthz"), timeout=30).json().get("ok") is True, f"healthz {a.api}")
    india(v, bank)
    malaysia(v)
    print("E2E OK")


if __name__ == "__main__":
    main()
