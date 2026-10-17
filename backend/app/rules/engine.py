"""Country playbook engine: deterministic plan + clocks from YAML rules.

Rules are data (playbooks/*.yaml); this module is generic. Gemini only explains the result.
"""
from __future__ import annotations

import copy
from datetime import date, datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from ..config import BACKEND_DIR
from ..timeutil import ensure_utc, utcnow
from .formatting import format_dt, to_local

PLAYBOOK_DIR = BACKEND_DIR / "playbooks"
URGENCY_ORDER = {"now": 0, "today": 1, "within_days": 2}


def _norm(pb: dict) -> dict:
    pb = copy.deepcopy(pb)
    for k in ("version", "last_verified"):
        if isinstance(pb.get(k), date):
            pb[k] = pb[k].isoformat()
    for c in pb.get("clocks", []):
        ef = c.get("effective_from")
        if isinstance(ef, str):
            c["effective_from"] = date.fromisoformat(ef)
    pb.setdefault("rules_text", {})
    pb.setdefault("notes", {})
    return pb


@lru_cache
def load_playbooks(directory: str | None = None) -> dict[str, dict]:
    d = Path(directory) if directory else PLAYBOOK_DIR
    out = {}
    for f in sorted(d.glob("*.yaml")):
        pb = _norm(yaml.safe_load(f.read_text(encoding="utf-8")))
        out[pb["country"]] = pb
    return out


def get_playbook(country: str) -> dict:
    pbs = load_playbooks()
    if country not in pbs:
        raise KeyError(f"no playbook for {country}")
    return pbs[country]


def incident_date_local(case: dict, pb: dict) -> date | None:
    inc = case.get("incidentAt")
    return to_local(inc, pb["timezone"]).date() if inc else None


def clock_in_force(clock: dict, case: dict, pb: dict) -> bool:
    ef = clock.get("effective_from")
    if not ef:
        return True
    inc = incident_date_local(case, pb)
    if inc is None:
        return False
    return inc >= ef


def _step_index(case: dict) -> dict[str, dict]:
    return {s["id"]: s for s in (case.get("plan") or {}).get("steps", [])}


def clock_start(clock: dict, case: dict) -> datetime | None:
    src = clock.get("from", "incident_at")
    if src == "incident_at":
        inc = case.get("incidentAt") or case.get("createdAt")
        return ensure_utc(inc) if inc else None
    if src.startswith("step_done:"):
        step = _step_index(case).get(src.split(":", 1)[1])
        if step and step.get("status") == "done" and step.get("doneAt"):
            return ensure_utc(step["doneAt"])
        return None
    raise ValueError(f"unknown clock origin {src}")


def _duration(clock: dict) -> timedelta:
    return timedelta(days=float(clock.get("days") or 0), hours=float(clock.get("hours") or 0))


def compute_clocks(case: dict, pb: dict, now: datetime) -> list[dict]:
    """Return the clocks that have started, with status pending/done/overdue/recommended.

    `now` is the effective (demo-shifted) time. escalationNotifiedAt is carried over from the case.
    """
    now = ensure_utc(now)
    prev = {c["id"]: c for c in case.get("clocks") or []}
    steps = _step_index(case)
    tz = pb["timezone"]
    lang = case.get("language", "en")
    out = []
    for c in pb.get("clocks", []):
        start = clock_start(c, case)
        if start is None:
            continue
        due = start + _duration(c)
        in_force = clock_in_force(c, case, pb)
        applies = c.get("applies_to_steps") or []
        done = bool(applies) and all(steps.get(s, {}).get("status") == "done" for s in applies)
        if c["id"].startswith("ombudsman") and case.get("status") == "closed":
            done = True
        if done:
            status = "done"
        elif not in_force:
            status = "recommended"
        elif now > due:
            status = "overdue"
        else:
            status = "pending"
        p = prev.get(c["id"], {})
        out.append({
            "id": c["id"],
            "label": c["label"],
            "labelLocal": (c.get("label_local") or {}).get(lang),
            "from": c.get("from", "incident_at"),
            "startedAt": start,
            "dueAt": due,
            "dueDisplay": format_dt(due, tz),
            "status": status,
            "inForce": in_force,
            "note": None if in_force else c.get("not_in_force_note"),
            "noteLocal": None if in_force else (c.get("not_in_force_note_local") or {}).get(lang),
            "effectiveFrom": c["effective_from"].isoformat() if c.get("effective_from") else None,
            "urgencyOnly": bool(c.get("urgency_only")),
            "appliesToSteps": applies,
            "escalationTemplate": c.get("escalation_template"),
            "escalationTitle": c.get("escalation_title"),
            "escalationTitleLocal": (c.get("escalation_title_local") or {}).get(lang),
            "contact": c.get("contact"),
            "escalationNotifiedAt": p.get("escalationNotifiedAt"),
        })
    return out


