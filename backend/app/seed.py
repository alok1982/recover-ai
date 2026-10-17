"""Seed synthetic bank accounts (PRD §12.3) into the active store."""
from __future__ import annotations

import logging

from .bank.rules import normalize_account_key, synthetic_accounts
from .store import Store, get_store

log = logging.getLogger("recoverai.seed")


def seed_bank_accounts(store: Store | None = None, force: bool = False) -> int:
    store = store or get_store()
    if not force and store.count_bank_accounts() >= len(synthetic_accounts()):
        return 0
    n = 0
    for a in synthetic_accounts():
        store.put_bank_account(normalize_account_key(a["id"]), dict(a))
        n += 1
    log.info("seeded bank accounts", extra={"count": n, "step": "seed"})
    return n
