"""Shared helpers for the QA pass (scripts/qa/*). Live by default; throw-away accounts only.

Throw-away victim phones: +91 90000 011xx (fictional, never the user's own account). Every account created here is
deleted with DELETE /api/me (removes cases, evidence, profile and the Firebase login). Passwords for the analyst /
admin are read from deploy/.state and never printed."""
from __future__ import annotations

import json
import os
import sys
import time
import uuid
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[2]
STATE = ROOT / "deploy" / ".state"
FIX = ROOT / "fixtures"
IDT = "https://identitytoolkit.googleapis.com/v1/accounts"
SITE = os.environ.get("QA_SITE", "https://recoverai-511917.web.app")
RUN_URL = os.environ.get("QA_RUN_URL") or (STATE / "run_url").read_text().strip()
PROJECT = "recoverai-511917"
SEED = {"in_complete": "+919000000001", "in_incomplete": "+919000000002", "my_complete": "+60100000001"}
SEED_PW = "Demo@2026"
PROTECTED_UIDS = {"CJadzLLy9Talu2yqHFPoerBOd1r2"}  # the user's own account — never touched
PROTECTED_CASES = {"c_6a99e7503a40418fbaa0"}
COMPLETE_IN = {"fullName": "QA Tester", "country": "IN", "language": "en", "state": "Maharashtra", "district": "Pune",
               "postalCode": "411001", "primaryBank": "State Bank of India"}

RESULTS: list[dict] = []


def api_key() -> str:
    return json.loads((STATE / "sdkconfig.json").read_text())["apiKey"]


def rec(tid: str, name: str, cond: bool | None, info: str = "", pri: str = "") -> bool:
    """Record one check. cond None = warning/partial."""
    st = "PASS" if cond is True else ("WARN" if cond is None else "FAIL")
    RESULTS.append({"id": tid, "name": name, "status": st, "info": info[:400], "pri": pri})
    print(f"{st:4} [{tid}] {name}" + (f" — {info[:300]}" if info else ""), flush=True)
    return cond is True


def dump(path: str | Path) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(RESULTS, ensure_ascii=False, indent=1))
    n = {s: sum(r["status"] == s for r in RESULTS) for s in ("PASS", "FAIL", "WARN")}
    print("SUMMARY", json.dumps(n))


def phone_email(e164: str) -> str:
    return e164.lstrip("+") + "@phone.recoverai.app"


def sign_in(email: str, pw: str) -> httpx.Response:
    return httpx.post(f"{IDT}:signInWithPassword?key={api_key()}",
                      json={"email": email, "password": pw, "returnSecureToken": True}, timeout=30)


def phone_login(e164: str, pw: str = SEED_PW) -> httpx.Response:
    return sign_in(phone_email(e164), pw)


def token_for(e164: str, pw: str = SEED_PW) -> str:
    r = phone_login(e164, pw)
    r.raise_for_status()
    return r.json()["idToken"]


def staff_token(which: str) -> str:
    email = {"bank": "analyst@recoverai-demo.example", "admin": "admin@recoverai-demo.example"}[which]
    pw = (STATE / ("bank_password" if which == "bank" else "admin_password")).read_text().strip()
    r = sign_in(email, pw)
    r.raise_for_status()
    return r.json()["idToken"]


