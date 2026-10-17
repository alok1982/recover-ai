"""Stretch S2 — BigQuery scam intelligence. NOT BUILT (PRD: start only after M8 is deployed and the demo passes 3x).

Planned shape (PRD §S2):
  * table `recoverai_analytics.case_events` — anonymised rows on facts confirmation and bank decision
    (no names/phones; beneficiary account stored only as SHA-256 hash)
  * three queries for the bank "Scam intelligence" tab: by scam type (30 d), repeat beneficiary hashes (>= 2 cases),
    cases + amounts by country per day.
The /api/bank/analytics route returns 501 unless BIGQUERY_ENABLED=true, so this module is never imported in the demo.
"""
from __future__ import annotations


def insert_case_event(event: dict) -> None:  # pragma: no cover - stretch stub
    raise NotImplementedError("S2 BigQuery analytics is not built in this prototype")


def run_queries() -> dict:  # pragma: no cover - stretch stub
    raise NotImplementedError("S2 BigQuery analytics is not built in this prototype")
