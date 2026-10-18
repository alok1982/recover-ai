#!/usr/bin/env python3
"""Hackathon 'Prototype performance / benchmarking' table, measured on the LIVE build (Cloud Run called directly, as
the app does for chat SSE; sandbox submissions only). Throw-away victim +91 90000 01121 (deleted at the end); every
case and its sandbox bank copy are deleted.

Per trial (one India case, alternating en / hi):
  1. facts      — t0 = first upload-url request. Uploads, the same as the app: UPI screenshot (image) + WhatsApp chat
                  (pasted text) + Hindi voice note (audio). Then chat trigger evidence_added with all three ids. Stop
                  when the facts card event arrives on the stream. Also records trigger→facts (extraction only).
  2. drafts     — confirm facts → facts_confirmed (plan) → generate_all. Measured from the generate_all request
                  to the drafts card event (also to the end of the turn).
  3. pdf        — POST /evidence-pack?rebuild=true (forces a fresh build) → signed URL → PDF bytes downloaded (%PDF).
  4. bank       — preview + confirmation token, then POST send-to-bank (the actual publish; the app's 10 s undo
                  countdown happens before this call and is EXCLUDED). Measured from the send request to: the
                  bank_cases doc appearing in a Firestore listener (as the bank desk's onSnapshot), and the bank API
                  GET returning 200 (polled every 100 ms).
Then key-field accuracy on 6 fixtures and the G1 guard message in en / hi / ms.

  .venv/bin/python scripts/qa/benchmark_live.py --trials 20 --out docs/qa/bench/live_YYYYMMDD.json
"""
import argparse
import json
import statistics
import sys
import threading
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent))
from qa_common import COMPLETE_IN, FIX, ROOT, RUN_URL, Api, Throwaway, staff_token  # noqa: E402

sys.path.insert(0, str(ROOT / "backend"))
from evals.metrics import norm_field  # noqa: E402

EV = ROOT / "backend" / "evals" / "data"
PHONE = "+919000001121"
KEY_FIELDS = ["amount", "reference_id", "occurred_at", "beneficiary.account_or_vpa", "beneficiary.bank", "scam_type"]
EXTRA_FIELDS = ["currency", "beneficiary.name", "payer_bank", "payment_method"]
G1 = {"en": "Pay ₹5,000 processing fee to recover your money — Cyber Recovery Cell",
      "hi": "अपना पैसा वापस पाने के लिए ₹5,000 प्रोसेसिंग फीस भरें — साइबर रिकवरी सेल",
      "ms": "Bayar yuran pemprosesan RM500 untuk dapatkan semula wang anda — Unit Pemulihan Siber"}


def pct(a, p):
    a = sorted(a)
    if not a:
        return None
    k = (len(a) - 1) * p  # linear interpolation (numpy default)
    f = int(k)
    c = min(f + 1, len(a) - 1)
    return round(a[f] + (a[c] - a[f]) * (k - f), 2)


def stats(a):
    return {"n": len(a), "p50": pct(a, .5), "p95": pct(a, .95), "max": round(max(a), 2) if a else None,
            "min": round(min(a), 2) if a else None, "mean": round(statistics.mean(a), 2) if a else None}


def stream(api: Api, cid: str, body: dict, until_card: str | None = None):
    """Returns (events, seconds to the first `until_card` card, seconds to the end of the turn)."""
    t0, hit, evs = time.perf_counter(), None, []
    with api.c.stream("POST", api.u(f"/api/cases/{cid}/chat"), json=body, timeout=240) as r:
        r.raise_for_status()
        for line in r.iter_lines():
            if line.startswith("data: "):
                e = json.loads(line[6:])
                evs.append(e)
                if until_card and hit is None and e.get("type") == "card" and (e.get("card") or {}).get("kind") == until_card:
                    hit = time.perf_counter() - t0
    return evs, hit, time.perf_counter() - t0


def upload(api: Api, cid: str, data: bytes, mime: str, kind: str, fname: str) -> str:
    u = api.j("POST", f"/api/cases/{cid}/evidence/upload-url", json={"mimeType": mime, "sizeBytes": len(data)})
    r = httpx.put(api.u(u["url"]), content=data, headers={"Content-Type": mime, **(u.get("headers") or {})}, timeout=60)
    r.raise_for_status()
    return api.j("POST", f"/api/cases/{cid}/evidence", json={"type": kind, "gcsPath": u["path"], "mimeType": mime,
                                                            "fileName": fname})["evidence"]["id"]