class Api:
    def __init__(self, token: str | None, base: str = SITE):
        self.base = base.rstrip("/")
        h = {"Authorization": f"Bearer {token}"} if token else {}
        self.c = httpx.Client(timeout=180, headers=h)

    def u(self, p: str) -> str:
        return p if p.startswith("http") else self.base + p

    def req(self, method: str, p: str, **kw) -> httpx.Response:
        return self.c.request(method, self.u(p), **kw)

    def j(self, method: str, p: str, **kw):
        r = self.req(method, p, **kw)
        if r.status_code >= 400:
            raise RuntimeError(f"{method} {p} -> {r.status_code}: {r.text[:300]}")
        return r.json()

    def chat(self, cid: str, body: dict) -> list[dict]:
        evs = []
        with self.c.stream("POST", self.u(f"/api/cases/{cid}/chat"), json=body) as r:
            if r.status_code >= 400:
                r.read()
                raise RuntimeError(f"chat -> {r.status_code}: {r.text[:200]}")
            for line in r.iter_lines():
                if line.startswith("data: "):
                    evs.append(json.loads(line[6:]))
        return evs

    def chat_timed(self, cid: str, body: dict) -> tuple[list[dict], float | None, float]:
        """Returns events, seconds to first streamed token (None if no token), total seconds."""
        evs, first, t0 = [], None, time.time()
        with self.c.stream("POST", self.u(f"/api/cases/{cid}/chat"), json=body) as r:
            r.raise_for_status()
            for line in r.iter_lines():
                if line.startswith("data: "):
                    e = json.loads(line[6:])
                    if e.get("type") == "token" and first is None:
                        first = time.time() - t0
                    evs.append(e)
        return evs, first, time.time() - t0

    def upload(self, cid: str, data: bytes, mime: str, fname: str = "x.png") -> httpx.Response:
        u = self.req("POST", f"/api/cases/{cid}/evidence/upload-url", json={"mimeType": mime, "sizeBytes": len(data)})
        if u.status_code >= 400:
            return u
        u = u.json()
        r = httpx.put(self.u(u["url"]), content=data, headers={"Content-Type": mime, **(u.get("headers") or {})}, timeout=60)
        if r.status_code >= 400:
            return r
        return self.req("POST", f"/api/cases/{cid}/evidence", json={"type": "image", "gcsPath": u["path"], "mimeType": mime,
                                                                   "fileName": fname})


def kinds(evs):
    return [e["card"]["kind"] for e in evs if e.get("type") == "card"]


def card(evs, kind):
    return next((e["card"]["data"] for e in evs if e.get("type") == "card" and e["card"]["kind"] == kind), None)


def text(evs):
    return "".join(e.get("text", "") for e in evs if e.get("type") == "token")


def done(evs):
    return next((e for e in evs if e.get("type") == "done"), {})


class Throwaway:
    """A throw-away phone victim account created through the same Firebase REST call the app uses."""

    def __init__(self, e164: str, pw: str | None = None, profile: dict | None = None, terms: bool = True):
        assert e164.startswith("+9190000011"), "throw-away numbers only"
        self.e164, self.pw = e164, pw or ("Qa" + uuid.uuid4().hex[:8] + "7")
        r = httpx.post(f"{IDT}:signUp?key={api_key()}", json={"email": phone_email(e164), "password": self.pw,
                                                            "returnSecureToken": True}, timeout=30)
        if r.status_code == 400 and "EMAIL_EXISTS" in r.text:
            raise RuntimeError(f"{e164} already exists — clean it up first")
        r.raise_for_status()
        self.uid = r.json()["localId"]
        assert self.uid not in PROTECTED_UIDS
        self.api = Api(r.json()["idToken"])
        if terms:
            self.api.j("POST", "/api/me/terms", json={"version": self.api.j("GET", "/api/me")["termsCurrent"]})
        if profile is not None:
            self.api.j("PUT", "/api/me/profile", json={"profile": profile})

    def fresh(self) -> Api:
        self.api = Api(phone_login(self.e164, self.pw).json()["idToken"])
        return self.api

    def delete(self) -> bool:
        try:
            r = self.fresh().req("DELETE", "/api/me")
            # the app deletes the Firebase login from the client (lib/auth.ts deleteUser); do the same via REST
            httpx.post(f"{IDT}:delete?key={api_key()}", json={"idToken": self.api.c.headers["Authorization"].split()[1]}, timeout=30)
            gone = phone_login(self.e164, self.pw).status_code == 400  # INVALID_LOGIN_CREDENTIALS
            print(f"cleanup: {self.e164[:-4]}xxxx DELETE /api/me → {r.status_code}; login gone={gone}")
            return gone
        except Exception as e:  # noqa: BLE001
            print("cleanup failed", self.e164, e, file=sys.stderr)
            return False
