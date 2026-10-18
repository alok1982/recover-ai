"""IntakeAgent — one multimodal Gemini request over all evidence with a response JSON schema (PRD §9.1)."""
from __future__ import annotations

import copy
import json
import logging
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

from ..config import REPO_DIR
from ..i18n import LANG_NAMES
from ..llm import INJECTION_GUARD, Blob, LLMError, evidence_block, get_llm
from ..models import EXTRACTION_FIELDS, Extraction, ExtractionLLM
from ..storage import get_blobs

log = logging.getLogger("recoverai.intake")
LOW_CONFIDENCE = 0.7

SYSTEM = """You are the Intake Agent of RecoverAI, which helps scam victims recover money.
You receive evidence for ONE incident: payment screenshots, SMS or chat text, and/or audio (any language).
Extract facts ONLY from the evidence. Never guess. If a field is not present, return null and add it to missing_fields.
Return confidence 0-1 for every field you return.
Country context: {country}. Victim language: {language}.
Scam type must be one of: digital_arrest, fake_courier_customs, investment_trading, job_task, kyc_update, loan_app, romance, phishing_link, other.
Write narrative_en in English and narrative_local in {language}, max 80 words each, neutral and factual.
Amounts: digits only, no currency symbols. Datetime: ISO 8601 with timezone if visible, else local time without offset.
Use dotted names for nested fields in missing_fields (e.g. beneficiary.ifsc_or_code).
""" + INJECTION_GUARD


def _fixtures_dir() -> Path:
    import os

    return Path(os.getenv("FIXTURES_DIR") or (REPO_DIR / "fixtures"))


@lru_cache
def _manifest() -> dict:
    p = _fixtures_dir() / "manifest.json"
    return json.loads(p.read_text()) if p.exists() else {"images": {}, "audio": {}}


@lru_cache
def expected_case(name: str) -> dict:
    return json.loads((_fixtures_dir() / "expected" / f"{name}.json").read_text(encoding="utf-8"))


# ------------------------------------------------------------------ offline extraction (mock + fallback)
_SCAM_KEYWORDS = [
    ("digital_arrest", r"digital arrest|डिजिटल अरेस्ट|cbi|money laundering|मनी लॉन्ड्रिंग|warrant"),
    ("fake_courier_customs", r"kastam|customs|parcel|bungkusan|courier"),
    ("investment_trading", r"invest|trading|crypto|stock tips"),
    ("job_task", r"task|part[- ]time job|like and earn"),
    ("kyc_update", r"kyc"),
    ("loan_app", r"loan app|instant loan"),
    ("phishing_link", r"click (this|the) link|verify your account"),
]


def heuristic_extract(texts: list[str], country: str) -> dict[str, Any]:
    blob = "\n".join(texts)
    out: dict[str, Any] = {"beneficiary": {}, "confidence": {}}
    phones = re.findall(r"\+\d{2}[\d\s\-]{8,14}\d", blob)
    out["scammer_contacts"] = sorted({re.sub(r"\s+", " ", p.strip()) for p in phones})
    out["urls"] = sorted(set(re.findall(r"https?://[^\s)]+", blob)))
    vpa = re.search(r"\b[\w.\-]+@ok[a-z]+\b", blob)
    acct = re.search(r"\b\d{4}\s\d{4}\s\d{4}\b", blob)
    if vpa:
        out["beneficiary"]["account_or_vpa"] = vpa.group(0)
        out["confidence"]["beneficiary.account_or_vpa"] = 0.75
    elif acct:
        out["beneficiary"]["account_or_vpa"] = acct.group(0)
        out["confidence"]["beneficiary.account_or_vpa"] = 0.75
    amt = re.search(r"(?:₹|rs\.?|inr|rm)\s*([\d,]+(?:\.\d+)?)", blob, re.I)
    if amt:
        out["amount"] = float(amt.group(1).replace(",", ""))
        out["currency"] = "INR" if country == "IN" else "MYR"
        out["confidence"]["amount"] = 0.6
    for st, rx in _SCAM_KEYWORDS:
        if re.search(rx, blob, re.I):
            out["scam_type"] = st
            out["confidence"]["scam_type"] = 0.8
            break
    if out["scammer_contacts"]:
        out["confidence"]["scammer_contacts"] = 0.85
    if out["urls"]:
        out["confidence"]["urls"] = 0.85
    return out


