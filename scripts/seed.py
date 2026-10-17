#!/usr/bin/env python3
"""Seed all demo data. Firestore needs no seed data (cases are created by the app); the synthetic bank data lives in
BigQuery (F14), so this is the same as scripts/seed_bigquery.py. Kept for the PRD's script list and old docs."""
import runpy
from pathlib import Path

if __name__ == "__main__":
    runpy.run_path(str(Path(__file__).with_name("seed_bigquery.py")), run_name="__main__")