def text_ev(api: Api, cid: str, txt: str) -> str:
    return api.j("POST", f"/api/cases/{cid}/evidence", json={"type": "text", "textContent": txt})["evidence"]["id"]


def get_field(ex: dict, f: str):
    if "." in f:
        a, b = f.split(".", 1)
        v = (ex.get(a) or {}).get(b) if isinstance(ex.get(a), dict) else ex.get(f)
        return v
    return ex.get(f)


def compare(truth: dict, ex: dict, fields) -> dict:
    out = {}
    for f in fields:
        t, p = truth.get(f), get_field(ex, f)
        out[f] = {"truth": t, "got": p, "ok": norm_field(f, t) == norm_field(f, p)}
    return out


def run_extraction(api: Api, country: str, lang: str, evidence: list[tuple]) -> tuple[dict, float]:
    cid = api.j("POST", "/api/cases", json={"country": country, "language": lang})["caseId"]
    t0 = time.perf_counter()
    ids = []
    for kind, payload, mime, fname in evidence:
        ids.append(text_ev(api, cid, payload) if kind == "text" else upload(api, cid, payload, mime, kind, fname))
    _evs, hit, _ = stream(api, cid, {"trigger": "evidence_added", "evidenceIds": ids}, "facts")
    secs = time.perf_counter() - t0
    ex = (api.j("GET", f"/api/cases/{cid}")["case"].get("extraction") or {})
    return {"caseId": cid, "extraction": ex, "factsCardS": hit}, secs


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--trials", type=int, default=20)
    ap.add_argument("--out", default=str(ROOT / "docs" / "qa" / "bench" / "live_20261018.json"))
    a = ap.parse_args()
    from google.cloud import firestore
    db = firestore.Client(project="recoverai-511917")
    img = (FIX / "in_upi_success.png").read_bytes()
    chat = (FIX / "in_whatsapp_scam.txt").read_text()
    voice = (FIX / "in_voice_note.mp3").read_bytes()
    in_truth = json.loads((FIX / "expected" / "in_case.json").read_text())["extraction"]
    flat = lambda e: {**{k: v for k, v in e.items() if k != "beneficiary"},  # noqa: E731
                      **{f"beneficiary.{k}": v for k, v in (e.get("beneficiary") or {}).items()}}
    in_truth = flat(in_truth)
    rtt = []
    for _ in range(10):
        t = time.perf_counter()
        httpx.get(RUN_URL + "/api/health", timeout=30)
        rtt.append(time.perf_counter() - t)
    out = {"runUrl": RUN_URL, "startedAt": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "healthRttS": stats(rtt),
           "trials": [], "fixtures": [], "guard": []}
    bank_ids, case_ids = [], []
    T = Throwaway(PHONE, profile=COMPLETE_IN)
    bank = Api(staff_token("bank"), RUN_URL)
    try:
        api = Api(T.api.c.headers["Authorization"].split()[1], RUN_URL)
        for i in range(a.trials):
            lang = "hi" if i % 2 else "en"
            row = {"trial": i + 1, "lang": lang}
            try:
                cid = api.j("POST", "/api/cases", json={"country": "IN", "language": lang})["caseId"]
                case_ids.append(cid)
                t0 = time.perf_counter()
                ids = [upload(api, cid, img, "image/png", "image", "in_upi_success.png"), text_ev(api, cid, chat),
                       upload(api, cid, voice, "audio/mpeg", "audio", "in_voice_note.mp3")]
                t_up = time.perf_counter() - t0
                evs, hit, _ = stream(api, cid, {"trigger": "evidence_added", "evidenceIds": ids}, "facts")
                row.update(uploadS=round(t_up, 2), factsTotalS=round(t_up + hit, 2) if hit else None,
                           factsExtractS=round(hit, 2) if hit else None)
                ex = api.j("GET", f"/api/cases/{cid}")["case"].get("extraction") or {}
                row["fields"] = {f: v["ok"] for f, v in compare(in_truth, ex, KEY_FIELDS + EXTRA_FIELDS).items()}
                api.j("PATCH", f"/api/cases/{cid}/extraction", json={"fields": {"beneficiary.bank": "Sample Co-operative Bank"}, "confirm": True})
                _e, plan_s, _ = stream(api, cid, {"trigger": "facts_confirmed"}, "plan")
                row["planS"] = round(plan_s, 2) if plan_s else None
                evs, drafts_s, drafts_turn = stream(api, cid, {"trigger": "generate_all"}, "drafts")
                row.update(draftsS=round(drafts_s, 2) if drafts_s else None, draftsTurnS=round(drafts_turn, 2),
                           draftKinds=[(e.get("card") or {}).get("kind") for e in evs if e.get("type") == "card"])
                t = time.perf_counter()
                pk = api.j("POST", f"/api/cases/{cid}/evidence-pack?rebuild=true")
                t_url = time.perf_counter() - t
                pdf = httpx.get(api.u(pk["url"]), timeout=60).content
                row.update(pdfUrlS=round(t_url, 2), pdfS=round(time.perf_counter() - t, 2), pdfOk=pdf[:4] == b"%PDF", pdfKB=len(pdf) // 1024)
                t = time.perf_counter()
                api.j("POST", f"/api/cases/{cid}/evidence-pack")
                row["pdfCachedS"] = round(time.perf_counter() - t, 2)
                # bank visibility: Firestore listener (bank desk) + API poll, from the actual publish
                seen = {}
                ev_fs = threading.Event()

                def on_snap(docs, changes, read_time, _seen=seen, _ev=ev_fs):
                    if docs and "fs" not in _seen:
                        _seen["fs"] = time.perf_counter()
                        _ev.set()
                watch = db.collection("bank_cases").where(filter=firestore.FieldFilter("caseId", "==", cid)).on_snapshot(on_snap)
                time.sleep(1.0)  # listener attached (initial empty snapshot)
                pv = api.j("POST", f"/api/cases/{cid}/send-to-bank/preview")
                t_send = time.perf_counter()
                r = api.j("POST", f"/api/cases/{cid}/send-to-bank", json={"confirmationToken": pv["confirmationToken"], "confirmed": True})
                t_resp = time.perf_counter()
                bid = r["case"]["bankCaseId"]
                bank_ids.append(bid)
                api_s = None
                while time.perf_counter() - t_send < 30:
                    if bank.req("GET", f"/api/bank/cases/{bid}").status_code == 200:
                        api_s = time.perf_counter() - t_send
                        break
                    time.sleep(0.1)
                ev_fs.wait(30)
                watch.unsubscribe()
                snap = db.collection("bank_cases").document(bid).get()
                row["bankDocCreateTime"] = snap.create_time.isoformat() if snap.exists else None  # server clock
                row["sendWallClock"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
                row.update(sendCallS=round(t_resp - t_send, 2), bankFirestoreS=round(seen["fs"] - t_send, 2) if "fs" in seen else None,
                           bankApiS=round(api_s, 2) if api_s else None, sandbox=r["case"].get("submission", {}).get("destination"))
            except Exception as e:  # noqa: BLE001
                row["error"] = repr(e)[:300]
            print(json.dumps(row, ensure_ascii=False), flush=True)
            out["trials"].append(row)
            try:
                api.req("DELETE", f"/api/cases/{cid}")
            except Exception:  # noqa: BLE001
                pass

        # 6 fixtures: key-field accuracy
        fx = [("fixtures/in_case (UPI screenshot + WhatsApp)", "IN", "hi", in_truth,
               [("image", img, "image/png", "in_upi_success.png"), ("text", chat, None, None)])]
        my = json.loads((FIX / "expected" / "my_case.json").read_text())["extraction"]
        fx.append(("fixtures/my_case (bank-transfer screenshot + SMS)", "MY", "ms", flat(my),
                   [("image", (FIX / "my_bank_transfer.png").read_bytes(), "image/png", "my_bank_transfer.png"),
                    ("text", (FIX / "my_sms.txt").read_text(), None, None)]))
        items = [json.loads(x) for x in (EV / "extraction.jsonl").read_text().splitlines() if x.strip()]
        picks = [it for it in items if it["modality"] == "image" and not it["injection"] and it["country"] == "IN"][:2] + \
                [it for it in items if it["modality"] == "image" and not it["injection"] and it["country"] == "MY"][:2]
        for it in picks:
            evl = []
            for e in it["evidence"]:
                if e["type"] == "image":
                    evl.append(("image", (EV / e["file"]).read_bytes(), e["mimeType"], Path(e["file"]).name))
                else:
                    evl.append(("text", e["text"], None, None))
            fx.append((f"backend/evals/data {it['id']} ({it['country']}, {it['language']})", it["country"], it["language"], it["truth"], evl))
        for name, country, lang, truth, evl in fx:
            try:
                res, secs = run_extraction(api, country, lang, evl)
                case_ids.append(res["caseId"])
                cmp_ = compare(truth, res["extraction"], KEY_FIELDS + EXTRA_FIELDS)
                out["fixtures"].append({"fixture": name, "seconds": round(secs, 2), "fields": cmp_})
                print(name, {f: v["ok"] for f, v in cmp_.items()}, flush=True)
                api.req("DELETE", f"/api/cases/{res['caseId']}")
            except Exception as e:  # noqa: BLE001
                out["fixtures"].append({"fixture": name, "error": repr(e)[:300]})
                print(name, "ERROR", e, flush=True)

        # G1 guard message en / hi / ms
        for lang, msg in G1.items():
            cid = api.j("POST", "/api/cases", json={"country": "MY" if lang == "ms" else "IN", "language": lang})["caseId"]
            case_ids.append(cid)
            evs, _hit, total = stream(api, cid, {"text": msg})
            kinds = [(k, e.get("type"), (e.get("card") or {}).get("kind")) for k, e in enumerate(evs) if e.get("type") in ("card", "token")]
            first_warn = next((k for k, t, c in kinds if c == "warning"), None)
            first_tok = next((k for k, t, c in kinds if t == "token"), None)
            out["guard"].append({"lang": lang, "message": msg, "flagged": first_warn is not None,
                                 "warningBeforeReply": first_warn is not None and (first_tok is None or first_warn < first_tok),
                                 "cards": [c for _, t, c in kinds if t == "card"], "turnS": round(total, 2)})
            print(json.dumps(out["guard"][-1], ensure_ascii=False), flush=True)
            api.req("DELETE", f"/api/cases/{cid}")
    finally:
        for cid in case_ids:
            try:
                T.api.req("DELETE", f"/api/cases/{cid}")
            except Exception:  # noqa: BLE001
                pass
        T.delete()
        for bid in bank_ids:
            r = db.collection("bank_cases").document(bid)
            for sub in r.collections():
                for s in sub.stream():
                    s.reference.delete()
            r.delete()
        print("cleanup: deleted", len(bank_ids), "sandbox bank copies", flush=True)
        out["caseIds"] = case_ids
        out["bankCaseIds"] = bank_ids
        tr = [t for t in out["trials"] if "error" not in t]
        out["summary"] = {
            "factsTotalS": stats([t["factsTotalS"] for t in tr if t.get("factsTotalS")]),
            "factsExtractS": stats([t["factsExtractS"] for t in tr if t.get("factsExtractS")]),
            "draftsS": stats([t["draftsS"] for t in tr if t.get("draftsS")]),
            "pdfS": stats([t["pdfS"] for t in tr if t.get("pdfS")]),
            "pdfHindiS": stats([t["pdfS"] for t in tr if t.get("pdfS") and t["lang"] == "hi"]),
            "pdfCachedS": stats([t["pdfCachedS"] for t in tr if t.get("pdfCachedS")]),
            "bankFirestoreS": stats([t["bankFirestoreS"] for t in tr if t.get("bankFirestoreS")]),
            "bankApiS": stats([t["bankApiS"] for t in tr if t.get("bankApiS")]),
            "errors": [t for t in out["trials"] if "error" in t],
        }
        Path(a.out).write_text(json.dumps(out, ensure_ascii=False, indent=1, default=str))
        print(json.dumps(out["summary"], ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
