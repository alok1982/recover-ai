#!/usr/bin/env python3
"""Drive both PRD §4 storylines (India + Malaysia) and the bank side end-to-end over HTTP.

Local mock stack:   python scripts/e2e_demo.py --mock --api http://localhost:8080
Deployed stack:     API_BASE=$(cat deploy/.state/run_url) python scripts/e2e_demo.py
  (CR-03: seeded phone + password victims — scripts/seed_users.py — and the analyst sign in via the Firebase Auth
   REST API; an anonymous token must be rejected. Uses
   deploy/.state/sdkconfig.json and deploy/.state/bank_password written by deploy/deploy.sh)
Exits non-zero on the first failed check. DEMO_MODE must be on for the time-travel step.
Checks the v2.2 backbone too: bank case created via the fraud-case-submitted Pub/Sub push with BigQuery features,
the bank decision reaching the victim via bank-decision (timed against the 3 s target), and a cited source (F16).
"""
from __future__ import annotations

import argparse
import re
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

    def get_or_none(self, p):
        r = self.c.get(self.url(p))
        return r.json() if r.status_code == 200 else None

    def post(self, p, body=None):
        r = self.c.post(self.url(p), json=body or {})
        if r.status_code >= 400:
            raise SystemExit(f"POST {p} -> {r.status_code}: {r.text[:300]}")
        return r.json()

    def post_status(self, p, body=None) -> tuple[int, dict]:
        r = self.c.post(self.url(p), json=body or {})
        try:
            return r.status_code, r.json()
        except ValueError:
            return r.status_code, {}

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
        if body.get("text"):  # every co-pilot turn must write a real reply (blank-reply regression)
            reply = text(evs).strip()
            if not reply:
                check(False, f"non-empty assistant reply for: {body['text']!r} (cards {kinds(evs)})")
            REPLIES.append({"q": body["text"], "reply": reply[:160]})
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


def poll(fn, timeout: float, every: float = 0.5):
    end = time.time() + timeout
    while time.time() < end:
        r = fn()
        if r:
            return r
        time.sleep(every)
    return None


def kinds(evs):
    return [e["card"]["kind"] for e in evs if e.get("type") == "card"]


def card(evs, kind):
    return next(e["card"]["data"] for e in evs if e.get("type") == "card" and e["card"]["kind"] == kind)


def text(evs):
    return "".join(e.get("text", "") for e in evs if e.get("type") == "token")


SEED = {"in_complete": "+919000000001", "in_incomplete": "+919000000002", "my_complete": "+60100000001"}
SEED_PASSWORD = "Demo@2026"
DEMO_BANK, DEMO_BANK_ID = "RecoverAI Demo Bank (fictional)", "demo-recoverai-bank"  # DEMO_MODE bank side  # CR-03 fictional seed accounts (scripts/seed_users.py)


def _api_key() -> str:
    return os.environ.get("FIREBASE_API_KEY") or json.loads((STATE / "sdkconfig.json").read_text())["apiKey"]


def phone_login(e164: str, password: str = SEED_PASSWORD) -> httpx.Response:
    """CR-03: phone + password = Firebase Email/Password with the synthetic <digits>@phone.recoverai.app login."""
    email = e164.lstrip("+") + "@phone.recoverai.app"
    return httpx.post(f"{IDT}:signInWithPassword?key={_api_key()}", json={"email": email, "password": password,
                                                                         "returnSecureToken": True}, timeout=30)


def tokens(mock: bool, api: str) -> tuple[dict[str, str], str, str]:
    """Seeded victims (by role), the analyst, and an anonymous token (must be rejected on victim routes)."""
    if mock:
        import subprocess
        subprocess.run([sys.executable, str(ROOT / "scripts" / "seed_users.py"), "--api", api], check=True,
                       stdout=subprocess.DEVNULL)
        return {k: f"mock:phone:{v}" for k, v in SEED.items()}, "mock:bank:E2E Analyst", f"mock:anon-{uuid.uuid4().hex[:8]}"
    victims = {}
    for k, e164 in SEED.items():
        r = phone_login(e164)
        r.raise_for_status()
        victims[k] = r.json()["idToken"]
    bad = phone_login(SEED["in_complete"], "Wrong-password-1")
    check(bad.status_code == 400, f"wrong password rejected by Firebase ({bad.json().get('error', {}).get('message')})")
    anon = httpx.post(f"{IDT}:signUp?key={_api_key()}", json={"returnSecureToken": True}, timeout=30).json()["idToken"]
    email = os.environ.get("BANK_USER_EMAIL", "analyst@recoverai-demo.example")
    pw = os.environ.get("BANK_USER_PASSWORD") or (STATE / "bank_password").read_text().strip()
    r = httpx.post(f"{IDT}:signInWithPassword?key={_api_key()}", json={"email": email, "password": pw, "returnSecureToken": True}, timeout=30)
    r.raise_for_status()
    return victims, r.json()["idToken"], anon


