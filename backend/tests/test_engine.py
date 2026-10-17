from datetime import datetime, timedelta, timezone

from app.rules.engine import compute_clocks, compute_plan, evaluate_clocks, explain_rule, get_playbook, load_playbooks, mark_step

UTC = timezone.utc
INCIDENT = datetime(2026, 10, 17, 8, 32, tzinfo=UTC)  # 17 Oct 2026 14:02 IST


def case(country="IN", incident=INCIDENT, **kw):
    return {"id": "c1", "country": country, "language": "en", "incidentAt": incident, "createdAt": incident,
            "clocks": [], "plan": None, "status": "confirmed", **kw}


def planned(c):
    c["plan"] = compute_plan(c, get_playbook(c["country"]))
    return c


def test_playbooks_load_and_are_versioned():
    pbs = load_playbooks()
    assert set(pbs) == {"IN", "MY"}
    for pb in pbs.values():
        assert pb["version"] == "2026-10-17" and pb["last_verified"] and pb["sources"]
        assert pb["timezone"] in ("Asia/Kolkata", "Asia/Kuala_Lumpur")


def test_india_plan_order_and_deadlines():
    c = planned(case())
    steps = c["plan"]["steps"]
    assert [s["id"] for s in steps] == ["call_1930", "file_ncrp", "report_bank"]
    assert steps[0]["urgency"] == "now" and steps[0]["contact"] == "1930" and steps[0]["channel"] == "call"
    assert all(s["deadline"] == INCIDENT + timedelta(days=5) for s in steps)
    assert steps[0]["deadlineDisplay"] == "22 Oct 2026, 14:02 IST"
    assert steps[1]["template_id"] == "ncrp_complaint"


def test_malaysia_plan_order_and_urgency_clock():
    c = planned(case("MY"))
    assert [s["id"] for s in c["plan"]["steps"]] == ["call_997", "call_bank", "keep_reference"]
    clocks = compute_clocks(c, get_playbook("MY"), INCIDENT + timedelta(minutes=30))
    assert [k["id"] for k in clocks] == ["report_hours"]
    assert clocks[0]["urgencyOnly"] and clocks[0]["status"] == "pending"
    assert clocks[0]["dueAt"] == INCIDENT + timedelta(hours=2)
    assert clocks[0]["dueDisplay"].endswith("MYT")
    assert compute_clocks(c, get_playbook("MY"), INCIDENT + timedelta(hours=3))[0]["status"] == "overdue"


def test_effective_from_not_in_force_shows_recommended_never_hidden():
    c = planned(case())
    clocks = compute_clocks(c, get_playbook("IN"), INCIDENT + timedelta(days=10))
    k = next(x for x in clocks if x["id"] == "dual_report_5d")
    assert k["status"] == "recommended"  # not "overdue": the rule is not in force for this incident
    assert k["inForce"] is False
    assert k["note"] == "Recommended — the RBI rule applies to frauds from 1 Jan 2027"
    assert k["effectiveFrom"] == "2027-01-01"
    _, newly = evaluate_clocks(c, get_playbook("IN"), INCIDENT + timedelta(days=10))
    assert newly == []  # not-in-force rules never trigger escalations


def test_effective_from_in_force_uses_playbook_local_date():
    pb = get_playbook("IN")
    # 31 Dec 2026 20:00 UTC == 1 Jan 2027 01:30 IST -> in force (local date decides)
    c = planned(case(incident=datetime(2026, 12, 31, 20, 0, tzinfo=UTC)))
    k = next(x for x in compute_clocks(c, pb, c["incidentAt"] + timedelta(days=1)) if x["id"] == "dual_report_5d")
    assert k["inForce"] is True and k["status"] == "pending" and k["note"] is None
    k = next(x for x in compute_clocks(c, pb, c["incidentAt"] + timedelta(days=6)) if x["id"] == "dual_report_5d")
    assert k["status"] == "overdue"
    # 31 Dec 2026 18:00 UTC == 31 Dec 23:30 IST -> not yet in force
    c2 = planned(case(incident=datetime(2026, 12, 31, 18, 0, tzinfo=UTC)))
    k2 = next(x for x in compute_clocks(c2, pb, c2["incidentAt"]) if x["id"] == "dual_report_5d")
    assert k2["status"] == "recommended"


def test_all_steps_done_marks_clock_done():
    pb = get_playbook("IN")
    c = planned(case(incident=datetime(2027, 2, 1, 5, 0, tzinfo=UTC)))
    for sid in ("call_1930", "file_ncrp", "report_bank"):
        c["plan"] = mark_step(c["plan"], sid, "done", "ref", c["incidentAt"] + timedelta(hours=1))
    k = next(x for x in compute_clocks(c, pb, c["incidentAt"] + timedelta(days=9)) if x["id"] == "dual_report_5d")
    assert k["status"] == "done"


def test_ombudsman_clock_starts_only_after_bank_step_done():
    pb = get_playbook("IN")
    c = planned(case())
    assert "ombudsman_30d" not in {k["id"] for k in compute_clocks(c, pb, INCIDENT + timedelta(days=40))}
    done_at = INCIDENT + timedelta(hours=2)
    c["plan"] = mark_step(c["plan"], "report_bank", "done", "BANK-123", done_at)
    clocks = {k["id"]: k for k in compute_clocks(c, pb, done_at + timedelta(days=29))}
    assert clocks["ombudsman_30d"]["status"] == "pending"
    assert clocks["ombudsman_30d"]["dueAt"] == done_at + timedelta(days=30)
    clocks = {k["id"]: k for k in compute_clocks(c, pb, done_at + timedelta(days=31))}
    assert clocks["ombudsman_30d"]["status"] == "overdue"
    assert clocks["ombudsman_30d"]["escalationTemplate"] == "rbi_ombudsman_complaint"


def test_lazy_evaluation_is_idempotent():
    pb = get_playbook("IN")
    c = planned(case())
    c["plan"] = mark_step(c["plan"], "report_bank", "done", "BANK-1", INCIDENT)
    now = INCIDENT + timedelta(days=31)
    clocks, newly = evaluate_clocks(c, pb, now)
    assert [k["id"] for k in newly] == ["ombudsman_30d"]
    assert newly[0]["escalationNotifiedAt"] == now
    c["clocks"] = clocks  # persisted
    for later in (now, now + timedelta(days=1), now + timedelta(days=5)):
        clocks2, newly2 = evaluate_clocks(c, pb, later)
        assert newly2 == []
        assert next(k for k in clocks2 if k["id"] == "ombudsman_30d")["escalationNotifiedAt"] == now
        c["clocks"] = clocks2


def test_plan_preserves_step_status_and_country_switch():
    c = planned(case())
    c["plan"] = mark_step(c["plan"], "call_1930", "done", "31016", INCIDENT)
    again = compute_plan(c, get_playbook("IN"))
    s = next(x for x in again["steps"] if x["id"] == "call_1930")
    assert s["status"] == "done" and s["user_reference"] == "31016"
    my = compute_plan({**c, "country": "MY", "plan": None}, get_playbook("MY"))
    assert my["country"] == "MY" and my["steps"][0]["id"] == "call_997"


def test_explain_rule_returns_playbook_text_verbatim():
    r = explain_rule(get_playbook("IN"), "compensation")
    assert "85%" in r["text"] and "₹25,000" in r["text"]
    assert explain_rule(get_playbook("IN"), "unknown-topic")["text"] is None
