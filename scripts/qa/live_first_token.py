#!/usr/bin/env python3
"""QA BUG-07 / C1 on the live build: time to the first streamed co-pilot token (real model text, measured by the
client from the request start, through Hosting). Throw-away +91 90000 01112, deleted at the end.

  python scripts/qa/live_first_token.py [--out /workspace/qa_logs/fix/first_token_live.json]
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from qa_common import COMPLETE_IN, Api, Throwaway  # noqa: E402
from copilot_api_checks import story_case  # noqa: E402

CONVERSATIONAL = ["What happens next with my case?", "Is it safe to share this with my bank?", "अब आगे क्या होगा?",
                  "What should I tell the 1930 operator?", "क्या मेरा पैसा पक्का वापस मिलेगा?", "When is my deadline?",
                  "What is the Ombudsman?", "Should I block the scammer's number?", "मुझे बैंक को कब बताना चाहिए?",
                  "Can the bank freeze the money?"]


def q(a, p):
    a = sorted(a)
    return round(a[min(len(a) - 1, int(round(p * (len(a) - 1))))], 2) if a else None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="/workspace/qa_logs/fix/first_token_live.json")
    ap.add_argument("--chat-base", default=None, help="the app's VITE_CHAT_BASE (the Cloud Run URL): chat SSE goes there "
                    "directly because Firebase Hosting buffers streamed responses")
    a = ap.parse_args()
    T = Throwaway("+919000001114" if a.chat_base else "+919000001112", profile=COMPLETE_IN)
    rows = []
    try:
        api = T.api
        cids = [story_case(api, "en", f"FT{i}")[0] for i in range(2)]
        if a.chat_base:
            api = Api(T.api.c.headers["Authorization"].split()[1], a.chat_base)
        for i, text in enumerate(CONVERSATIONAL * 2):
            cid = cids[i % 2]
            evs, first, total = api.chat_timed(cid, {"text": text})
            done = next((e for e in evs if e.get("type") == "done"), {})
            cards = [e["card"]["kind"] for e in evs if e.get("type") == "card"]
            first_card = next((k for k, e in enumerate(evs) if e.get("type") == "card"), None)
            first_tok = next((k for k, e in enumerate(evs) if e.get("type") == "token"), None)
            rows.append({"text": text, "firstTokenS": round(first, 2) if first else None, "totalS": round(total, 2),
                         "serverFirstTokenMs": done.get("firstTokenMs"), "model": done.get("model"), "cards": cards,
                         "warningFirst": ("warning" not in cards) or (first_card is not None and (first_tok is None or first_card < first_tok))})
            print(json.dumps(rows[-1], ensure_ascii=False))
        # G1 on live: a recovery-scam message — warning card before any reply text
        evs, first, total = api.chat_timed(cids[0], {"text": "An agent says pay ₹5,000 processing fee and he will recover my money"})
        cards = [e["card"]["kind"] for e in evs if e.get("type") == "card"]
        fc = next((k for k, e in enumerate(evs) if e.get("type") == "card"), 10**9)
        ft = next((k for k, e in enumerate(evs) if e.get("type") == "token"), 10**9)
        g1 = {"cards": cards, "warningBeforeText": bool(cards) and cards[0] == "warning" and fc < ft, "firstTokenS": first}
        for cid in cids:
            api.req("DELETE", f"/api/cases/{cid}")
    finally:
        T.delete()
    ft = [r["firstTokenS"] for r in rows if r["firstTokenS"]]
    out = {"chatBase": a.chat_base or "hosting", "n": len(ft), "first_token_s": {"p50": q(ft, .5), "p90": q(ft, .9), "max": max(ft) if ft else None},
           "under_2s": sum(1 for x in ft if x <= 2.0), "models": sorted({r["model"] for r in rows if r["model"]}), "g1": g1, "rows": rows}
    Path(a.out).write_text(json.dumps(out, ensure_ascii=False, indent=1))
    print(json.dumps({k: v for k, v in out.items() if k != "rows"}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