GATE_MSG = "मेरे साथ अभी 1,95,000 का फ्रॉड हुआ"
INCOMPLETE = {"postalCode": "", "primaryBank": ""}


def accounts(v1: Api, anon: Api) -> None:
    print("Accounts (CR-03 B)")
    st, body = anon.post_status("/api/cases", {"country": "IN", "language": "en"})
    check(st == 401, f"anonymous token rejected on victim routes ({st})")
    me = v1.get("/api/me")
    check(me["profileStatus"]["complete"] and me["phoneVerified"] is False and me["phoneMasked"].endswith("0001"),
          f"seeded 00001: complete profile, phoneVerified=false, masked {me['phoneMasked']}")
    check(isinstance(v1.get("/api/cases")["cases"], list), "GET /api/cases lists my cases")


def profile_gate(v2: Api) -> None:
    print("Profile gate (CR-03 C) as seeded 00002")
    r = v2.c.put(v2.url("/api/me/profile"), json={"profile": INCOMPLETE})  # demo account: back to the seeded state
    r.raise_for_status()
    check(r.json()["profileStatus"]["missing"] == ["postalCode", "primaryBank"], "00002 is missing PIN code and bank")
    cid = v2.post("/api/cases", {"country": "IN", "language": "hi"})["caseId"]
    try:
        evs = v2.chat(cid, {"text": GATE_MSG})
        ks = kinds(evs)
        check(ks[:2] == ["hotline", "profile"] and "upload" not in ks, f"hotline card, then profile card ({ks})")
        check(card(evs, "hotline")["number"] == "1930", "hotline card: Call 1930")
        check(card(evs, "profile")["missing"] == ["postalCode", "primaryBank"], "profile card asks only PIN code + bank")
        for path in ("drafts", "send-to-bank/preview"):
            st, body = v2.post_status(f"/api/cases/{cid}/{path}")
            d = body.get("detail") or {}
            check(st == 412 and d.get("code") == "PROFILE_INCOMPLETE" and d.get("missing") == ["postalCode", "primaryBank"],
                  f"{path} → {st} {d.get('code')}")
        r = v2.c.put(v2.url("/api/me/profile"), json={"profile": {"postalCode": "208001", "primaryBank": "State Bank of India"}})
        check(r.status_code == 200 and r.json()["profileStatus"]["complete"], "victim saves the card → profile complete")
        evs = v2.chat(cid, {"trigger": "profile_saved"})
        check("upload" in kinds(evs), f"after Save the co-pilot asks for evidence ({kinds(evs)})")
        st, _ = v2.post_status(f"/api/cases/{cid}/send-to-bank/preview")
        check(st != 412, f"gate lifted after Save (preview → {st})")
    finally:
        v2.c.put(v2.url("/api/me/profile"), json={"profile": INCOMPLETE})  # keep the seeded demo state
        v2.c.delete(v2.url(f"/api/cases/{cid}"))


