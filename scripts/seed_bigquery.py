#!/usr/bin/env python3
"""Load the synthetic bank data (PRD §12.3) into BigQuery: ~40 accounts, ~3,000 transactions with timestamps relative to
now (so "last 24 h" holds on demo day), 50 anonymised case_events; then build the S2 feature table + BigQuery ML model.

  GOOGLE_CLOUD_PROJECT=recoverai-511917 ANALYTICS_BACKEND=bigquery BQ_LOCATION=asia-south1 \\
      python scripts/seed_bigquery.py [--no-ml]
  MOCK_MODE=true LOCAL_DATA_DIR=backend/.localdata python scripts/seed_bigquery.py   # offline store
Tables must exist (deploy.sh runs backend/sql/create_tables.sql). Uses Application Default Credentials.
"""
import argparse
import json

import _path  # noqa: F401
from app.seed import seed_bank_data


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-ml", action="store_true", help="skip the S2 feature table + BigQuery ML model")
    a = ap.parse_args()
    print(json.dumps(seed_bank_data(with_ml=not a.no_ml), indent=1))


if __name__ == "__main__":
    main()
