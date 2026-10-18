"""F17 — light chat turns on Gemma 4, everything else on Gemini (PRD v2.3 §F17, §9.5, §9.6).

The guard's Flash-Lite call already labels each user turn "light" / "full" (no extra model call). Code overrides force
"full" for anything that needs tools, evidence, judgement or drafting. A light turn is answered by Gemma from a compact,
code-built case summary; Gemma never runs the conversation, never calls tools and never emits cards. Any Gemma problem
(error, > 8 s to first token, "[[FULL]]" hand-back, an unverifiable number, an empty reply) silently falls back to the
normal Gemini co-pilot turn — the victim never sees an error, only the Gemini answer.
"""
from __future__ import annotations

import asyncio
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any, AsyncIterator

from .. import actions
from ..config import get_settings
from ..i18n import LANG_NAMES
from ..llm import INJECTION_GUARD, LLMError, get_llm
from ..rules.formatting import format_dt
from ..services import jsonable
from ..store import get_store
from ..timeutil import effective_now, ensure_utc, parse_iso
from . import copilot, post_check

log = logging.getLogger("recoverai.router")

FULL_MARKER = "[[FULL]]"
HISTORY_MESSAGES = 6

LIGHT_SYSTEM = """You are RecoverAI, helping a fraud victim. Answer ONLY from the CASE SUMMARY below and the recent messages.
Reply in {language}, in at most 120 words, calmly and plainly. Never invent amounts, dates, deadlines, phone numbers
or legal rules; use only those in the summary. Never promise the money will be recovered. Never ask for OTPs, PINs or passwords.
"terms" in the summary explains the rules and terms for this case (e.g. ombudsman, compensation, freeze); questions about
what they mean, the next step, a deadline or the case status are answerable from the summary.
If the user needs a draft, a file, a decision, a change to their facts, or anything not in the summary, reply with exactly: [[FULL]]
CASE SUMMARY: {case_summary}
"""

# ---------------------------------------------------------------- routing rules (code overrides)
# A request for a draft, consent, escalation, sending to the bank, uploading, or a change to the facts → Gemini.
_FULL_KEYWORDS = re.compile(
    r"(draft|write|letter|generate|consent|share|send|escalat|upload|attach|screenshot|photo|picture|"
    r"change|correct|wrong|mistake|edit|fix|delete|remove|new number|withdraw|revoke|reverse|cancel|take back|undo|"
    # Hindi
    r"ड्राफ्ट|ड्राफ़्ट|लिखो|लिख दो|लिख दें|लिखिए|लिखें|पत्र|चिट्ठी|बना\s*दो|बनाओ|सहमति|साझा|शेयर|भेजो|भेज दो|भेज दें|भेज दीजिए|भेजिए|भेजें|एस्केलेट|अपलोड|स्क्रीनशॉट|फ़ोटो|फोटो|"
    r"बदल|गलत|ग़लत|सुधार|ठीक कर|हटा|वापस ले|वापस लो|रद्द|"
    # Malay
    r"draf|tulis|surat|jana|persetujuan|kongsi|hantar|eskalasi|muat naik|tangkapan skrin|gambar|"
    r"tukar|ubah|salah|betulkan|padam|batal|tarik balik)",
    re.I,
)
# "Will I definitely get my money back?" stays on Gemini: outcome questions are grounded with explain_rule + citations.
_OUTCOME = copilot._Q_GUARANTEE
# Identifiers: UPI IDs / e-mail, phone numbers, account numbers (amounts and dates come from post_check.find_values).
_ID_RE = re.compile(r"([\w.\-]{2,}@[a-z][\w.]{1,}|\+?\d[\d\s\-]{7,}\d)", re.I)

# Mock/offline stand-in for the Flash-Lite route label (the real label comes from the guard's Gemini call).
_LIGHT_HINT = re.compile(
    r"(what(?:'s| is| should| do| now| next)|next step|deadline|status|how long|when|meaning|explain|ombudsman|"
    r"अब|आगे|क्या करना|क्या है|मतलब|समय-सीमा|समय सीमा|स्थिति|कब तक|कब|लोकपाल|"
    r"apa (?:itu|perlu|seterusnya|langkah)|seterusnya|maksud|tarikh akhir|bila|status kes)",
    re.I,
)


def heuristic_route(text: str) -> str:
    t = text or ""
    return "light" if _LIGHT_HINT.search(t) and not _FULL_KEYWORDS.search(t) else "full"


@dataclass
class Decision:
    route: str  # "light" | "full"
    reason: str
    guard_route: str | None = None