def india(v: Api, bank: Api) -> None:
    print("India storyline")
    t0 = time.time()
    cid = v.post("/api/cases", {"country": "IN", "language": "hi"})["caseId"]
    ks = kinds(v.chat(cid, {"text": "मैंने CBI वाले को 1,95,000 भेज दिए"}))
    check("upload" in ks and "profile" not in ks and "hotline" not in ks, f"complete profile → straight to evidence ({ks})")
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
    prof = v.get("/api/me")["profile"]
    letter = next(d for d in card(evs, "drafts")["drafts"] if d["templateId"] == "bank_dispute_letter")
    check(prof["fullName"] in letter["en"] and prof["postalCode"] in letter["en"] and prof["district"] in letter["en"],
          f"bank letter signed with the profile name + address ({prof['fullName']}, {prof['district']} {prof['postalCode']})")
    light_routing(v, cid, w["evidence"]["id"])
    pack = v.post(f"/api/cases/{cid}/evidence-pack")
    check(httpx.get(v.url(pack["url"]), timeout=60).content[:4] == b"%PDF", "evidence pack PDF downloads")
    # CR-01 / F8: sandbox path — preview + confirmation token + undo; nothing reaches the live queue
    live_before = live_queue(bank)
    sent_before = {r["id"] for r in bank.get("/api/bank/cases")["cases"]}
    pv = v.post(f"/api/cases/{cid}/send-to-bank/preview")
    ref = pv["summary"]["publicRef"]
    check(pv["summary"]["destination"] == "SANDBOX" and re.fullmatch(r"RAI-IN-\d{8}-\d{4}", ref or "") is not None,
          f"preview: destination SANDBOX, readable reference {ref}")
    check(pv["summary"]["bankName"] == DEMO_BANK and (pv["summary"].get("receivingBank") or {}).get("bankId") == DEMO_BANK_ID,
          f"preview: received by {pv['summary']['bankName']} (no real bank)")
    time.sleep(2)  # the client's 10 s undo = simply never calling send-to-bank
    check({r["id"] for r in bank.get("/api/bank/cases")["cases"]} == sent_before and v.get(f"/api/cases/{cid}")["case"]["bankStatus"] == "NONE",
          "preview / undo publishes nothing")
    v.patch(f"/api/cases/{cid}/extraction", {"fields": {"beneficiary.bank": "Sample Co-operative Bank Ltd"}})
    st, body = v.post_status(f"/api/cases/{cid}/send-to-bank", {"confirmationToken": pv["confirmationToken"], "confirmed": True})
    check(st == 409 and body.get("detail") == "Details changed — please review again", f"edited facts after preview → {st} {body.get('detail')}")
    v.patch(f"/api/cases/{cid}/extraction", {"fields": {"beneficiary.bank": "Sample Co-operative Bank"}})
    st, _ = v.post_status(f"/api/cases/{cid}/send-to-bank", {"confirmationToken": pv["confirmationToken"], "confirmed": False})
    check(st == 400, "send without the confirmation checkbox → 400")
    pv = v.post(f"/api/cases/{cid}/send-to-bank/preview")
    t_send = time.time()
    r = v.post(f"/api/cases/{cid}/send-to-bank", {"confirmationToken": pv["confirmationToken"], "confirmed": True})
    case = r["case"]
    check(case["bankStatus"] == "SENT" and case.get("bankCaseId") and (case.get("submission") or {}).get("destination") == "SANDBOX",
          "confirmed send → published to fraud-case-submitted (env=sandbox)")
    reply = " ".join(m.get("text") or "" for m in r["messages"])
    check(ref in reply and case["bankCaseId"] not in reply, f"reply shows {ref}, no internal id")
    print(f"  (victim flow {time.time() - t0:.1f}s)")
    d = poll(lambda: bank.get_or_none(f"/api/bank/cases/{case['bankCaseId']}"), 30)
    check(d is not None, f"bank case created by Pub/Sub push ({time.time() - t_send:.1f}s after consent)")
    d = d["case"]
    check(d.get("sandbox") is True and d.get("publicRef") == ref, "bank case stored with sandbox=true + publicRef (Sandbox tab)")
    check(d.get("receivingBankId") == DEMO_BANK_ID and d.get("receivingBankName") == DEMO_BANK
          and DEMO_BANK_ID in ((d.get("envelope") or {}).get("to_agent") or ""), f"bank case received by {d.get('receivingBankName')}")
    check(live_queue(bank) == live_before, f"live queue unchanged by this run ({len(live_before)} pre-existing live-tab case(s))")
    SANDBOX.update({"caseId": cid, "publicRef": ref, "bankCaseId": case["bankCaseId"]})
    check(d["riskLevel"] == "HIGH" and d["recommendedAction"] == "TEMPORARY_HOLD", "bank: HIGH risk, temporary hold recommended")
    f = d.get("txnFeatures") or {}
    check(d.get("txnStatus") == "ok" and f.get("credits_24h") == 9 and f.get("account_age_days") == 21,
          f"signals from transaction data ({d.get('txnSource')}, {d.get('txnQueryMs')} ms)")
    full = poll(lambda: (lambda x: x if x and not x["case"].get("reasonPending") else None)(
        bank.get_or_none(f"/api/bank/cases/{d['id']}")), 30)
    if full:
        d = full["case"]
        print(f"  (reason: {d.get('reasonSource')}, {time.time() - t_send:.1f}s after consent; "
              f"ML mule-risk {d.get('mlRiskScore')} — advisory)")
    t_dec = time.time()
    bank.post(f"/api/bank/cases/{d['id']}/decision", {"decision": "APPROVE_HOLD"})
    ok = poll(lambda: v.get(f"/api/cases/{cid}")["case"]["bankStatus"] == "HOLD_APPROVED" or None, 10, 0.25)
    took = time.time() - t_dec
    check(bool(ok), f"victim sees hold approved via bank-decision event ({took:.1f}s{' — over the 3 s target!' if took > 3 else ''})")
    check(kinds(v.chat(cid, {"text": "Pay ₹5,000 fee and we recover your money"}))[:1] == ["warning"], "recovery-scam warning first")
    done = next(e for e in v.chat(cid, {"text": "Will I definitely get my money back?"}) if e.get("type") == "done")
    srcs = (done.get("message") or {}).get("sources") or []
    check(bool(srcs), f"honest answer cites an official source: {srcs[0]['title'][:60] if srcs else '-'}")
    intel = bank.get("/api/bank/analytics")
    check(bool(intel.get("repeat_beneficiaries")), f"scam intelligence panels ({intel.get('source')})")
    r = v.post(f"/api/cases/{cid}/clock", {"jumpToDay": 31})
    check([m["card"]["kind"] for m in r["messages"] if m.get("card")] == ["escalation"], "day-31 ombudsman escalation")
    check(v.post(f"/api/cases/{cid}/clock", {"addDays": 1})["messages"] == [], "escalation fires exactly once")
    # CR-01 / F8.4: withdraw consent from chat
    evs = v.chat(cid, {"text": "Reverse the consent which has sent to bank"})
    wtext = text(evs).lower()
    check("withdraw" in kinds(evs) and "impossible" not in wtext and "cannot be withdrawn" not in wtext, "withdraw request → withdraw card")
    t_w = time.time()
    r = v.post(f"/api/cases/{cid}/withdraw-consent", {"confirmed": True})
    w = poll(lambda: (lambda x: x if x and x["case"]["status"] == "WITHDRAWN_BY_CUSTOMER" else None)(
        bank.get_or_none(f"/api/bank/cases/{case['bankCaseId']}")), 10, 0.2)
    took = time.time() - t_w
    check(w is not None and took <= 3, f"bank case WITHDRAWN_BY_CUSTOMER in {took:.1f}s (target ≤ 3 s)")
    check(w["case"]["evidence"] == [] and "CONSENT_WITHDRAWN" in [x["action"] for x in w["audit"]], "evidence hidden + audit entry")
    wr = " ".join(m.get("text") or "" for m in r["messages"])
    check(r["case"]["bankStatus"] == "WITHDRAWN" and ref in wr, f"victim: WITHDRAWN, reply shows {ref}")
    msgs = v.get(f"/api/cases/{cid}/messages")["messages"]
    shown = " ".join(m.get("text") or "" for m in msgs if m["role"] != "system_event")
    check(case["bankCaseId"] not in shown and not re.search(r"\bb_[0-9a-f]{8,}", shown), "no internal ids in any co-pilot reply")
    SANDBOX["withdrawS"] = round(took, 2)
    # CR-03: seeded accounts are shared (MAX_OPEN_CASES per user) → delete the victim case this run created
    v.c.delete(v.url(f"/api/cases/{cid}"))


