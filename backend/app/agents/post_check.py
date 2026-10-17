"""Guardrail post-check: every amount, date or long number in a co-pilot reply must exist in case state.

Digits are normalised first, so Devanagari digits (१,९५,०००), Indian lakh grouping (1,95,000),
plain digits (195000), western grouping (195,000) and "1.95 lakh" all compare equal.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable

from ..rules.formatting import to_local

DEVANAGARI_DIGITS = str.maketrans("०१२३४५६७८९", "0123456789")
MIN_PLAIN_DIGITS = 3  # standalone numbers shorter than this (e.g. "5 days", "step 2") are not checked

_MONTHS = {
    # English
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3, "apr": 4, "april": 4, "may": 5,
    "jun": 6, "june": 6, "jul": 7, "july": 7, "aug": 8, "august": 8, "sep": 9, "sept": 9, "september": 9,
    "oct": 10, "october": 10, "nov": 11, "november": 11, "dec": 12, "december": 12,
    # Malay
    "januari": 1, "februari": 2, "mac": 3, "mei": 5, "julai": 7, "ogos": 8, "ogo": 8, "okt": 10, "oktober": 10,
    "dis": 12, "disember": 12,
    # Hindi
    "जनवरी": 1, "फ़रवरी": 2, "फरवरी": 2, "मार्च": 3, "अप्रैल": 4, "मई": 5, "जून": 6, "जुलाई": 7, "अगस्त": 8,
    "सितंबर": 9, "सितम्बर": 9, "अक्टूबर": 10, "अक्तूबर": 10, "नवंबर": 11, "नवम्बर": 11, "दिसंबर": 12, "दिसम्बर": 12,
}
_MONTH_RE = "|".join(sorted((re.escape(m) for m in _MONTHS), key=len, reverse=True))
_SCALE = {"lakh": 100_000, "lakhs": 100_000, "lac": 100_000, "lacs": 100_000, "लाख": 100_000,
          "crore": 10_000_000, "crores": 10_000_000, "करोड़": 10_000_000, "करोड": 10_000_000,
          "k": 1_000, "ribu": 1_000, "juta": 1_000_000, "million": 1_000_000, "thousand": 1_000, "हज़ार": 1_000, "हजार": 1_000}
_SCALE_RE = "|".join(sorted((re.escape(s) for s in _SCALE), key=len, reverse=True))

_NUM = r"\d+(?:,\d{2,3})*(?:\.\d+)?"
_DATE_PATTERNS = [
    (re.compile(r"\b(\d{4})-(\d{1,2})-(\d{1,2})"), ("y", "m", "d")),
    (re.compile(r"\b(\d{1,2})[/.-](\d{1,2})[/.-](\d{4})\b"), ("d", "m", "y")),
    (re.compile(rf"(?<!\w)(\d{{1,2}})(?:st|nd|rd|th)?\s+({_MONTH_RE})\.?,?(?:\s+(\d{{4}}))?(?!\w)", re.I), ("d", "M", "y")),
    (re.compile(rf"(?<!\w)({_MONTH_RE})\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?,?(?:\s+(\d{{4}}))?(?!\w)", re.I), ("M", "d", "y")),
]
_AMOUNT_RE = re.compile(
    rf"(?:(₹|rs\.?|inr|rm|myr)\s*)?({_NUM})(?:\s*({_SCALE_RE})(?![a-z]))?(?:\s*(rupees?|रुपये|रुपए|रु\.?|ringgit|/-))?",
    re.I,
)


def normalize_digits(text: str) -> str:
    return (text or "").translate(DEVANAGARI_DIGITS)


def _to_decimal(num: str, scale: str | None) -> Decimal | None:
    raw = re.sub(r"[,\s]", "", num)
    try:
        d = Decimal(raw)
    except InvalidOperation:
        return None
    if scale:
        d *= _SCALE[scale.lower()] if scale.lower() in _SCALE else _SCALE.get(scale, 1)
    return d.normalize()


def _canon(d: Decimal) -> str:
    q = d.normalize()
    s = format(q, "f")
    return s.rstrip("0").rstrip(".") if "." in s else s


@dataclass
class Found:
    kind: str  # "amount" | "number" | "date"
    raw: str
    value: Any
    parts: tuple[str, ...] = ()


def find_dates(text: str) -> tuple[list[Found], str]:
    """Return dates and the text with date spans blanked out (so their digits are not re-checked)."""
    text = normalize_digits(text)
    found: list[Found] = []
    chars = list(text)
    for rx, order in _DATE_PATTERNS:
        for m in rx.finditer(text):
            if any(c == "\0" for c in chars[m.start():m.end()]):
                continue
            vals = dict(zip(order, m.groups()))
            try:
                month = _MONTHS[vals["M"].lower()] if "M" in vals else int(vals["m"])
                day = int(vals["d"])
                year = int(vals["y"]) if vals.get("y") else None
                if not (1 <= month <= 12 and 1 <= day <= 31):
                    continue
            except (KeyError, ValueError, TypeError):
                continue
            found.append(Found("date", m.group(0), (year, month, day)))
            for i in range(m.start(), m.end()):
                chars[i] = "\0"
    return found, "".join(" " if c == "\0" else c for c in chars)


def find_values(text: str) -> list[Found]:
    dates, rest = find_dates(text)
    out = list(dates)
    for m in _AMOUNT_RE.finditer(rest):
        cur, num, scale, suffix = m.groups()
        digits_only = re.sub(r"\D", "", num.split(".")[0])
        d = _to_decimal(num, scale)
        if d is None:
            continue
        is_amount = bool(cur or scale or suffix)
        if not is_amount and len(digits_only) < MIN_PLAIN_DIGITS:
            continue
        parts = tuple(p for p in re.split(r"[^\d]+", num) if p)
        out.append(Found("amount" if is_amount else "number", m.group(0).strip(), _canon(d), parts))
    return out


@dataclass
class Allowed:
    numbers: set[str] = field(default_factory=set)
    dates: set[tuple[int, int, int]] = field(default_factory=set)

    def add_text(self, text: str) -> None:
        for f in find_values(text):
            if f.kind == "date":
                y, m, d = f.value
                if y:
                    self.dates.add((y, m, d))
                else:
                    self.dates.add((0, m, d))
            else:
                self.numbers.add(f.value)
        for run in re.findall(r"\d[\d\s\-]{2,}\d", normalize_digits(text)):  # phone numbers / references
            self.numbers.add(re.sub(r"\D", "", run))

    def add_number(self, v: float | int | Decimal) -> None:
        try:
            self.numbers.add(_canon(Decimal(str(v))))
        except InvalidOperation:
            pass

    def add_datetime(self, dt: datetime, tz_names: Iterable[str]) -> None:
        for tz in list(tz_names) + ["UTC"]:
            loc = to_local(dt, tz)
            self.dates.add((loc.year, loc.month, loc.day))

    def date_ok(self, value: tuple) -> bool:
        y, m, d = value
        if y:
            return (y, m, d) in self.dates
        return any(mm == m and dd == d for _, mm, dd in self.dates)

    def number_ok(self, f: Found) -> bool:
        return f.value in self.numbers


def build_allowed(*objs: Any, tz_names: Iterable[str] = ("Asia/Kolkata",)) -> Allowed:
    al = Allowed()
    tzs = list(tz_names)

    def walk(o: Any) -> None:
        if o is None or isinstance(o, bool):
            return
        if isinstance(o, str):
            al.add_text(o)
        elif isinstance(o, (int, float, Decimal)):
            al.add_number(o)
        elif isinstance(o, datetime):
            al.add_datetime(o, tzs)
        elif isinstance(o, date):
            al.dates.add((o.year, o.month, o.day))
        elif isinstance(o, dict):
            for v in o.values():
                walk(v)
        elif isinstance(o, (list, tuple, set)):
            for v in o:
                walk(v)

    for o in objs:
        walk(o)
    return al


def violations(text: str, allowed: Allowed) -> list[Found]:
    bad = []
    for f in find_values(text):
        ok = allowed.date_ok(f.value) if f.kind == "date" else allowed.number_ok(f)
        if not ok:
            bad.append(f)
    return bad


_SENT_SPLIT = re.compile(r"(?<=[.!?।])\s+|\n+")


def split_sentences(text: str) -> list[str]:
    return [s for s in _SENT_SPLIT.split(text) if s and s.strip()]


def sanitize(text: str, allowed: Allowed) -> tuple[str, list[Found]]:
    """Drop sentences containing unverifiable values. Returns (clean_text, violations)."""
    kept, bad = [], []
    for s in split_sentences(text):
        v = violations(s, allowed)
        if v:
            bad.extend(v)
        else:
            kept.append(s.strip())
    return " ".join(kept), bad


class StreamGate:
    """Sentence-level gate for streamed replies: a sentence is released only after it passes the check."""

    _BOUNDARY = re.compile(r"[.!?।]\s|\n")

    def __init__(self, allowed: Allowed):
        self.allowed = allowed
        self.buf = ""
        self.emitted: list[str] = []
        self.dropped: list[Found] = []

    def _release(self, sentence: str) -> str | None:
        if not sentence.strip():
            return sentence
        v = violations(sentence, self.allowed)
        if v:
            self.dropped.extend(v)
            return None
        self.emitted.append(sentence)
        return sentence

    def feed(self, chunk: str) -> list[str]:
        self.buf += chunk
        out = []
        while True:
            m = self._BOUNDARY.search(self.buf)
            if not m:
                break
            sentence, self.buf = self.buf[: m.end()], self.buf[m.end():]
            r = self._release(sentence)
            if r:
                out.append(r)
        return out

    def flush(self) -> list[str]:
        rest, self.buf = self.buf, ""
        r = self._release(rest) if rest else None
        return [r] if r else []

    @property
    def text(self) -> str:
        return "".join(self.emitted).strip()
