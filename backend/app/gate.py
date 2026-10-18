"""CR-03 C: the profile gate.

Evidence, plans, drafts, the evidence pack and bank sharing need a complete victim profile (profile.compute_status).
REST endpoints answer 412 {code: PROFILE_INCOMPLETE, missing}; the co-pilot shows the urgent hotline card first
(recent loss / distress), then a profile card with only the missing fields, pre-filled from the chat. The victim
saves the card; the co-pilot never saves profile data.
"""
from __future__ import annotations

import re

from fastapi import HTTPException

from . import profile as P
from .i18n import t
from .store import get_store

HOTLINE = {
    "IN": {"number": "1930", "web": "https://cybercrime.gov.in", "name": "National Cyber Crime Helpline"},
    "MY": {"number": "997", "web": None, "name": "National Scam Response Centre (NSRC)"},
}

# Recent loss or distress (a code backstop for the co-pilot's own judgement).
_RECENT = re.compile(
    r"(just now|right now|\bnow\b|today|minutes? ago|an? hour ago|just (?:lost|sent|paid|transferred)|happened|scam(?:med)?|fraud|"
    r"help|urgent|panic|scared|please|cheated|"
    r"अभी|आज|अभी-अभी|कुछ देर|घंटे पहले|मिनट पहले|फ्रॉड|फ़्रॉड|ठगी|धोखा|मदद|बचाओ|डर|घबरा|"
    r"baru(?:\s+sahaja)?|tadi|hari ini|sekarang|ditipu|penipuan|tolong|takut|bantu)",
    re.I,
)
_NAME = re.compile(r"(?:my name is|i am|i'm|this is|मेरा नाम|nama saya)\s+([^\d,.!?।\n]{2,40}?)(?:\s+(?:है|hai|and|from|से)\b|[,.!?।\n]|$)", re.I)
_CITY = re.compile(r"(?:from|in|live in|मैं|dari|di)\s+([A-Z][a-z]{2,20})\b")


BANK_ALIASES = {
    "IN": ((r"\bSBI\b|एसबीआई|स्टेट बैंक", "State Bank of India"), (r"\bPNB\b|पंजाब नेशनल", "Punjab National Bank"),
           (r"\bBOB\b|\bBoB\b|बैंक ऑफ़? बड़ौदा", "Bank of Baroda"), (r"\bkotak\b|कोटक", "Kotak Mahindra Bank"),
           (r"\bHDFC\b|एचडीएफसी", "HDFC Bank"), (r"\bICICI\b|आईसीआईसीआई", "ICICI Bank"), (r"\baxis\b|एक्सिस", "Axis Bank"),
           (r"\bIDFC\b", "IDFC FIRST Bank"), (r"\bunion bank\b|यूनियन बैंक", "Union Bank of India"), (r"\bcanara\b|केनरा", "Canara Bank"),
           (r"\bpaytm\b|पेटीएम", "Paytm Payments Bank"), (r"\bairtel\b|एयरटेल", "Airtel Payments Bank")),
    "MY": ((r"\bmaybank\b|\bMBB\b", "Maybank"), (r"\bCIMB\b", "CIMB Bank"), (r"\bpublic bank\b|\bPBB\b", "Public Bank"),
           (r"\bRHB\b", "RHB Bank"), (r"\bhong leong\b|\bHLB\b", "Hong Leong Bank"), (r"\bambank\b", "AmBank"),
           (r"\bBSN\b", "BSN"), (r"\bbank rakyat\b", "Bank Rakyat"), (r"\bbank islam\b", "Bank Islam")),
}
_PIN_WORD = re.compile(r"(pin\s*code|pincode|\bpin\b|postal code|post\s*code|postcode|poskod|पिन\s*कोड|पिनकोड|पिन)\W{0,12}$", re.I)
_NOT_PLACE = {"sent", "paid", "lost", "transferred", "gave", "received", "total", "amount", "about", "around", "approx",
              "only", "upi", "utr", "ref", "reference", "account", "acct", "otp", "the", "and", "was", "hantar", "bayar"}
_AMOUNT_AFTER = re.compile(r"\s*(rs\b|inr\b|rupees?|ringgit|rm\b|/-|रुपये|रु\b)", re.I)
_AMOUNT_WORD = re.compile(r"(rs\.?|inr|₹|rm|rupees?|ringgit|रुपये|रु\.?)\s*$", re.I)


