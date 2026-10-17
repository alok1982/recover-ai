"""Seed the synthetic bank data (PRD §12.3) into the active analytics backend (BigQuery, or local in mock mode)."""
from __future__ import annotations

import logging
from datetime import datetime

from .analytics.bq import get_analytics

log = logging.getLogger("recoverai.seed")


def seed_bank_data(seed_time: datetime | None = None, with_ml: bool = True) -> dict:
    stats = get_analytics().seed(seed_time, with_ml=with_ml)
    log.info("seeded bank data", extra={"step": "seed", **stats})
    return stats
