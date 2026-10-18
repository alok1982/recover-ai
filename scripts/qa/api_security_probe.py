#!/usr/bin/env python3
"""RecoverAI API security probe (QA plan §2 F5, I1, I2, I3, I6 + the probe P0 checks).

  .venv/bin/python scripts/qa/api_security_probe.py [--out /tmp/probe.json]

Live only. Creates two throw-away victims (+91 90000 01101 / 01102), one sandbox case that is sent to the fictional
demo bank (sandbox) and then withdrawn, and deletes both accounts at the end (DELETE /api/me → cases, evidence,
profile and Firebase login). Never touches the user's own account. Prints no secrets or tokens.
Checks:
  push endpoints without / with a bad / with a wrong-audience OIDC token (run.app + Hosting)   F5   P0
  IDOR: user B on user A's case, messages, evidence, PDF, chat, send/withdraw, upload paths    I1   P0
  Firestore rules from the client REST API with real ID tokens                                 I1   P0
  victim / anonymous / no token on bank + admin endpoints; staff token on victim routes        F1   P0
  412 PROFILE_INCOMPLETE on all gated endpoints                                               B6   P1
  live send blocked (ALLOW_LIVE_SUBMISSION=false) + sandbox forced                            E1   P0
  409 changed facts / tampered token, double confirm → one bank case, Pub/Sub replay          E7 E8 F6
  signed URLs: ≤ 15 min, bucket not listable, tampered signature rejected                     I2   P1
  response headers, internal-id leakage in PDF + replies, max 3 open cases                    I3 E11 K
"""
from __future__ import annotations

import argparse
import base64
import concurrent.futures as cf
import json
import re
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent))
from qa_common import (FIX, IDT, PROJECT, RUN_URL, SITE, Api, COMPLETE_IN, Throwaway, api_key, dump, rec,  # noqa: E402
                       staff_token)

FS = f"https://firestore.googleapis.com/v1/projects/{PROJECT}/databases/(default)/documents"
GCLOUD = "/home/box/tools/google-cloud-sdk/bin/gcloud"


def push_checks() -> None:
    body = {"message": {"data": base64.b64encode(json.dumps({"intent": "fraud_case.submit", "payload": {"caseId": "c_probe"}}).encode()).decode(),
                        "messageId": "probe-1", "attributes": {"eventTopic": "fraud-case-submitted"}}, "subscription": "probe"}
    try:
        user_id_tok = subprocess.run([GCLOUD, "auth", "print-identity-token"], capture_output=True, text=True, timeout=60).stdout.strip()
    except Exception:  # noqa: BLE001
        user_id_tok = ""
    fake_jwt = ".".join(base64.urlsafe_b64encode(json.dumps(x).encode()).decode().rstrip("=") for x in
                        ({"alg": "RS256", "kid": "x"}, {"email": "pubsub-push@recoverai-511917.iam.gserviceaccount.com",
                                                        "aud": RUN_URL, "email_verified": True, "exp": 9999999999})) + ".c2ln"
    for base, label in ((RUN_URL, "run.app"), (SITE, "hosting")):
        for path in ("/bank/a2a/inbox", "/api/bank/a2a/inbox", "/api/events/bank-decision"):
            if base == SITE and path == "/bank/a2a/inbox":
                continue  # Hosting serves the SPA there (no rewrite)
            for tok, tl in ((None, "no token"), ("garbage", "bad token"), (fake_jwt, "forged unsigned JWT"),
                            (user_id_tok, "real Google ID token, wrong audience/account")):
                if tl.startswith("real") and not tok:
                    continue
                h = {"Authorization": f"Bearer {tok}"} if tok else {}
                r = httpx.post(base + path, json=body, headers=h, timeout=30)
                rec("F5", f"push {label}{path} with {tl} → rejected", r.status_code in (401, 403), f"HTTP {r.status_code}", "P0")


def firestore_rest(tok: str, path: str, method: str = "GET", body: dict | None = None) -> int:
    return httpx.request(method, f"{FS}/{path}", headers={"Authorization": f"Bearer {tok}"}, json=body, timeout=30).status_code


