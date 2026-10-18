"""GuardAgent — recovery-scam classifier (Gemini Flash-Lite, PRD §9.5) plus a deterministic keyword net.

Runs on EVERY user message and on pasted/uploaded text before the co-pilot (wired in the chat route).
F17: the same call also labels the turn "light" / "full" (no extra model call); code overrides live in router.py.
"""
from __future__ import annotations

import logging
import re

from ..llm import INJECTION_GUARD, LLMError, evidence_block, get_llm
from ..models import GuardResult, GuardVerdict

log = logging.getLogger("recoverai.guard")

_CORE = """Classify whether this message is a likely "recovery scam" (asks the victim to pay money, fees, taxes or deposits to
recover lost funds, or claims to be a recovery agent / lawyer / official offering guaranteed recovery).
Return JSON {{"is_recovery_scam": bool, "reason": string (max 12 words){route_field}}}.
A victim asking whether they will get their money back is NOT a recovery scam.
A victim describing their own loss (e.g. "I sent 1,95,000 to the CBI caller") is NOT a recovery scam.
A victim saying someone asked them to pay to get their money back (e.g. "Someone wants ₹9,500 to recover my money, should I pay?")
IS a recovery scam: true. Fees the victim already paid in the original scam (customs duty, KYC charge, task deposit)
are part of their loss, NOT a recovery scam.
"""
_ROUTE = """Also decide "route": "light" if the message can be answered from the case summary alone — a question about status,
the next step, a deadline, the meaning of a term, or simple reassurance — with no new facts, files, drafts or decisions.
Light examples: "What should I do now?", "अब मुझे क्या करना है?", "अगला कदम क्या है?", "When is my deadline?",
"मेरी डेडलाइन कब है?", "What is the Ombudsman?", "Ombudsman क्या है?", "Has my case been sent?", "Apa langkah seterusnya?",
"thank you", "I am scared".
Full examples: a new amount, date, UTR or account; "draft my complaint"; "send it to my bank"; "withdraw my consent";
"will I get my money back?"; anything about a file or screenshot. If it is none of these and you are unsure, "full".
"""
SYSTEM = _CORE.format(route_field=', "route": "light" | "full"') + _ROUTE + INJECTION_GUARD
# Token cut: with the Gemma light path off (CHAT_LIGHT_MODEL empty) the route label is unused, so it is not asked for.
SYSTEM_CORE = _CORE.format(route_field="") + INJECTION_GUARD


def system_prompt() -> str:
    from ..config import get_settings

    return SYSTEM if get_settings().chat_light_model else SYSTEM_CORE


def schema() -> type:
    from ..config import get_settings

    return GuardResult if get_settings().chat_light_model else GuardVerdict

_FEE = r"(fee|fees|processing|charge|charges|deposit|tax|commission|advance|शुल्क|फीस|फ़ीस|चार्ज|yuran|caj|bayaran pemprosesan|cukai)"
_RECOVER = (r"(recover|recovery|money back|get (?:your|ur) money|refund|reclaim|funds? release|वापस|रिकवरी|"
            r"kembali|pulih|pemulihan|tuntut semula)")
_AGENT = r"(recovery (?:agent|expert|lawyer|team|specialist)s?|cyber recovery|fund recovery|100% (?:money back|recovery)|guaranteed recovery)"


def heuristic(text: str) -> tuple[bool, str]:
    t = (text or "").lower()
    if re.search(_AGENT, t):
        return True, "Claims to be a recovery service / guaranteed recovery"
    if re.search(_FEE, t) and re.search(_RECOVER, t):
        return True, "Asks for a fee or payment to recover lost money"
    return False, ""


async def check(text: str, case_id: str | None = None) -> dict:
    text = (text or "").strip()
    if not text:
        return {"is_recovery_scam": False, "reason": "", "source": "empty", "route": "full"}
    from .router import heuristic_route

    h_flag, h_reason = heuristic(text)
    llm = get_llm()
    if llm.is_mock:
        return {"is_recovery_scam": h_flag, "reason": h_reason, "source": "heuristic", "route": heuristic_route(text)}
    try:
        res = await llm.generate_json(system=system_prompt(), parts=[evidence_block("msg", "text", text)], schema=schema(),
                                      temperature=0.0, task="guard", step="guard", case_id=case_id)
        flag = res.is_recovery_scam or h_flag
        return {"is_recovery_scam": flag, "reason": res.reason if res.is_recovery_scam else h_reason,
                "source": "gemini" + ("+heuristic" if h_flag else ""), "route": getattr(res, "route", "full")}
    except LLMError:
        log.warning("guard model failed; heuristic only", extra={"caseId": case_id})
        return {"is_recovery_scam": h_flag, "reason": h_reason, "source": "heuristic", "route": "full"}