def _merge(base: dict, overlay: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in overlay.items():
        if k == "beneficiary":
            out.setdefault("beneficiary", {}).update({kk: vv for kk, vv in v.items() if vv})
        elif k == "confidence":
            out.setdefault("confidence", {}).update(v)
        elif v not in (None, [], ""):
            if isinstance(v, list) and isinstance(out.get(k), list):
                out[k] = sorted(set(out[k]) | set(v))
            else:
                out[k] = v
    return out


def finalize(raw: dict, language: str) -> Extraction:
    raw = copy.deepcopy(raw)
    raw.setdefault("beneficiary", {})
    raw.setdefault("scam_type", "other")
    ex = Extraction.model_validate(raw)
    d = ex.model_dump()
    missing = []
    for f in EXTRACTION_FIELDS:
        v = d
        for part in f.split("."):
            v = v.get(part) if isinstance(v, dict) else None
        if v in (None, "", []):
            missing.append(f)
            ex.confidence.pop(f, None)
        elif f not in ex.confidence:
            ex.confidence[f] = 0.5
    ex.missing_fields = missing
    if ex.amount is not None and ex.amount <= 0:
        ex.amount = None
    return ex


def mock_extract(case: dict, evidence: list[dict], victim_texts: list[str]) -> Extraction:
    texts = [e.get("textContent") or "" for e in evidence if e.get("type") == "text"]
    raw: dict[str, Any] = heuristic_extract(texts + victim_texts, case["country"])
    man = _manifest()
    matched = None
    for e in evidence:
        if e.get("type") in ("image", "audio"):
            hit = man["images"].get(e.get("sha256")) or man["audio"].get(e.get("sha256"))
            if hit:
                matched = hit["case"]
    if matched:
        exp = expected_case(matched)["extraction"]
        raw = _merge(raw, exp)
        if case.get("language") == "en":
            raw["narrative_local"] = exp["narrative_en"]
    if not raw.get("narrative_en"):
        raw["narrative_en"] = "The victim reported a suspected scam payment. Details are taken from the evidence provided."
        raw["narrative_local"] = raw["narrative_en"]
    return finalize(raw, case.get("language", "en"))


# ------------------------------------------------------------------ Gemini
async def extract(case: dict, evidence: list[dict], victim_texts: list[str]) -> tuple[Extraction, str]:
    """Returns (extraction, source) where source is 'gemini' | 'mock' | 'fallback'."""
    llm = get_llm()
    if llm.is_mock:
        return mock_extract(case, evidence, victim_texts), "mock"
    blobs = get_blobs()
    lang = LANG_NAMES.get(case.get("language", "en"), "English")
    parts: list = [f"Country: {case['country']}. Evidence items follow."]
    for e in evidence:
        if e["type"] == "text":
            parts.append(evidence_block(e["id"], "text", e.get("textContent") or ""))
        else:
            parts.append(f'<evidence id="{e["id"]}" type="{e["type"]}" trust="untrusted"> (file follows) </evidence>')
            uri = blobs.gs_uri(e["gcsPath"])
            parts.append(Blob(mime_type=e["mimeType"], uri=uri) if uri else Blob(mime_type=e["mimeType"], data=blobs.read_bytes(e["gcsPath"])))
    for i, t in enumerate(victim_texts[-6:]):
        parts.append(evidence_block(f"victim_msg_{i}", "victim_statement", t))
    system = SYSTEM.format(country=case["country"], language=lang)
    # Cascade (evals/results/summary.md): the Flash-Lite tier first; the stronger "intake_escalate" tier only when the
    # first answer fails the schema / call, or a key field is missing or low-confidence while a receipt or text was given.
    tiers = ["intake"]
    s = llm.settings
    if s.task_model("intake_escalate") != s.task_model("intake"):
        tiers.append("intake_escalate")
    for i, task in enumerate(tiers):
        try:
            res = await llm.generate_json(system=system, parts=parts, schema=ExtractionLLM, temperature=0.2, task=task,
                                          step="intake" if i == 0 else "intake_escalate", case_id=case.get("id"))
            ex = finalize(res.to_canonical().model_dump(), case.get("language", "en"))
        except LLMError:
            log.warning("intake tier failed", extra={"caseId": case.get("id"), "step": task})
            continue
        why = needs_escalation(ex, evidence)
        if i == len(tiers) - 1 or not why:
            return ex, "gemini"
        log.info("intake_escalate", extra={"caseId": case.get("id"), "step": "intake", "reason": why})
    log.error("intake failed; using heuristic fallback", extra={"caseId": case.get("id")})
    return mock_extract(case, evidence, victim_texts), "fallback"


ESCALATE_KEYS = ("reference_id", "amount", "beneficiary.account_or_vpa")


def needs_escalation(ex: Extraction, evidence: list[dict]) -> str | None:
    """Why a first-tier extraction should be redone by the stronger tier (None = accept it)."""
    if not any(e.get("type") in ("image", "text") for e in evidence):
        return None  # voice-only: references / accounts are rarely spoken; nothing for a stronger model to find
    d = ex.model_dump()
    for k in ESCALATE_KEYS:
        if get_field(d, k) in (None, "", []):
            return f"missing:{k}"
        if ex.confidence.get(k, 0) < LOW_CONFIDENCE:
            return f"low_confidence:{k}"
    return None


def confidence_level(conf: float | None) -> str:
    if conf is None:
        return "red"
    if conf >= 0.85:
        return "green"
    if conf >= LOW_CONFIDENCE:
        return "amber"
    return "red"


def get_field(extraction: dict, dotted: str) -> Any:
    v: Any = extraction
    for part in dotted.split("."):
        v = v.get(part) if isinstance(v, dict) else None
    return v


def set_field(extraction: dict, dotted: str, value: Any) -> None:
    parts = dotted.split(".")
    tgt = extraction
    for p in parts[:-1]:
        tgt = tgt.setdefault(p, {})
    tgt[parts[-1]] = value