def decide(case: dict, text: str | None, *, guard_route: str | None, flagged: bool, has_attachment: bool = False,
           has_audio: bool = False, trigger: str | None = None) -> Decision:
    """Light only if the guard said light AND no code override forces full."""
    s = get_settings()
    if not s.chat_light_model:
        return Decision("full", "light_model_disabled", guard_route)
    if has_attachment or has_audio:
        return Decision("full", "attachment_or_audio", guard_route)
    if trigger or not text:
        return Decision("full", "system_event", guard_route)
    if flagged:
        return Decision("full", "recovery_scam", guard_route)
    if not case.get("plan"):
        return Decision("full", "no_plan_yet", guard_route)
    if _FULL_KEYWORDS.search(text):
        return Decision("full", "action_keyword", guard_route)
    if post_check.find_values(text) or _ID_RE.search(post_check.normalize_digits(text)):
        return Decision("full", "new_fact_value", guard_route)
    if _OUTCOME.search(text):
        return Decision("full", "outcome_question", guard_route)
    if guard_route != "light":
        return Decision("full", "guard_full", guard_route)
    return Decision("light", "guard_light", guard_route)


# ---------------------------------------------------------------- light-turn context (built by code)
def _left(due: Any, now) -> str | None:
    d = parse_iso(due) if due else None
    if not d:
        return None
    secs = int((ensure_utc(d) - now).total_seconds())
    if secs <= 0:
        return "overdue"
    days, hours = secs // 86400, (secs % 86400) // 3600
    return f"{days}d {hours}h left" if days else f"{hours}h left"


def light_summary(case: dict) -> dict:
    """Facts, plan steps with status, clocks with due dates in the victim's time zone, bank status, playbook terms."""
    pb = actions.pb_for(case)
    tz = pb["timezone"]
    now = effective_now(case)
    base = copilot.case_summary(case, len(get_store().list_evidence(case["id"])))
    steps = (case.get("plan") or {}).get("steps", [])
    nxt = next((s for s in steps if s.get("status") != "done"), None)
    return jsonable({
        "now": format_dt(now, tz),
        "country": base["country"], "facts": base["facts"],
        "next_step": {"title": nxt["title"], "contact": nxt.get("contact"), "deadline": nxt.get("deadlineDisplay")} if nxt else None,
        "steps": base["steps"],
        "clocks": [{"label": c["label"], "due": c.get("dueDisplay"), "time_left": _left(c.get("dueAt"), now),
                    "status": c["status"], "note": c.get("note")} for c in case.get("clocks") or []],
        "bank_status": base["bank_status"], "drafts_ready": base["drafts_ready"],
        "terms": pb.get("rules_text", {}),  # verbatim playbook text (ombudsman, compensation, freeze)
        "hotline": "1930" if case["country"] == "IN" else "997",
    })


def _history_contents(history: list[dict], text: str):
    """Last N user/assistant text turns as alternating Gemma chat turns, then the new user message."""
    from google.genai import types

    turns: list[tuple[str, str]] = []
    for m in history[-HISTORY_MESSAGES:]:
        if m.get("role") == "user" and m.get("text"):
            role, txt = "user", m["text"]
        elif m.get("role") == "assistant" and (m.get("text") or m.get("card")):
            role = "model"
            txt = (m.get("text") or "") + (f" [showed {m['card']['kind']} card]" if m.get("card") else "")
        else:
            continue
        if turns and turns[-1][0] == role:
            # model: text + card of one reply belong together. user: an earlier question that got no reply is
            # superseded by the later one (merging them made Gemma answer the stale question).
            turns[-1] = (role, turns[-1][1] + "\n" + txt) if role == "model" else (role, txt)
        else:
            turns.append((role, txt))
    while turns and turns[0][0] != "user":
        turns.pop(0)
    if turns and turns[-1][0] == "user":
        turns[-1] = ("user", text)  # only the new message is the question
    else:
        turns.append(("user", text))
    return [types.Content(role=r, parts=[types.Part(text=t)]) for r, t in turns]


# ---------------------------------------------------------------- Gemma call
class LightFail(Exception):
    def __init__(self, reason: str, first_token_ms: int | None = None):
        super().__init__(reason)
        self.reason = reason
        self.first_token_ms = first_token_ms


_client = None


def _gemma_client():
    global _client
    if _client is None:
        from google import genai

        s = get_settings()
        _client = genai.Client(vertexai=True, project=s.project_id or None, location=s.chat_light_location)
    return _client


async def _gemma_stream(system: str, contents) -> AsyncIterator[str]:
    from google.genai import types

    s = get_settings()
    cfg = types.GenerateContentConfig(system_instruction=system, temperature=0.3, max_output_tokens=400)
    stream = await _gemma_client().aio.models.generate_content_stream(model=s.chat_light_model, contents=contents, config=cfg)
    async for chunk in stream:
        if chunk.text:
            yield chunk.text


def mock_light_reply(summary: dict, text: str, lang: str) -> str:
    """Offline stand-in for Gemma (MOCK_MODE): answers next-step / term questions from the summary, else hands back."""
    q = (text or "").lower()
    for key, val in (summary.get("terms") or {}).items():
        if key in q or (key == "ombudsman" and "लोकपाल" in q):
            lead = {"hi": "नियम के अनुसार:", "ms": "Mengikut peraturan:"}.get(lang)
            return f"{lead} {val}" if lead else val
    nxt = summary.get("next_step")
    if nxt and _LIGHT_HINT.search(q):
        dl = f" ({nxt['deadline']})" if nxt.get("deadline") else ""
        lead = {"hi": "अगला कदम", "ms": "Langkah seterusnya"}.get(lang, "Next step")
        return f"{lead}: {nxt['title']}{dl}."
    return FULL_MARKER


