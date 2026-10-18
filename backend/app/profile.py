"""CR-03 B/C: victim accounts (phone + password) and the victim profile.

Phone numbers are normalised to E.164 and mapped to a synthetic Firebase Email/Password login
(`<digits>@phone.recoverai.app`, never shown in the UI). `compute_status()` is the single definition of
"profile complete" used by the API, the 412 gate and the co-pilot tools. Profile data is personal data:
it is never written to BigQuery and never sent to Gemma.
"""
from __future__ import annotations

import re


PHONE_DOMAIN = "phone.recoverai.app"
TERMS_VERSION = "2026-10-cr03"
REQUIRED = ("fullName", "country", "language", "state", "district", "postalCode", "primaryBank")
OPTIONAL = ("email", "addressLine", "dob", "accountLast4", "altPhone", "primaryBankOther")
COUNTRIES = {"IN", "MY"}
LANGS = {"IN": {"en", "hi"}, "MY": {"en", "ms"}}
POSTAL = {"IN": re.compile(r"^[1-9]\d{5}$"), "MY": re.compile(r"^\d{5}$")}
BANKS = {
    "IN": ["State Bank of India", "HDFC Bank", "ICICI Bank", "Axis Bank", "Punjab National Bank", "Bank of Baroda",
           "Kotak Mahindra Bank", "Canara Bank", "Union Bank of India", "IndusInd Bank", "Yes Bank", "IDFC FIRST Bank",
           "Paytm Payments Bank", "Airtel Payments Bank"],
    "MY": ["Maybank", "CIMB Bank", "Public Bank", "RHB Bank", "Hong Leong Bank", "AmBank", "Bank Islam", "BSN",
           "Bank Rakyat", "Alliance Bank", "OCBC Bank (Malaysia)", "UOB Malaysia"],
}
OTHER_BANK = "Other"


MOBILE_RULE = {"IN": re.compile(r"[6-9]\d{9}"), "MY": re.compile(r"1\d{8,9}")}
DIAL = {"IN": "+91", "MY": "+60"}


def normalize_phone(raw: str, country: str | None = None) -> str | None:
    """'+91 90000 00001' / '090000-00001' / '9000000001' (IN) → '+919000000001'; None when not a valid IN/MY mobile.

    QA BUG-06: explicit per-country rules (the same as frontend/src/lib/phone.ts). India: 10 digits starting 6–9.
    Malaysia: 9–10 digits after 60, starting 1. An explicit +91 / +60 picks that country; any other code is rejected.
    The seed numbers (+91 90000 0000x, +60 10000 000x) satisfy these rules."""
    cc = (country or "IN").upper()
    if cc not in COUNTRIES:
        return None
    s = re.sub(r"[\s\-.()\u00a0]", "", raw or "")
    if s.startswith("00"):
        s = "+" + s[2:]
    if s.startswith("+"):
        cc = {"+91": "IN", "+60": "MY"}.get(s[:3])
        if not cc:
            return None
        s = s[3:]
    elif not s.isdigit():
        return None
    elif cc == "IN" and len(s) == 12 and s.startswith("91"):
        s = s[2:]
    elif cc == "MY" and s.startswith("60") and len(s) in (11, 12):
        s = s[2:]
    if not s.isdigit():
        return None
    if s.startswith("0"):
        s = s[1:]
    return DIAL[cc] + s if MOBILE_RULE[cc].fullmatch(s) else None


def valid_mobile_e164(e164: str | None) -> bool:
    """True for an E.164 number that satisfies the IN / MY mobile rules."""
    return bool(e164) and normalize_phone(e164) == e164


def phone_email(e164: str) -> str:
    return e164.lstrip("+") + "@" + PHONE_DOMAIN


def phone_from_email(email: str | None) -> str | None:
    if email and email.lower().endswith("@" + PHONE_DOMAIN):
        return "+" + email.split("@", 1)[0]
    return None