def anon_token() -> str:
    return httpx.post(f"{IDT}:signUp?key={api_key()}", json={"returnSecureToken": True}, timeout=30).json()["idToken"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="/workspace/qa_logs/probe.json")
    a = ap.parse_args()
    t0 = time.time()
    h = httpx.get(SITE + "/api/health", timeout=30).json()
    rec("K-HEALTH", "/api/health: allowLiveSubmission=false, sandboxDefault=true, demo=true, chatLight(Gemma) off",
        h.get("allowLiveSubmission") is False and h.get("sandboxDefault") is True and h.get("chatLight") in (None, ""),
        json.dumps(h), "P0")
    push_checks()

    A = Throwaway("+919000001101", profile=COMPLETE_IN)
    B = Throwaway("+919000001102", profile={**COMPLETE_IN, "fullName": "QA Tester Two", "postalCode": "", "primaryBank": ""})
    anon = None
    try:
        a_, b_ = A.api, B.api
        # ---------------- I1 / IDOR
        cid = a_.j("POST", "/api/cases", json={"country": "IN", "language": "en", "sandbox": False})["caseId"]
        case = a_.j("GET", f"/api/cases/{cid}")["case"]
        rec("E1", "case created with sandbox=false request is forced to sandbox (ALLOW_LIVE_SUBMISSION=false)",
            case.get("sandbox") is True, f"sandbox={case.get('sandbox')}", "P0")
        r = a_.req("PATCH", f"/api/cases/{cid}/sandbox", json={"sandbox": False})
        rec("E1", "PATCH sandbox=false (go live) → 403", r.status_code == 403, f"HTTP {r.status_code}", "P0")
        ev_txt = a_.j("POST", f"/api/cases/{cid}/evidence", json={"type": "text", "textContent": (FIX / "in_whatsapp_scam.txt").read_text()})
        img = a_.upload(cid, (FIX / "in_upi_success.png").read_bytes(), "image/png", "in_upi_success.png")
        img_j = img.json() if img.status_code < 300 else {}
        rec("E2", "bundled demo screenshot uploaded → case locked to sandbox",
            a_.j("GET", f"/api/cases/{cid}")["case"].get("sandboxLocked") is True, "", "P0")
        evid = (img_j.get("evidence") or {})
        purl = evid.get("previewUrl")
        a_path = evid.get("gcsPath")
        B_cid = b_.j("POST", "/api/cases", json={"country": "IN", "language": "en"})["caseId"]
        probes = [("GET", f"/api/cases/{cid}", None), ("GET", f"/api/cases/{cid}/messages", None),
                  ("GET", f"/api/cases/{cid}/evidence", None), ("PATCH", f"/api/cases/{cid}", {"language": "hi"}),
                  ("POST", f"/api/cases/{cid}/evidence-pack", None), ("POST", f"/api/cases/{cid}/evidence/upload-url", {"mimeType": "image/png", "sizeBytes": 10}),
                  ("POST", f"/api/cases/{cid}/evidence", {"type": "text", "textContent": "x"}),
                  ("PATCH", f"/api/cases/{cid}/extraction", {"fields": {}, "confirm": True}),
                  ("POST", f"/api/cases/{cid}/send-to-bank/preview", None), ("POST", f"/api/cases/{cid}/withdraw-consent", {"confirmed": True}),
                  ("POST", f"/api/cases/{cid}/clock", {"addDays": 1}), ("POST", f"/api/cases/{cid}/guard", {"text": "x"}),
                  ("PATCH", f"/api/cases/{cid}/sandbox", {"sandbox": True}), ("POST", f"/api/cases/{cid}/chat", {"text": "hi"}),
                  ("DELETE", f"/api/cases/{cid}", None)]
        for m, p, body in probes:
            r = b_.req(m, p, json=body) if body is not None else b_.req(m, p)
            rec("I1", f"IDOR: user B {m} {p.replace(cid, '{A-case}')} → denied", r.status_code in (403, 404),
                f"HTTP {r.status_code}", "P0")
        r = b_.req("POST", f"/api/cases/{B_cid}/evidence", json={"type": "image", "gcsPath": a_path or f"cases/{cid}/evidence/x.png", "mimeType": "image/png"})
        rec("I1", "IDOR: B registers A's evidence path in B's own case → 400", r.status_code == 400, f"HTTP {r.status_code}", "P0")
        r = b_.req("POST", f"/api/cases/{B_cid}/chat", json={"audioPath": f"cases/{cid}/voice/x.webm"})
        rec("I1", "IDOR: B chat with A's audioPath → rejected", r.status_code >= 400 or "invalid audio path" in r.text,
            f"HTTP {r.status_code}", "P0")
        r = a_.req("GET", f"/api/cases/{cid}/messages")
        rec("K-CACHE", "after B's denied GET, owner A still reads /messages via Hosting (no shared cached 404)", r.status_code == 200,
            f"HTTP {r.status_code} x-cache={r.headers.get('x-cache')} cache-control={r.headers.get('cache-control')}", "P1")
        r = httpx.get(SITE + f"/api/cases/{cid}/messages")
        rec("K-CACHE", "unauthenticated GET via Hosting is not answered from cache", r.status_code == 401,
            f"HTTP {r.status_code} x-cache={r.headers.get('x-cache')}", "P1")
        # I8: the same denied URL twice via Hosting → never a cache HIT; every API status carries private, no-store
        for label, call in (("403 bank API as victim", lambda: b_.req("GET", "/api/bank/cases")),
                            ("404 foreign case", lambda: b_.req("GET", f"/api/cases/{cid}/messages")),
                            ("401 no token", lambda: httpx.get(SITE + f"/api/cases/{cid}")),
                            ("200 health", lambda: httpx.get(SITE + "/api/health"))):
            r1, r2 = call(), call()
            cc = (r2.headers.get("cache-control") or "").lower()
            rec("I8", f"{label}: Cache-Control private, no-store, no CDN HIT on repeat",
                "no-store" in cc and "max-age" not in cc and "HIT" not in (r2.headers.get("x-cache") or ""),
                f"HTTP {r1.status_code}/{r2.status_code} cache-control={cc!r} x-cache={r2.headers.get('x-cache')}", "P1")
        lst = [c["id"] for c in b_.j("GET", "/api/cases")["cases"]]
        rec("I1", "B's /api/cases lists only B's cases", cid not in lst and B_cid in lst, f"{len(lst)} cases", "P0")
        me_b = b_.j("GET", "/api/me")
        rec("I1", "/api/me returns only the caller's profile", me_b["uid"] == B.uid and "QA Tester Two" == me_b["profile"]["fullName"], "", "P0")
        r = b_.req("PUT", "/api/me/profile", json={"profile": {"fullName": "x" * 2}, "uid": A.uid})
        rec("I1", "PUT /api/me/profile ignores a foreign uid in the body", a_.j("GET", "/api/me")["profile"]["fullName"] == "QA Tester",
            "", "P0")
        b_.req("PUT", "/api/me/profile", json={"profile": {"fullName": "QA Tester Two"}})

        # ---------------- Firestore rules from the client side (REST = what the web SDK uses)
        ta, tb = A.fresh().c.headers["Authorization"].split()[1], B.fresh().c.headers["Authorization"].split()[1]
        a_, b_ = A.api, B.api
        rec("I1", "rules: A reads own users/{uid} (positive control)", firestore_rest(ta, f"users/{A.uid}") == 200, "", "P0")
        rec("I1", "rules: A reads own case doc (positive control)", firestore_rest(ta, f"cases/{cid}") == 200, "", "P0")
        for path, what in ((f"users/{A.uid}", "B reads A's users doc"), (f"cases/{cid}", "B reads A's case"),
                           (f"cases/{cid}/messages", "B lists A's messages"), (f"cases/{cid}/evidence", "B lists A's evidence"),
                           ("bank_cases", "victim lists bank_cases"), ("audit_log", "victim lists audit_log"),
                           ("admin_audit", "victim lists admin_audit"), ("bank_access_requests", "victim lists access requests"),
                           ("processed_events", "victim lists processed_events")):
            st = firestore_rest(tb, path)
            rec("I1", f"rules: {what} → 403", st == 403, f"HTTP {st}", "P0")
        st = firestore_rest(tb, f"users?pageSize=5")
        rec("I1", "rules: victim lists all users → 403", st == 403, f"HTTP {st}", "P0")
        st = firestore_rest(tb, f"users/{B.uid}?updateMask.fieldPaths=role", "PATCH", {"fields": {"role": {"stringValue": "bank"}}})
        rec("I1", "rules: client write to own users doc → 403", st == 403, f"HTTP {st}", "P0")
        st = firestore_rest(tb, f"cases/{B_cid}?updateMask.fieldPaths=sandbox", "PATCH", {"fields": {"sandbox": {"booleanValue": False}}})
        rec("I1", "rules: client write to own case (flip sandbox) → 403", st == 403, f"HTTP {st}", "P0")

        # ---------------- role checks
        anon = anon_token()
        for tok, who in ((None, "no token"), (anon, "anonymous token"), ("garbage", "bad token")):
            api = Api(tok)
            for m, p in (("POST", "/api/cases"), ("GET", "/api/cases"), ("GET", "/api/me")):
                r = api.req(m, p, json={"country": "IN", "language": "en"} if m == "POST" else None)
                rec("A4", f"{who}: {m} {p} → 401", r.status_code == 401, f"HTTP {r.status_code}", "P0")
        for m, p, body in (("GET", "/api/bank/cases", None), ("GET", "/api/bank/cases/b_x", None),
                           ("POST", "/api/bank/cases/b_x/decision", {"decision": "APPROVE_HOLD"}), ("GET", "/api/bank/analytics", None),
                           ("GET", "/api/admin/bank-requests", None), ("POST", f"/api/admin/bank-requests/{B.uid}/approve", {}),
                           ("POST", f"/api/admin/bank-requests/{B.uid}/reject", {"reason": "x"}),
                           ("POST", f"/api/admin/users/{B.uid}/revoke-bank", {"reason": "x"}), ("GET", "/api/admin/audit", None)):
            for api, who in ((b_, "victim"), (Api(anon), "anonymous")):
                r = api.req(m, p, json=body) if body is not None else api.req(m, p)
                rec("F1", f"{who} token: {m} {p} → 401/403", r.status_code in (401, 403), f"HTTP {r.status_code}", "P0")
        r = b_.req("POST", "/api/bank-access/request", json={"fullName": "QA Applicant", "country": "IN", "bankName": "RecoverAI Demo Bank (fictional)",
                                                              "employeeId": "DEMO-0001", "designation": "Fraud analyst", "note": "qa"})
        rec("K-ROLE", "victim phone account cannot apply for bank access → 409", r.status_code == 409, f"HTTP {r.status_code}", "P1")
        bank = Api(staff_token("bank"))
        r = bank.req("POST", "/api/cases", json={"country": "IN", "language": "en"})
        rec("K-ROLE", "analyst (staff) token on victim route → 403", r.status_code == 403, f"HTTP {r.status_code}", "P1")
        r = bank.req("GET", "/api/admin/bank-requests")
        rec("K-ROLE", "analyst token on admin API → 403", r.status_code == 403, f"HTTP {r.status_code}", "P0")

        # ---------------- B6: 412 on every gated endpoint (B is incomplete)
        for m, p, body in (("POST", "extract", None), ("POST", "plan", None), ("POST", "drafts", None), ("POST", "evidence-pack", None),
                           ("POST", "send-to-bank/preview", None), ("POST", "send-to-bank", {"confirmed": True, "confirmationToken": "x"})):
            r = b_.req(m, f"/api/cases/{B_cid}/{p}", json=body)
            d = (r.json() if r.headers.get("content-type", "").startswith("application/json") else {}).get("detail") or {}
            rec("B6", f"incomplete profile: {p} → 412 PROFILE_INCOMPLETE", r.status_code == 412 and d.get("code") == "PROFILE_INCOMPLETE"
                and d.get("missing") == ["postalCode", "primaryBank"], f"HTTP {r.status_code} {d.get('code')}", "P1")

        # ---------------- I2: signed URLs
        if purl:
            q = parse_qs(urlparse(purl).query)
            exp = int((q.get("X-Goog-Expires") or ["0"])[0])
            rec("I2", "evidence signed URL expires ≤ 15 min", 0 < exp <= 900, f"X-Goog-Expires={exp}", "P1")
            rec("I2", "signed URL works for its own object now", httpx.get(purl, timeout=30).status_code == 200, "", "P1")
            bucket = urlparse(purl).path.split("/")[1]
            r = httpx.get(f"https://storage.googleapis.com/{bucket}", timeout=30)
            rec("I2", "evidence bucket not listable anonymously", r.status_code in (401, 403), f"HTTP {r.status_code}", "P1")
            r = httpx.get(f"https://storage.googleapis.com/storage/v1/b/{bucket}/o", headers={"Authorization": f"Bearer {tb}"}, timeout=30)
            rec("I2", "evidence bucket not listable with a Firebase user token", r.status_code in (401, 403), f"HTTP {r.status_code}", "P1")
            tampered = re.sub(r"(X-Goog-Signature=)([0-9a-f])", lambda m: m.group(1) + ("0" if m.group(2) != "0" else "1"), purl)
            rec("I2", "tampered signature rejected", httpx.get(tampered, timeout=30).status_code in (400, 401, 403), "", "P1")
            other = purl.replace(urlparse(purl).path, urlparse(purl).path.rsplit("/", 1)[0] + "/other.png")
            rec("I2", "signed URL cannot be re-pointed at another object", httpx.get(other, timeout=30).status_code in (400, 401, 403), "", "P1")
            Path("/workspace/qa_logs/signed_url_for_expiry.txt").write_text(f"{time.time()}\n{purl}\n")  # re-checked after 15 min
        else:
            rec("I2", "evidence previewUrl present", False, f"upload HTTP {img.status_code}", "P1")

        # ---------------- C5: upload validation
        big = b"\x89PNG\r\n\x1a\n" + b"0" * (15 * 1024 * 1024)
        r = b_.req("POST", f"/api/cases/{B_cid}/evidence/upload-url", json={"mimeType": "image/png", "sizeBytes": len(big)})
        rec("C5", "15 MB image → 413 at upload-url", r.status_code == 413, f"HTTP {r.status_code}", "P1")
        r = b_.req("POST", f"/api/cases/{B_cid}/evidence/upload-url", json={"mimeType": "application/x-msdownload", "sizeBytes": 100})
        rec("C5", ".exe MIME → 415", r.status_code == 415, f"HTTP {r.status_code}", "P1")
        exe = b"MZ\x90\x00" + b"\x00" * 2000
        r = b_.upload(B_cid, exe, "image/png", "evil.png")
        rec("C5", ".exe renamed to .png (MZ header) rejected by the server", r.status_code >= 400,
            f"HTTP {r.status_code} (server checks MIME + size only, not magic bytes)" if r.status_code < 400 else f"HTTP {r.status_code}", "P1")
        r = b_.upload(B_cid, b"", "image/png", "empty.png")
        rec("C5", "0-byte file rejected", r.status_code >= 400, f"HTTP {r.status_code}", "P1")
        r = b_.req("POST", f"/api/cases/{B_cid}/evidence", json={"type": "text", "textContent": "   "})
        rec("C5", "empty pasted text → 400", r.status_code == 400, f"HTTP {r.status_code}", "P2")

        # ---------------- E7 / E8 / F6: send path on A's sandbox case
        ext = a_.j("POST", f"/api/cases/{cid}/extract")
        exn = (ext.get("case") or {}).get("extraction") or {}
        rec("C4", "REST extract on the India fixture: UTR 612345678901 + ₹1,95,000 (model path, not heuristic)",
            "612345678901" in json.dumps(exn) and "195000" in json.dumps(exn).replace(",", ""), f"source={exn.get('source') or exn.get('model')}", "P0")
        a_.j("PATCH", f"/api/cases/{cid}/extraction", json={"fields": {"beneficiary.bank": "Sample Co-operative Bank"}, "confirm": True})
        a_.j("POST", f"/api/cases/{cid}/plan")
        dr = a_.j("POST", f"/api/cases/{cid}/drafts")
        pv = a_.j("POST", f"/api/cases/{cid}/send-to-bank/preview")
        rec("E4", "preview: destination SANDBOX + RecoverAI Demo Bank (fictional) + masked beneficiary",
            pv["summary"].get("destination") == "SANDBOX" and pv["summary"].get("bankName") == "RecoverAI Demo Bank (fictional)",
            json.dumps({k: pv['summary'].get(k) for k in ('destination', 'bankName', 'publicRef')}, ensure_ascii=False), "P0")
        tok = pv["confirmationToken"]
        bad = tok[:-3] + ("aaa" if not tok.endswith("aaa") else "bbb")
        r = a_.req("POST", f"/api/cases/{cid}/send-to-bank", json={"confirmationToken": bad, "confirmed": True})
        rec("E7", "tampered confirmation token → 409/400/403", r.status_code in (400, 403, 409), f"HTTP {r.status_code}", "P1")
        a_.j("PATCH", f"/api/cases/{cid}/extraction", json={"fields": {"beneficiary.bank": "Sample Co-operative Bank Ltd"}})
        r = a_.req("POST", f"/api/cases/{cid}/send-to-bank", json={"confirmationToken": tok, "confirmed": True})
        rec("E7", "fact edited after preview → 409 'Details changed — please review again'",
            r.status_code == 409 and "Details changed" in r.text, f"HTTP {r.status_code} {r.text[:80]}", "P1")
        a_.j("PATCH", f"/api/cases/{cid}/extraction", json={"fields": {"beneficiary.bank": "Sample Co-operative Bank"}})
        r = a_.req("POST", f"/api/cases/{cid}/send-to-bank", json={"confirmationToken": tok, "confirmed": False})
        rec("E4", "send without the confirm checkbox → 400", r.status_code == 400, f"HTTP {r.status_code}", "P0")
        before = {x["id"] for x in bank.j("GET", "/api/bank/cases")["cases"]}
        tok = a_.j("POST", f"/api/cases/{cid}/send-to-bank/preview")["confirmationToken"]
        import threading
        clients = [Api(ta) for _ in range(5)]
        barrier = threading.Barrier(5)

        def fire(c):
            barrier.wait()  # all five leave together
            return c.req("POST", f"/api/cases/{cid}/send-to-bank", json={"confirmationToken": tok, "confirmed": True})
        with cf.ThreadPoolExecutor(5) as pool:
            futs = [pool.submit(fire, c) for c in clients]
            codes = sorted(f.result().status_code for f in futs)
        time.sleep(6)
        r = a_.req("POST", f"/api/cases/{cid}/send-to-bank", json={"confirmationToken": tok, "confirmed": True})
        codes.append(r.status_code)
        new = [x for x in bank.j("GET", "/api/bank/cases")["cases"] if x["id"] not in before and x.get("caseId") == cid]
        rec("E8", "5 parallel confirms + 1 replay → exactly one bank case (one 200, rest 409)", len(new) == 1 and codes.count(200) == 1, f"send HTTP codes {codes}; bank cases {len(new)}", "P1")
        bc = bank.j("GET", f"/api/bank/cases/{new[0]['id']}")["case"] if new else {}
        rec("E9", "bank case sandbox=true, received by demo bank; live queue untouched",
            bc.get("sandbox") is True and bc.get("receivingBankName") == "RecoverAI Demo Bank (fictional)", "", "P0")
        direct = Api(ta, RUN_URL)  # bypass the Hosting CDN (see K-CACHE)
        msgs_before = len(direct.j("GET", f"/api/cases/{cid}/messages")["messages"])
        cases_before = len([x for x in bank.j("GET", "/api/bank/cases")["cases"] if x.get("caseId") == cid])
        Path("/workspace/qa_logs/probe_bank_cases.txt").open("a").write("\n".join(x["id"] for x in new) + "\n")
        # F6: the bank case keeps only the envelope header (no payload), so an identical live replay is not possible from
        # here; republishing the header alone is rejected 400 and dead-letters after 5 attempts (seen on 18 Oct — do
        # not do it). Dedupe on redelivery is covered by backend/tests/test_events.py (LocalBus.redeliver).
        rec("F6", "live Pub/Sub redelivery of an identical message", None,
            "not replayable from the client side; covered by unit tests (test_events) — see results doc", "P1")
        # E11 internal ids: PDF + reply texts
        pack = a_.j("POST", f"/api/cases/{cid}/evidence-pack", params={"rebuild": "true"})
        rec("I2", "evidence-pack URL expiresInSeconds ≤ 900", pack.get("expiresInSeconds", 9999) <= 900, str(pack.get("expiresInSeconds")), "P1")
        pdf = httpx.get(a_.u(pack["url"]), timeout=60).content
        Path("/workspace/qa_logs/probe_pack.pdf").write_bytes(pdf)
        txt = subprocess.run(["pdftotext", "-layout", "/workspace/qa_logs/probe_pack.pdf", "-"], capture_output=True, text=True).stdout
        bcid = (new[0]["id"] if new else "zzzz")
        rec("E11", "evidence-pack PDF: no internal ids (c_/b_/uid), shows RAI- ref", cid not in txt and bcid not in txt and A.uid not in txt
            and not re.search(r"\b[bc]_[0-9a-f]{12,}", txt) and "RAI-IN-" in txt, "", "P1")
        rec("D3", "evidence-pack PDF has the SANDBOX — NOT SUBMITTED watermark + an Evidence (SHA-256) section",
            "SANDBOX — NOT SUBMITTED" in txt and "SHA-256" in txt, "", "P1")
        rec("K-PDF", "evidence pack names the fictional demo bank, no real receiving bank", "RecoverAI Demo Bank (fictional)" in txt, "", "P1")
        r = a_.j("POST", f"/api/cases/{cid}/withdraw-consent", json={"confirmed": True})
        msgs = direct.j("GET", f"/api/cases/{cid}/messages")["messages"]
        shown = " ".join(m.get("text") or "" for m in msgs if m.get("role") != "system_event")
        rec("E11", "co-pilot replies show no internal ids", cid not in shown and bcid not in shown and not re.search(r"\bb_[0-9a-f]{8,}", shown), "", "P1")
        # I1: API responses don't carry server secrets
        raw = a_.req("GET", f"/api/cases/{cid}").text + direct.req("GET", f"/api/cases/{cid}/messages").text
        rec("I1", "case API responses carry no tokens/secrets/other uids", not re.search(r"private_key|BEGIN PRIVATE|AIza[0-9A-Za-z_-]{20}|turnTimes|"
                                                                                        + re.escape(B.uid), raw), "", "P0")

        # ---------------- K: max 3 open cases per user
        made = []
        codes = []
        for _ in range(3):
            r = a_.req("POST", "/api/cases", json={"country": "IN", "language": "en"})
            codes.append(r.status_code)
            if r.status_code == 200:
                made.append(r.json()["caseId"])
        rec("K-MAXCASES", "4th open case → 429 with a clear message", codes[:2] == [200, 200] and codes[2] == 429,
            f"codes for cases 2-4: {codes}", "P2")

        # ---------------- I3 headers
        for url in (SITE + "/", SITE + "/api/health"):
            hd = httpx.get(url, timeout=30).headers
            rec("I3", f"HSTS on {url.replace(SITE, '') or '/'}", "strict-transport-security" in hd, "", "P2")
            rec("I3", f"X-Content-Type-Options nosniff on {url.replace(SITE, '') or '/'}", hd.get("x-content-type-options") == "nosniff",
                f"missing" if "x-content-type-options" not in hd else hd["x-content-type-options"], "P2")
            rec("I3", f"Content-Security-Policy on {url.replace(SITE, '') or '/'}", "content-security-policy" in hd, "absent" if "content-security-policy" not in hd else "", "P2")
        hd = httpx.get(SITE + "/", timeout=30).headers
        rec("I3", "Permissions-Policy allows microphone=(self) (no microphone=())", "microphone=(self)" in hd.get("permissions-policy", ""),
            hd.get("permissions-policy", ""), "P2")
    finally:
        A.delete()
        B.delete()
        if anon:
            httpx.post(f"{IDT}:delete?key={api_key()}", json={"idToken": anon}, timeout=30)
    print(f"probe took {time.time() - t0:.0f}s")
    dump(a.out)
    return 0 if not any(r["status"] == "FAIL" and r["pri"] == "P0" for r in __import__("qa_common").RESULTS) else 1


if __name__ == "__main__":
    sys.exit(main())
