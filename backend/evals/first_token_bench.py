"""QA BUG-07: measure the co-pilot first-token latency through the real chat pipeline (evaluate → guard → router →
co-pilot) on live Vertex AI with the production task models. Reports p50/p90 for: guard, co-pilot first token
(from co-pilot start) and end-to-end first token (from the request).

    cd backend && ../.venv/bin/python -m evals.first_token_bench [--n 24] [--tag label]
"""
from __future__ import annotations

import argparse
import asyncio
import json
import time

from . import common  # noqa: F401
from .common import fresh_state
from .run import RESULTS, _live_llm, _mock_llm, build_cases

TURNS = [("follow_up", "en", "What happens next with my case?"), ("follow_up", "hi", "अब आगे क्या होगा?"),
         ("consent", "en", "Is it safe to share this with my bank?"), ("filings", "hi", "मुझे अब क्या करना चाहिए?"),
         ("follow_up", "ms", "Apa yang berlaku seterusnya?"), ("filings", "en", "What should I do now?"),
         ("follow_up", "en", "When is my deadline?"), ("consent", "hi", "क्या मेरा पैसा पक्का वापस मिलेगा?")]


def q(a, p):
    a = sorted(a)
    return a[min(len(a) - 1, int(round(p * (len(a) - 1))))] if a else None


async def main_async(n: int, tag: str):
    from fastapi.testclient import TestClient
    from app import actions
    from app.main import create_app
    from app.routers.cases import ChatReq, chat_events

    fresh_state()
    _mock_llm()
    items = []
    with TestClient(create_app()) as client:
        for i in range(n):
            stg, lang, text = TURNS[i % len(TURNS)]
            country = "MY" if lang == "ms" else "IN"
            items.append((build_cases(client, stg, country, lang, f"ft_{i}"), text))
    _live_llm()
    guard_ms: dict[str, float] = {}
    orig = actions.guard_turn

    async def timed_guard(case_id, text, lang):
        t = time.perf_counter()
        try:
            return await orig(case_id, text, lang)
        finally:
            guard_ms[case_id] = (time.perf_counter() - t) * 1000
    actions.guard_turn = timed_guard
    import app.routers.cases as rc
    rc.actions.guard_turn = timed_guard
    rows = []
    for cid, text in items:  # sequential: latency, not throughput
        t0 = time.perf_counter()
        first = None
        model_ft = None
        async for ev in chat_events(cid, ChatReq(text=text)):
            if ev.get("type") == "token" and first is None:
                first = (time.perf_counter() - t0) * 1000
            if ev.get("type") == "done":
                model_ft = ev.get("firstTokenMs")
        rows.append({"caseId": cid, "text": text, "e2eFirstTokenMs": round(first or -1), "copilotFirstTokenMs": model_ft,
                     "guardMs": round(guard_ms.get(cid, 0))})
        print(json.dumps(rows[-1], ensure_ascii=False))
    e2e = [r["e2eFirstTokenMs"] for r in rows if r["e2eFirstTokenMs"] > 0]
    out = {"n": len(rows), "e2e_first_token_ms": {"p50": q(e2e, .5), "p90": q(e2e, .9)},
           "copilot_first_token_ms": {"p50": q([r["copilotFirstTokenMs"] for r in rows if r["copilotFirstTokenMs"]], .5),
                                      "p90": q([r["copilotFirstTokenMs"] for r in rows if r["copilotFirstTokenMs"]], .9)},
           "guard_ms": {"p50": q([r["guardMs"] for r in rows], .5), "p90": q([r["guardMs"] for r in rows], .9)}, "rows": rows}
    (RESULTS / f"first_token__{tag}.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))
    print(json.dumps({k: v for k, v in out.items() if k != "rows"}))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=24)
    ap.add_argument("--tag", default="baseline")
    a = ap.parse_args()
    asyncio.run(main_async(a.n, a.tag))