def country_of_phone(e164: str | None) -> str | None:
    if not e164:
        return None
    return "MY" if e164.startswith("+60") else "IN" if e164.startswith("+91") else None


def mask_phone(e164: str | None) -> str | None:
    """Never read out the full number: '+91 ••••••0001'."""
    if not e164:
        return None
    return f"{e164[:3]} ••••••{e164[-4:]}"


def _clean(v) -> str:
    return re.sub(r"\s+", " ", str(v)).strip() if v is not None else ""


def validate(profile: dict) -> tuple[dict, dict]:
    """Clean + validate a profile patch. Returns (clean, errors{field: code}). Empty strings clear optional fields."""
    out: dict = {}
    err: dict = {}
    allowed = set(REQUIRED) | set(OPTIONAL)
    for k, v in (profile or {}).items():
        if k in allowed:
            out[k] = _clean(v)
    if "country" in out and out["country"] not in COUNTRIES:
        err["country"] = "invalid"
    if "fullName" in out and not (2 <= len(out["fullName"]) <= 80):
        err["fullName"] = "length"
    if "language" in out and out["language"] not in {"en", "hi", "ms"}:
        err["language"] = "invalid"
    for k in ("state", "district"):
        if k in out and len(out[k]) > 80:
            err[k] = "length"
    if "postalCode" in out:
        out["postalCode"] = out["postalCode"].replace(" ", "")
    if out.get("accountLast4") and not re.fullmatch(r"\d{4}", out["accountLast4"]):
        err["accountLast4"] = "format"
    if out.get("email") and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", out["email"]):
        err["email"] = "format"
    if out.get("dob") and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", out["dob"]):
        err["dob"] = "format"
    if out.get("altPhone"):
        alt = normalize_phone(out["altPhone"], out.get("country") or None)
        if alt:
            out["altPhone"] = alt
        else:
            err["altPhone"] = "format"
    for k in ("addressLine", "primaryBankOther"):
        if k in out and len(out[k]) > 200:
            err[k] = "length"
    return out, err


def check_against_country(profile: dict) -> dict:
    """Cross-field checks on the merged profile (postal code, bank and language depend on the country)."""
    err: dict = {}
    c = profile.get("country")
    pc = profile.get("postalCode")
    if pc and c in POSTAL and not POSTAL[c].match(pc):
        err["postalCode"] = "format"
    bank = profile.get("primaryBank")
    if bank and c in BANKS and bank not in BANKS[c] and bank != OTHER_BANK:
        err["primaryBank"] = "invalid"
    if bank == OTHER_BANK and not _clean(profile.get("primaryBankOther")):
        err["primaryBankOther"] = "required"
    if profile.get("language") and c in LANGS and profile["language"] not in LANGS[c]:
        err["language"] = "invalid"
    return err


def compute_status(profile: dict | None) -> dict:
    """The one definition of a complete profile: {complete, missing[]} (missing in REQUIRED order)."""
    p = profile or {}
    bad = check_against_country(p)
    if "primaryBankOther" in bad:
        bad["primaryBank"] = bad.pop("primaryBankOther")
    missing = [k for k in REQUIRED if not _clean(p.get(k)) or k in bad]
    return {"complete": not missing, "missing": missing}


def bank_name(profile: dict | None) -> str | None:
    p = profile or {}
    if p.get("primaryBank") == OTHER_BANK:
        return p.get("primaryBankOther") or None
    return p.get("primaryBank") or None


def address_line(profile: dict | None) -> str:
    """'12 MG Road, Lucknow, Uttar Pradesh 226001' (only the parts the user gave)."""
    p = profile or {}
    place = ", ".join(x for x in (p.get("addressLine"), p.get("district"), p.get("state")) if x)
    return (place + (" " + p["postalCode"] if p.get("postalCode") else "")).strip()


def first_name(profile: dict | None) -> str | None:
    n = _clean((profile or {}).get("fullName"))
    return n.split(" ")[0] if n else None
