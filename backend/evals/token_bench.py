"""Gemini tokens per complete India demo case (README demo story), from the response usage metadata of every Vertex AI
call (google-genai SDK spy in evals/common.py: generate_content + generate_content_stream, which also covers the ADK
co-pilot). Runs the real backend in-process against the same Vertex models and prompts as Cloud Run: the production
task-model env vars are copied below. Store, blobs and event bus are in-memory/local, so the bank receiver runs inline.

    cd backend && ../.venv/bin/python -m evals.token_bench [--cases 3] [--out ../docs/qa/bench/tokens_20261018.json]
"""
from __future__ import annotations

import os

PROD_ENV = {  # from `gcloud run services describe recoverai-api` (revision recoverai-api-00018-t5d), non-secret values
    "GEMINI_LOCATION": "global", "GEMINI_MODEL": "gemini-3.8-flash", "GEMINI_LITE_MODEL": "gemini-3.5-flash-lite",
    "GEMINI_PRO_MODEL": "gemini-3.1-pro-preview", "COPILOT_HISTORY_MESSAGES": "12", "GEMINI_MODEL_GUARD": "lite",
    "GEMINI_MODEL_INTAKE": "gemini-3.1-flash-lite", "GEMINI_MODEL_INTAKE_ESCALATE": "flash",
    "GEMINI_MODEL_TRANSCRIBE": "gemini-3.1-flash-lite", "GEMINI_MODEL_PLAN_EXPLAIN": "lite",
    "GEMINI_MODEL_DRAFTS": "gemini-3.1-flash-lite", "GEMINI_MODEL_BANK_REASON": "lite", "GEMINI_MODEL_COPILOT": "lite",
    "GEMINI_MODEL_REPLY_FALLBACK": "lite", "GEMINI_MODEL_POST_CHECK_REGEN": "lite",
    "GEMINI_FALLBACK_GUARD": "gemini-3.1-flash-lite", "CHAT_LIGHT_MODEL": "", "DEMO_MODE": "true",
    "COPILOT_RUNTIME": "cloudrun", "ENABLE_ML_SCORE": "true",
    "VERTEX_SEARCH_SERVING_CONFIG": "projects/recoverai-511917/locations/global/collections/default_collection/engines/"
                                    "recoverai-rules-app/servingConfigs/default_search",
}
os.environ.update(PROD_ENV)

import argparse  # noqa: E402
import json  # noqa: E402
import time  # noqa: E402
from collections import defaultdict  # noqa: E402
from pathlib import Path  # noqa: E402

from . import common  # noqa: E402
from .common import USAGE, fresh_state, install_spy  # noqa: E402

FIX = Path(__file__).resolve().parents[2] / "fixtures"


def H(uid):
    return {"Authorization": f"Bearer mock:{uid}"}