def _postal_from_text(text: str, country: str) -> str | None:
    """A PIN code / postcode the victim typed: a 6-digit (IN) or 5-digit (MY) number that follows 'PIN', 'postcode',
    'पिन' … or a place name ("Pune 411001"), never one that follows a currency word (amounts, UTRs are excluded)."""
    n = 6 if country == "IN" else 5
    pat = P.POSTAL.get(country)
    if not pat:
        return None
    for m in re.finditer(rf"(?<![\d,.])(\d{{{n}}})(?![\d,.]\d)", text):
        before = text[max(0, m.start() - 30):m.start()]
        after = text[m.end():m.end() + 14]
        if _AMOUNT_WORD.search(before) or _AMOUNT_AFTER.match(after) or not pat.match(m.group(1)):
            continue
        if _PIN_WORD.search(before):
            return m.group(1)
        place = re.search(r"\b([A-Z][a-z]{2,})(?: [A-Z][a-z]{2,})?,?\s*$", before)
        if place and place.group(1).lower() not in _NOT_PLACE:
            return m.group(1)
    return None


def owner_profile(case: dict) -> dict:
    u = get_store().get_user(case.get("ownerUid") or "") or {}
    return u.get("profile") or {}


def status(case: dict) -> dict:
    return P.compute_status(owner_profile(case))


def require_profile(case: dict) -> None:
    st = status(case)
    if not st["complete"]:
        raise HTTPException(412, {"code": "PROFILE_INCOMPLETE", "missing": st["missing"],
                                  "message": "Please complete your profile first."})


def hotline_shown(case_id: str) -> bool:
    return any((m.get("card") or {}).get("kind") == "hotline" for m in get_store().list_messages(case_id))


def wants_hotline_first(case: dict, text: str | None) -> bool:
    """Show the hotline card before the profile card when the loss is recent or the victim is distressed."""
    if hotline_shown(case["id"]):
        return False
    if text and _RECENT.search(text):
        return True
    users = [m for m in get_store().list_messages(case["id"]) if m.get("role") == "user" and m.get("text")]
    return any(_RECENT.search(m["text"]) for m in users[-3:])


def hotline_card_data(case: dict) -> dict:
    h = HOTLINE.get(case["country"], HOTLINE["IN"])
    lang = case.get("language", "en")
    return {"country": case["country"], "number": h["number"], "web": h["web"], "name": h["name"],
            "title": t("hotline_title", lang, number=h["number"]), "body": t("hotline_body", lang, number=h["number"])}


def prefill_from_text(texts: list[str], country: str) -> dict:
    """Details the victim already typed (name, city, bank) — only ever a suggestion on the card."""
    out: dict = {}
    joined = "\n".join(x for x in texts if x)
    m = _NAME.search(joined)
    if m:
        name = m.group(1).strip()
        if 2 <= len(name) <= 80:
            out["fullName"] = name
    low = joined.lower()
    for b in P.BANKS.get(country, []):
        short = b.lower().replace(" bank", "").replace("bank of ", "").strip()
        if b.lower() in low or (len(short) >= 3 and re.search(rf"\b{re.escape(short)}\b", low)):
            out["primaryBank"] = b
            break
    if "primaryBank" not in out:  # QA BUG-08: everyday short names ("SBI", "PNB", "एसबीआई")
        for alias, b in BANK_ALIASES.get(country, ()):
            if re.search(alias, joined, re.I):
                out["primaryBank"] = b
                break
    pc = _postal_from_text(joined, country)
    if pc:
        out["postalCode"] = pc
    c = _CITY.search(joined)
    if c and c.group(1).lower() not in {"india", "malaysia", "the", "my"}:
        out["district"] = c.group(1)
    return out


def profile_card_data(case: dict, prefill: dict | None = None) -> dict:
    prof = owner_profile(case)
    st = P.compute_status(prof)
    country = prof.get("country") or case["country"]
    users = [m.get("text") or "" for m in get_store().list_messages(case["id"]) if m.get("role") == "user"]
    guess = prefill_from_text(users[-6:], country)
    guess.update({k: v for k, v in (prefill or {}).items() if v and k in P.REQUIRED + P.OPTIONAL})
    pre = {k: v for k, v in guess.items() if k in st["missing"] or (k == "primaryBankOther" and "primaryBank" in st["missing"])}
    for k in st["missing"]:  # keep any partially typed value the profile already has (e.g. invalid PIN) out of the prefill
        if k not in pre and prof.get(k) and k not in ("postalCode",):
            pre[k] = prof[k]
    return {"missing": st["missing"], "prefill": pre, "country": country, "complete": st["complete"]}