def _done(evs):
    return next(e for e in evs if e.get("type") == "done")


ROUTING: list[dict] = []
REPLIES: list[dict] = []
SANDBOX: dict = {}


def live_queue(bank: Api) -> set[str]:
    """Bank cases the dashboard's Live queue tab shows (sandbox !== true)."""
    return {r["id"] for r in bank.get("/api/bank/cases")["cases"] if r.get("sandbox") is not True}


def light_routing(v: Api, cid: str, evidence_id: str) -> None:
    """F17: light Hindi questions → Gemma (or Gemini when the light model is off / forced to fail); heavy turns → Gemini."""
    h = v.get("/api/health")
    light, forced = h.get("chatLight"), h.get("forceLightFail")
    turns = [("अब मुझे क्या करना है?", {}, "light"), ("Ombudsman क्या है?", {}, "light"),
             ("यह स्क्रीनशॉट देखो", {"evidenceIds": [evidence_id]}, "full"),
             ("draft my complaint", {}, "full"), ("send to my bank", {}, "full")]
    for q, extra, kind in turns:
        t0 = time.time()
        evs = v.chat(cid, {"text": q, **extra})
        d = _done(evs)
        m = d.get("message") or {}
        model, route = m.get("model") or d.get("model"), m.get("route") or {}
        reply = text(evs)
        ROUTING.append({"q": q, "model": model, "route": route.get("route"), "reason": route.get("reason"),
                        "fallback": route.get("fallback"), "gemmaFirstTokenMs": route.get("firstTokenMs") if route.get("firstTokenMs") is not None else route.get("lightFirstTokenMs"),
                        "turnS": round(time.time() - t0, 1)})
        check(not any(e.get("type") == "error" for e in evs) and bool(reply.strip()), f"reply without error: {q}")
        if kind == "light":
            if light and not forced:
                check(str(model).startswith("gemma"), f"light turn answered by Gemma (model={model}, "
                      f"fallback={route.get('fallback')}, first token {route.get('firstTokenMs')} ms): {q}")
                check(bool(re.search(r"[\u0900-\u097F]", reply)), "light reply is in Hindi")
            else:
                check((model == "gemini-fallback") if light else not str(model).startswith("gemma"),
                      f"light model off / forced to fail → Gemini ({model}): {q}")
        else:
            check(not str(model).startswith("gemma"), f"heavy turn stays on Gemini ({model}, {route.get('reason')}): {q}")
    for r in ROUTING:
        print("   ", json.dumps(r, ensure_ascii=False))


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