# Tests swap this to simulate Gemma (chunks, delays, errors).
GEMMA_STREAM = _gemma_stream


async def light_answer(case: dict, text: str, history: list[dict]) -> tuple[str, int]:
    """Return (reply, first_token_ms) or raise LightFail(reason). The reply is fully checked before anything is shown."""
    s = get_settings()
    lang = case.get("language", "en")
    t0 = time.perf_counter()
    if s.force_light_fail:
        raise LightFail("forced")
    summary = light_summary(case)
    if get_llm().is_mock and GEMMA_STREAM is _gemma_stream:
        reply, first_ms = mock_light_reply(summary, text, lang), 0
    else:
        import json

        system = LIGHT_SYSTEM.format(language=LANG_NAMES.get(lang, "English"),
                                     case_summary=json.dumps(summary, ensure_ascii=False)) + "\n" + INJECTION_GUARD
        gen = GEMMA_STREAM(system, _history_contents(history, f"<user_message>{text}</user_message>")).__aiter__()
        parts: list[str] = []
        first_ms = None
        try:
            first = await asyncio.wait_for(gen.__anext__(), timeout=s.light_first_token_s)
            first_ms = int((time.perf_counter() - t0) * 1000)
            parts.append(first)
            remaining = max(1.0, s.light_total_s - (time.perf_counter() - t0))

            async def rest():
                async for c in gen:
                    parts.append(c)
            await asyncio.wait_for(rest(), timeout=remaining)
        except asyncio.TimeoutError:
            raise LightFail("first_token_timeout" if first_ms is None else "total_timeout", first_ms) from None
        except StopAsyncIteration:
            raise LightFail("empty", first_ms) from None
        except (LLMError, Exception) as e:  # noqa: BLE001 - any Gemma error falls back to Gemini
            log.warning("gemma_error", extra={"caseId": case["id"], "step": "chat_light", "err": str(e)[:300]})
            raise LightFail("error", first_ms) from None
        reply = "".join(parts)
        log.info("gemma_call", extra={"caseId": case["id"], "step": "chat_light", "model": s.chat_light_model,
                                      "firstTokenMs": first_ms, "latencyMs": int((time.perf_counter() - t0) * 1000)})
    reply = (reply or "").strip()
    if FULL_MARKER in reply or "[[full]]" in reply.lower():
        raise LightFail("handed_back", first_ms)
    if not reply:
        raise LightFail("empty", first_ms)
    _clean, bad = post_check.sanitize(reply, actions.allowed_values(case, summary))
    if bad:
        log.warning("post_check_violation", extra={"caseId": case["id"], "step": "chat_light", "values": [f.raw for f in bad]})
        raise LightFail("post_check", first_ms)
    return reply, first_ms


# ---------------------------------------------------------------- turn
def _chunks(text: str) -> list[str]:
    return [w + " " for w in text.split(" ")] if text else []


async def run(case_id: str, text: str | None, flagged: bool, decision: Decision) -> AsyncIterator[dict]:
    """Route one turn. Full → Gemini co-pilot. Light → Gemma, falling back to the Gemini co-pilot on any failure."""
    s = get_settings()
    route_info: dict = {"route": decision.route, "reason": decision.reason, "guardRoute": decision.guard_route}
    if decision.route != "light":
        log.info("chat_route", extra={"caseId": case_id, "step": "router", **route_info})
        async for ev in copilot.run_turn(case_id, text, flagged, route=route_info):
            yield ev
        return
    store = get_store()
    case = actions.load(case_id)
    history = store.list_messages(case_id, limit=HISTORY_MESSAGES + 4)
    for i in range(len(history) - 1, -1, -1):  # the new user message is sent separately
        if history[i].get("role") == "user" and history[i].get("text") == text:
            history = history[:i] + history[i + 1:]
            break
    t0 = time.perf_counter()
    try:
        reply, first_ms = await light_answer(case, text or "", history)
    except LightFail as f:
        route_info.update({"fallback": f.reason, "lightFirstTokenMs": f.first_token_ms,
                           "lightMs": int((time.perf_counter() - t0) * 1000)})
        log.info("chat_route", extra={"caseId": case_id, "step": "router", **route_info})
        async for ev in copilot.run_turn(case_id, text, flagged, model_tag="gemini-fallback", route=route_info):
            yield ev
        return
    route_info.update({"firstTokenMs": first_ms, "lightMs": int((time.perf_counter() - t0) * 1000)})
    log.info("chat_route", extra={"caseId": case_id, "step": "router", "model": s.chat_light_model, **route_info})
    for piece in _chunks(reply):
        yield {"type": "token", "text": piece}
    msg = store.add_message(case_id, {"role": "assistant", "text": reply, "card": None, "audioPath": None,
                                      "lang": case.get("language", "en"), "toolCalls": [], "model": s.chat_light_model,
                                      "route": route_info})
    yield {"type": "done", "messageId": msg["id"], "message": jsonable(msg), "firstTokenMs": first_ms,
           "model": s.chat_light_model}
