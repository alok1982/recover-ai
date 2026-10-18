#!/usr/bin/env python3
"""D5 deadline / escalation detail check on the live API (throw-away +91 90000 01111, deleted at the end)."""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from qa_common import COMPLETE_IN, RUN_URL, Api, Throwaway, dump, rec  # noqa: E402
from copilot_api_checks import story_case  # noqa: E402

T = Throwaway("+919000001111", profile=COMPLETE_IN)
try:
    api = T.api
    cid, _ = story_case(api, "en", "D5")
    api.j("PATCH", f"/api/cases/{cid}/steps/report_bank", json={"status": "done", "reference": "QA-BANK-CMP-42"})
    r = api.j("POST", f"/api/cases/{cid}/clock", json={"addDays": 5})
    clocks = r["case"].get("clocks") or []
    st = {c.get("id") or c.get("label"): c.get("status") for c in clocks}
    # PRD: the RBI 5-day dual-report clock is 'recommended' (advisory) until the rule's effective_from 2027-01-01, so it
    # must NOT turn amber yet (the plan's 'amber' expectation conflicts with the PRD; see the results doc).
    rec("D5", "time-travel +5 days → 5-day RBI clock stays 'recommended' (PRD: advisory until 2027-01-01); Ombudsman clock running",
        st.get("dual_report_5d") == "recommended" and st.get("ombudsman_30d") in ("pending", "running", "due_soon", "ok"), json.dumps(st)[:300], "P0")
    r = api.j("POST", f"/api/cases/{cid}/clock", json={"jumpToDay": 31})
    cards = [m["card"] for m in r["messages"] if m.get("card")]
    esc = next((c for c in cards if c["kind"] == "escalation"), None)
    data = (esc or {}).get("data") or {}
    blob = json.dumps(esc, ensure_ascii=False) if esc else ""
    ref = r["case"].get("publicRef")
    draft_en = (data.get("draft") or {}).get("en") or ""
    rec("D5", "day 31 → escalation card: bankComplaintDate + RAI- ref + user's bank ref; Ombudsman draft cites date + both refs",
        esc is not None and "Ombudsman" in blob and bool(data.get("bankComplaintDate")) and data.get("publicRef") == ref
        and ref in draft_en and "QA-BANK-CMP-42" in draft_en and bool(re.search(r"\d{1,2} \w{3} 2026", draft_en)),
        f"bankComplaintDate={data.get('bankComplaintDate')}; publicRef={data.get('publicRef')}; RAI ref in draft={ref in draft_en}; "
        f"bank ref in draft={'QA-BANK-CMP-42' in draft_en}", "P0")
    direct = Api(api.c.headers["Authorization"].split()[1], RUN_URL)
    n1 = sum(1 for m in direct.j("GET", f"/api/cases/{cid}/messages")["messages"] if (m.get("card") or {}).get("kind") == "escalation")
    api.j("GET", f"/api/cases/{cid}")  # lazy evaluation on load (= page refresh)
    api.j("GET", f"/api/cases/{cid}")
    n2 = sum(1 for m in direct.j("GET", f"/api/cases/{cid}/messages")["messages"] if (m.get("card") or {}).get("kind") == "escalation")
    rec("D5", "refresh does not duplicate the proactive escalation message", n1 == 1 and n2 == 1, f"{n1} → {n2}", "P0")
    api.req("DELETE", f"/api/cases/{cid}")
    # E11 variant: case shared with the (demo) bank, bank step done WITHOUT a user reference → the Ombudsman draft must
    # cite the RAI- reference, never the internal bank case id
    cid, _ = story_case(api, "en", "D5b")
    pv = api.j("POST", f"/api/cases/{cid}/send-to-bank/preview")
    sent = api.j("POST", f"/api/cases/{cid}/send-to-bank", json={"confirmationToken": pv["confirmationToken"], "confirmed": True})["case"]
    Path("/workspace/qa_logs/probe_bank_cases.txt").open("a").write(sent["bankCaseId"] + "\n")
    api.j("PATCH", f"/api/cases/{cid}/steps/report_bank", json={"status": "done"})
    r = api.j("POST", f"/api/cases/{cid}/clock", json={"jumpToDay": 31})
    esc = next((m["card"] for m in r["messages"] if (m.get("card") or {}).get("kind") == "escalation"), None)
    blob = json.dumps(esc, ensure_ascii=False) if esc else ""
    esc = (esc or {}).get("data") if esc else None  # card fields live under card.data (the QA run read the top level)
    rec("E11", "Ombudsman draft (no user bank reference) shows the RAI- ref, not the internal bank case id",
        esc is not None and sent["bankCaseId"] not in blob and not re.search(r"\bb_[0-9a-f]{12,}", blob),
        f"internal id in draft={sent['bankCaseId'] in blob}; RAI ref in draft={sent.get('publicRef') in blob}", "P1")
    rec("D5", "day 31 escalation card cites the bank complaint date + a reference", esc is not None and bool(esc.get("bankComplaintDate"))
        and bool(esc.get("bankReference")), f"bankComplaintDate={esc.get('bankComplaintDate') if esc else None}", "P0")
    api.j("POST", f"/api/cases/{cid}/withdraw-consent", json={"confirmed": True})
    api.req("DELETE", f"/api/cases/{cid}")
finally:
    T.delete()
dump("/workspace/qa_logs/deadline.json")