def evaluate_clocks(case: dict, pb: dict, now: datetime) -> tuple[list[dict], list[dict]]:
    """Lazy deadline evaluation (no scheduler). Returns (clocks, newly_overdue).

    A clock is reported as newly overdue exactly once: its escalationNotifiedAt is stamped in the
    returned list, so persisting the result makes repeated evaluation idempotent.
    """
    clocks = compute_clocks(case, pb, now)
    newly = []
    for c in clocks:
        if c["status"] == "overdue" and not c.get("escalationNotifiedAt"):
            c["escalationNotifiedAt"] = ensure_utc(now)
            newly.append(c)
    return clocks, newly


def compute_plan(case: dict, pb: dict, now: datetime | None = None) -> dict:
    """Ordered action plan (urgent first). Existing step status / user reference are preserved by id."""
    lang = case.get("language", "en")
    prev = _step_index(case)
    tz = pb["timezone"]
    # Deadlines come from incident-anchored clocks that list the step.
    tmp_case = {**case, "plan": {"steps": list(prev.values())}}
    step_due: dict[str, datetime] = {}
    for c in pb.get("clocks", []):
        if c.get("from", "incident_at") != "incident_at":
            continue
        start = clock_start(c, tmp_case)
        if start is None:
            continue
        due = start + _duration(c)
        for sid in c.get("applies_to_steps") or []:
            step_due[sid] = min(step_due.get(sid, due), due)
    steps = []
    for i, s in enumerate(pb["steps"]):
        p = prev.get(s["id"], {})
        due = step_due.get(s["id"])
        steps.append({
            "id": s["id"],
            "order": i,
            "title": s["title"],
            "titleLocal": (s.get("title_local") or {}).get(lang),
            "channel": s["channel"],
            "contact": s.get("contact"),
            "urgency": s["urgency"],
            "why": s.get("why"),
            "deadline": due,
            "deadlineDisplay": format_dt(due, tz),
            "required_fields": s.get("required_fields", []),
            "template_id": s.get("template_id", "none"),
            "status": p.get("status", "pending"),
            "user_reference": p.get("user_reference"),
            "doneAt": p.get("doneAt"),
        })
    steps.sort(key=lambda s: (URGENCY_ORDER.get(s["urgency"], 9), s["order"]))
    return {
        "playbook_version": pb["version"],
        "country": pb["country"],
        "timezone": tz,
        "computedAt": ensure_utc(now or utcnow()),
        "steps": steps,
        "sources": pb.get("sources", []),
        "last_verified": pb.get("last_verified"),
    }


def mark_step(plan: dict, step_id: str, status: str, reference: str | None, now: datetime) -> dict:
    plan = copy.deepcopy(plan)
    for s in plan["steps"]:
        if s["id"] == step_id:
            s["status"] = status
            if reference is not None:
                s["user_reference"] = reference
            s["doneAt"] = ensure_utc(now) if status == "done" else None
            return plan
    raise KeyError(step_id)


def explain_rule(pb: dict, topic: str) -> dict[str, Any]:
    """Return verbatim playbook text for a topic (compensation, ombudsman, freeze, or a step id)."""
    topic = (topic or "").lower()
    rules = pb.get("rules_text", {})
    for key, text in rules.items():
        if key in topic or topic in key:
            return {"topic": key, "text": text, "source": "playbook.rules_text", "playbook_version": pb["version"]}
    for s in pb["steps"]:
        if s["id"] in topic or topic in s["id"]:
            return {"topic": s["id"], "text": s.get("why", ""), "source": "playbook.steps.why", "playbook_version": pb["version"]}
    return {"topic": topic, "text": None, "available_topics": list(rules.keys()) + [s["id"] for s in pb["steps"]]}
