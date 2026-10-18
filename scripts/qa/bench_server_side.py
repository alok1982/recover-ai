import json, re, statistics
from datetime import datetime
live = json.load(open("docs/qa/bench/live_20261018.json"))
req = json.load(open("/workspace/qa_logs/bench_reqlogs.json"))
gem = json.load(open("/workspace/qa_logs/bench_gemini_logs.json"))
trial_cases = live["caseIds"][:20]
def ts(s): return datetime.fromisoformat(s.replace("Z", "+00:00"))
def lat(e):
    l = (e.get("httpRequest") or {}).get("latency") or "0s"
    return float(l.rstrip("s"))
by = {}
for e in req:
    u = e["httpRequest"]["requestUrl"]
    m = re.search(r"/api/cases/(c_[0-9a-f]+)/(.*?)(\?|$)", u)
    if m: by.setdefault(m.group(1), []).append((ts(e["timestamp"]), m.group(2), lat(e), e["httpRequest"].get("status")))
def pct(a, p):
    a = sorted(a); k = (len(a)-1)*p; f = int(k); c = min(f+1, len(a)-1); return round(a[f]+(a[c]-a[f])*(k-f), 2)
def st(a): return {"n": len(a), "p50": pct(a, .5), "p95": pct(a, .95), "max": round(max(a), 2)} if a else None
rows = []
for i, cid in enumerate(trial_cases):
    t = live["trials"][i]
    ev = sorted(by.get(cid, []))
    chats = [x for x in ev if x[1] == "chat"]
    send = [x for x in ev if x[1] == "send-to-bank"]
    pack = [x for x in ev if x[1] == "evidence-pack"]
    r = {"caseId": cid}
    if len(chats) >= 3:
        r["extractServerS"] = round(chats[0][2], 2); r["draftsTurnServerS"] = round(chats[2][2], 2)
    if pack: r["pdfRebuildServerS"] = round(pack[0][2], 2)
    if send and t.get("bankDocCreateTime"):
        r["bankDocCreatedAfterSendStartS"] = round((ts(t["bankDocCreateTime"]) - send[0][0]).total_seconds(), 2)
        r["sendServerS"] = round(send[0][2], 2)
    tok = {}
    for g in gem:
        p = g["jsonPayload"]
        if p.get("caseId") == cid:
            d = tok.setdefault(p["step"], {"calls": 0, "in": 0, "out": 0, "model": set()})
            d["calls"] += 1; d["in"] += p.get("promptTokens") or 0; d["out"] += (p.get("outputTokens") or 0) + (p.get("thoughtsTokens") or 0)
            d["model"].add(p["model"])
    r["geminiCallsLogged"] = {k: {**v, "model": sorted(v["model"])} for k, v in tok.items()}
    rows.append(r)
summ = {k: st([r[k] for r in rows if k in r]) for k in ("extractServerS", "draftsTurnServerS", "pdfRebuildServerS", "bankDocCreatedAfterSendStartS", "sendServerS")}
steps = sorted({s for r in rows for s in r["geminiCallsLogged"]})
summ["liveLoggedTokensPerCase"] = {s: {"avg_in": round(statistics.mean([r["geminiCallsLogged"].get(s, {}).get("in", 0) for r in rows])),
                                       "avg_out": round(statistics.mean([r["geminiCallsLogged"].get(s, {}).get("out", 0) for r in rows])),
                                       "avg_calls": round(statistics.mean([r["geminiCallsLogged"].get(s, {}).get("calls", 0) for r in rows]), 2)} for s in steps}
summ["liveLoggedTokensPerCaseTotal"] = sum(v["avg_in"] + v["avg_out"] for v in summ["liveLoggedTokensPerCase"].values())
json.dump({"source": "Cloud Logging, revision recoverai-api-00018-t5d, 15:45:50–15:58 UTC (21:15–21:28 IST): Cloud Run request logs (httpRequest.latency, timestamp) + app 'gemini_call' logs (usage_metadata)",
           "summary": summ, "rows": rows}, open("docs/qa/bench/live_server_side_20261018.json", "w"), indent=1, default=str)
print(json.dumps(summ, indent=1))
