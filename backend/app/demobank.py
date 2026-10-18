"""Demo bank: in DEMO_MODE the bank side is always a clearly fictional bank, so nothing presents as a real bank.

Real bank names stay only on the victim's own side (their profile's primary bank, and the letters the victim
addresses to their own bank). The desk that *receives* a shared case, the bank-staff signup choice, approved staff
`bankId`s and the bank's messages back to the victim all use this bank."""
from __future__ import annotations

from .config import get_settings

DEMO_BANK_ID = "demo-recoverai-bank"
DEMO_BANK_NAME = "RecoverAI Demo Bank (fictional)"
# Same display name in every country (IN, MY); kept as a map so a per-country label can be added later.
DEMO_BANK_NAMES = {"IN": DEMO_BANK_NAME, "MY": DEMO_BANK_NAME}


def active() -> bool:
    return bool(get_settings().demo_mode)


def name(country: str | None = None) -> str:
    return DEMO_BANK_NAMES.get((country or "").upper(), DEMO_BANK_NAME)


def receiving_bank(country: str | None = None) -> dict | None:
    """The bank desk that receives a shared case (demo mode), or None outside demo mode."""
    return {"bankId": DEMO_BANK_ID, "name": name(country)} if active() else None


def staff_banks() -> dict[str, list[str]]:
    """Bank choices for bank-staff signup: only the demo bank in demo mode."""
    from . import profile as P
    return {c: [name(c)] for c in ("IN", "MY")} if active() else P.BANKS
