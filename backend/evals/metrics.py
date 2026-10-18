"""Metric helpers. Field-level P/R uses exact match after normalisation (see norm_field)."""
from __future__ import annotations

import re
import unicodedata
from datetime import datetime

LIST_FIELDS = ("scammer_contacts", "urls")


def _txt(v) -> str:
    s = unicodedata.normalize("NFKC", str(v)).casefold()
    s = re.sub(r"[^\w@.]+", " ", s)
    return re.sub(r"\s+", " ", s).strip(" .")


def norm_field(field: str, v):
    if v in (None, "", []):
        return None
    if field == "amount":
        try:
            return round(float(v), 2)
        except (TypeError, ValueError):
            return None
    if field == "currency":
        s = str(v).strip().upper()
        return {"RS": "INR", "₹": "INR", "RM": "MYR"}.get(s, s)
    if field in ("reference_id", "beneficiary.ifsc_or_code"):
        return re.sub(r"[^0-9A-Za-z]", "", str(v)).upper()
    if field == "beneficiary.account_or_vpa":
        return re.sub(r"[\s\-]", "", str(v)).lower()
    if field == "occurred_at":
        s = str(v).strip()
        m = re.match(r"(\d{4})-(\d{2})-(\d{2})[T ](\d{1,2}):(\d{2})", s)
        if not m:
            try:
                d = datetime.fromisoformat(s)
                return (d.year, d.month, d.day, d.hour, d.minute)
            except ValueError:
                return s
        return tuple(int(x) for x in m.groups())
    if field == "scammer_contacts":
        return {re.sub(r"\D", "", str(x))[-9:] for x in v if re.sub(r"\D", "", str(x))}
    if field == "urls":
        return {str(x).strip().lower().rstrip("/") for x in v}
    if field in ("payment_method", "scam_type"):
        return str(v)
    return _txt(v)


def field_counts(field: str, truth, pred) -> tuple[int, int, int]:
    """(tp, fp, fn). Lists are scored per element; a wrong scalar is one FP and one FN."""
    t, p = norm_field(field, truth), norm_field(field, pred)
    if field in LIST_FIELDS:
        t, p = t or set(), p or set()
        return len(t & p), len(p - t), len(t - p)
    if t is None and p is None:
        return 0, 0, 0
    if t is None:
        return 0, 1, 0
    if p is None:
        return 0, 0, 1
    return (1, 0, 0) if t == p else (0, 1, 1)


def pr(tp: int, fp: int, fn: int) -> tuple[float, float]:
    p = tp / (tp + fp) if tp + fp else 1.0
    r = tp / (tp + fn) if tp + fn else 1.0
    return round(p, 4), round(r, 4)


def lang_ok(text: str, lang: str) -> bool:
    """Reply is in the case language (script check for Hindi; function words for Malay / English)."""
    if not text.strip():
        return False
    deva = sum(1 for c in text if "\u0900" <= c <= "\u097f")
    letters = sum(1 for c in text if c.isalpha()) or 1
    if lang == "hi":
        return deva / letters > 0.4
    if deva / letters > 0.1:
        return False
    w = set(re.findall(r"[a-z]+", text.lower()))
    ms = len(w & {"anda", "dan", "yang", "untuk", "ini", "dengan", "kepada", "tidak", "boleh", "sila", "kes", "wang", "bank", "akan", "jika", "atau", "dalam", "telah", "saya"})
    en = len(w & {"the", "you", "your", "and", "to", "is", "for", "this", "with", "please", "will", "can", "if", "or", "not", "has", "have"})
    return ms > en if lang == "ms" else en >= ms