def sse(client, cid, body, uid):
    r = client.post(f"/api/cases/{cid}/chat", json=body, headers=H(uid))
    r.raise_for_status()
    return [json.loads(x[6:]) for x in r.text.splitlines() if x.startswith("data: ")]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cases", type=int, default=3)
    ap.add_argument("--out", default=str(Path(__file__).resolve().parents[2] / "docs" / "qa" / "bench" / "tokens_20261018.json"))
    a = ap.parse_args()
    from fastapi.testclient import TestClient
    from app.config import reset_settings_cache
    from app.llm import set_llm
    from app.main import create_app

    reset_settings_cache()
    set_llm(None)
    fresh_state()
    install_spy()
    calls = USAGE["_"]
    cases = []
    with TestClient(create_app()) as client:
        for n in range(a.cases):
            uid = f"tokbench{n}"
            steps = []

            def step(name, fn):
                i0, t0 = len(calls), time.perf_counter()
                res = fn()
                steps.append({"step": name, "seconds": round(time.perf_counter() - t0, 2), "calls": calls[i0:]})
                return res
            cid = client.post("/api/cases", json={"country": "IN", "language": "hi"}, headers=H(uid)).json()["caseId"]
            step("1 typed message (guard + co-pilot)", lambda: sse(client, cid, {"text": "मैंने CBI वाले को 1,95,000 भेज दिए"}, uid))

            def evidence():
                data = (FIX / "in_upi_success.png").read_bytes()
                u = client.post(f"/api/cases/{cid}/evidence/upload-url", json={"mimeType": "image/png", "sizeBytes": len(data)}, headers=H(uid)).json()
                from app.storage import get_blobs  # local blob store (the signed-URL PUT route is mock-mode only)
                get_blobs().write_bytes(u["path"], data, "image/png")
                pr = type("R", (), {"status_code": "direct-write"})
                im = client.post(f"/api/cases/{cid}/evidence", json={"type": "image", "gcsPath": u["path"], "mimeType": "image/png"}, headers=H(uid)).json()
                assert "evidence" in im, (u, pr.status_code, im)
                tx = client.post(f"/api/cases/{cid}/evidence", json={"type": "text", "textContent": (FIX / "in_whatsapp_scam.txt").read_text()},
                                 headers=H(uid)).json()
                return sse(client, cid, {"trigger": "evidence_added", "evidenceIds": [im["evidence"]["id"], tx["evidence"]["id"]]}, uid)
            step("2 evidence → extraction (guard on pasted text + intake)", evidence)

            def confirm():
                client.patch(f"/api/cases/{cid}/extraction", json={"fields": {"beneficiary.bank": "Sample Co-operative Bank"}, "confirm": True},
                             headers=H(uid))
                return sse(client, cid, {"trigger": "facts_confirmed"}, uid)
            step("3 facts confirmed → plan", confirm)
            step("4 generate_all → drafts", lambda: sse(client, cid, {"trigger": "generate_all"}, uid))
            step("5 evidence pack PDF", lambda: client.post(f"/api/cases/{cid}/evidence-pack", headers=H(uid)).json())

            def share():
                pv = client.post(f"/api/cases/{cid}/send-to-bank/preview", headers=H(uid)).json()
                r = client.post(f"/api/cases/{cid}/send-to-bank", json={"confirmationToken": pv["confirmationToken"], "confirmed": True},
                                headers=H(uid)).json()
                bid = r["case"]["bankCaseId"]
                i0 = len(calls)
                for _ in range(120):  # local bus: the bank receiver runs in-process; wait for its Gemini reasoning call
                    if any(c["task"] == "bank_reason" for c in calls[i0 - 5:]):
                        break
                    time.sleep(0.25)
                time.sleep(1)
                return bid
            step("6 consent → share with bank (bank case receiver reasoning)", share)
            step("7 extra co-pilot question (optional)", lambda: sse(client, cid, {"text": "अब आगे क्या होगा?"}, uid))
            for s in steps:
                s["tokens"] = {k: sum(c[k] for c in s["calls"]) for k in ("in", "out", "think", "cached")}
            cases.append({"caseId": cid, "steps": steps})
            core = [s for s in steps if not s["step"].startswith("7")]
            print(json.dumps({"case": n + 1, "core_total": sum(s["tokens"]["in"] + s["tokens"]["out"] + s["tokens"]["think"] for s in core),
                              "per_step": {s["step"]: s["tokens"] for s in steps}}, ensure_ascii=False), flush=True)

    def agg(filter_core: bool):
        by_task, by_model, tot = defaultdict(lambda: defaultdict(int)), defaultdict(lambda: defaultdict(int)), defaultdict(int)
        for c in cases:
            for s in c["steps"]:
                if filter_core and s["step"].startswith("7"):
                    continue
                for x in s["calls"]:
                    for k in ("in", "out", "think"):
                        by_task[x["task"]][k] += x[k]
                        by_model[x["model"]][k] += x[k]
                        tot[k] += x[k]
                    by_task[x["task"]]["calls"] += 1
                    by_model[x["model"]]["calls"] += 1
        n = len(cases)
        f = lambda d: {k: round(v / n, 1) for k, v in d.items()}  # noqa: E731
        return {"avg_total": round((tot["in"] + tot["out"] + tot["think"]) / n), "avg": f(tot),
                "by_task": {k: f(v) for k, v in by_task.items()}, "by_model": {k: f(v) for k, v in by_model.items()}}
    out = {"method": "local in-process backend, same Vertex models/prompts as Cloud Run; usage_metadata from every call",
           "cases": a.cases, "core": agg(True), "with_extra_question": agg(False), "raw": cases}
    Path(a.out).write_text(json.dumps(out, ensure_ascii=False, indent=1, default=str))
    print(json.dumps({k: out[k] for k in ("core", "with_extra_question")}, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
