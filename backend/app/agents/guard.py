"""GuardAgent — recovery-scam classifier (Gemini Flash-Lite, PRD §9.5) plus a deterministic keyword net.

Runs on EVERY user message and on pasted/uploaded text before the co-pilot (wired in the chat route).
"""
from __future__ import annotations

import logging
import re

from ..llm import INJECTION_GUARD, LLMError, evidence_block, get_llm
from ..models import GuardResult

log = logging.getLogger("recoverai.guard")

SYSTEM = """Classify whether this message is a likely "recovery scam" (asks the victim to pay money, fees, taxes or deposits to
recover lost funds, or claims to be a recovery agent / lawyer / official offering guaranteed recovery).
Return JSON {"is_recovery_scam": bool, "reason": string}.
A victim asking whether they will get their money back is NOT a recovery scam.
""" + INJECTION_GUARD

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
        return {"is_recovery_scam": False, "reason": "", "source": "empty"}
    h_flag, h_reason = heuristic(text)
    llm = get_llm()
    if llm.is_mock:
        return {"is_recovery_scam": h_flag, "reason": h_reason, "source": "heuristic"}
    try:
        res = await llm.generate_json(system=SYSTEM, parts=[evidence_block("msg", "text", text)], schema=GuardResult,
                                      model=llm.settings.gemini_lite_model, temperature=0.0, step="guard", case_id=case_id)
        flag = res.is_recovery_scam or h_flag
        return {"is_recovery_scam": flag, "reason": res.reason if res.is_recovery_scam else h_reason,
                "source": "gemini" + ("+heuristic" if h_flag else "")}
    except LLMError:
        log.warning("guard model failed; heuristic only", extra={"caseId": case_id})
        return {"is_recovery_scam": h_flag, "reason": h_reason, "source": "heuristic"}