def email_login(email: str, password: str) -> httpx.Response:
    return httpx.post(f"{IDT}:signInWithPassword?key={_api_key()}", json={"email": email, "password": password,
                                                                         "returnSecureToken": True}, timeout=30)


def roles(api: str, mock: bool, victim: Api, analyst: Api) -> None:
    """CR-04: a bank applicant stays PENDING with no bank access; admin approve → bank desk; revoke blocks again."""
    print("Roles (CR-04)")
    email = f"cr04.e2e.{uuid.uuid4().hex[:8]}@demo-bank.example"
    pw = "E2e-" + uuid.uuid4().hex[:10] + "9"
    form = {"fullName": "E2E Applicant", "country": "IN", "bankName": DEMO_BANK, "employeeId": "DEMO-0001",
            "designation": "Fraud analyst", "note": "e2e test account (deleted at the end)"}
    if mock:
        app_tok = lambda: f"mock:staff:{email}"  # noqa: E731
        admin_tok = "mock:admin:E2E"
    else:
        r = httpx.post(f"{IDT}:signUp?key={_api_key()}", json={"email": email, "password": pw, "returnSecureToken": True}, timeout=30)
        r.raise_for_status()
        app_tok = lambda: email_login(email, pw).json()["idToken"]  # noqa: E731 — a fresh sign-in picks up claims
        ar = email_login("admin@recoverai-demo.example", (STATE / "admin_password").read_text().strip())
        check(ar.status_code == 200, "seeded admin signs in")
        admin_tok = ar.json()["idToken"]
    app, adm = Api(api, app_tok()), Api(api, admin_tok)
    try:
        st, _ = victim.post_status("/api/bank-access/request", form)
        check(st == 409, f"a victim phone account cannot apply for bank access ({st})")
        st, _ = app.post_status("/api/bank-access/request", {**form, "bankName": "HDFC Bank"})
        check(st == 422, f"demo mode: a real bank cannot be chosen for bank staff ({st})")
        req = app.post("/api/bank-access/request", {**form, "role": "bank", "status": "APPROVED"})
        check(req["status"] == "PENDING" and req["bankId"] is None, "applicant request is PENDING; body role/status ignored")
        uid = req["uid"]
        me = app.get("/api/me")
        check(me["role"] is None and me["requestStatus"] == "PENDING", "GET /api/me: role none, requestStatus PENDING")
        check(app.c.get(app.url("/api/bank/cases")).status_code == 403, "pending applicant → 403 on bank APIs")
        check(app.c.get(app.url("/api/admin/bank-requests")).status_code == 403, "applicant → 403 on admin APIs")
        check(victim.c.get(victim.url("/api/admin/bank-requests")).status_code == 403, "victim → 403 on admin APIs")
        check(analyst.c.get(analyst.url("/api/admin/bank-requests")).status_code == 403, "analyst → 403 on admin APIs")
        st, _ = app.post_status("/api/cases", {"country": "IN", "language": "en"})
        check(st == 403, f"staff account is not a victim ({st})")
        pend = adm.get("/api/admin/bank-requests?status=PENDING")["requests"]
        check(any(r["uid"] == uid for r in pend), f"admin sees the request in the pending queue ({len(pend)} pending)")
        ok = adm.post(f"/api/admin/bank-requests/{uid}/approve", {})
        check(ok["status"] == "APPROVED" and ok["bankId"] == DEMO_BANK_ID, f"admin approves (bankId {ok['bankId']})")
        app2 = Api(api, app_tok())
        check(app2.get("/api/me")["role"] == "bank", "after re-login the token carries role=bank")
        check(app2.c.get(app2.url("/api/bank/cases")).status_code == 200, "approved applicant → 200 on bank APIs")
        rv = adm.post(f"/api/admin/users/{uid}/revoke-bank", {"reason": "e2e revoke"})
        check(rv["status"] == "REVOKED", "admin revokes")
        check(app2.c.get(app2.url("/api/bank/cases")).status_code == 403, "revoked: the old token is blocked at once (403)")
        if not mock:
            r = email_login(email, pw)
            check(r.status_code == 200, "revoked applicant can still sign in (to see the status)")
            app3 = Api(api, r.json()["idToken"])
            check(app3.get("/api/me")["role"] is None and app3.c.get(app3.url("/api/bank/cases")).status_code == 403,
                  "revoked: fresh token has no bank role (403)")
        acts = {(a["action"], a["targetUid"]) for a in adm.get("/api/admin/audit?limit=50")["entries"]}
        check({("approve", uid), ("revoke_bank", uid), ("request_submitted", uid)} <= acts, "audit log: submit, approve, revoke")
        check(analyst.c.get(analyst.url("/api/bank/cases")).status_code == 200, "existing analyst still has bank access")
    finally:
        tok = app_tok() if not mock else f"mock:staff:{email}"
        httpx.delete(f"{api}/api/me", headers={"Authorization": f"Bearer {tok}"}, timeout=30)
        if not mock:
            httpx.post(f"{IDT}:delete?key={_api_key()}", json={"idToken": tok}, timeout=30)
            check(email_login(email, pw).status_code == 400, "test applicant account deleted")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--api", default=os.environ.get("API_BASE", "http://localhost:8080"))
    ap.add_argument("--mock", action="store_true", help="use mock tokens (backend running with MOCK_MODE=true)")
    a = ap.parse_args()
    vts, bt, at = tokens(a.mock, a.api)
    v, bank = Api(a.api, vts["in_complete"]), Api(a.api, bt)
    check(httpx.get(v.url("/api/health"), timeout=30).json().get("ok") is True, f"healthz {a.api}")
    accounts(v, Api(a.api, at))
    profile_gate(Api(a.api, vts["in_incomplete"]))
    roles(a.api, a.mock, v, bank)
    india(v, bank)
    malaysia(Api(a.api, vts["my_complete"]))
    check(bool(REPLIES), f"all {len(REPLIES)} co-pilot chat turns had non-empty text")
    for r in REPLIES:
        print("   ", json.dumps(r, ensure_ascii=False))
    print("SANDBOX", json.dumps(SANDBOX))
    print("E2E OK")


if __name__ == "__main__":
    main()
