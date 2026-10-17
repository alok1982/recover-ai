#!/usr/bin/env python3
"""Seed the synthetic bank accounts (PRD §12.3) into Firestore (or the local store when MOCK_MODE=true).

  GOOGLE_CLOUD_PROJECT=<id> MOCK_MODE=false python scripts/seed.py [--force]
Uses Application Default Credentials (gcloud auth application-default login).
"""
import argparse

import _path  # noqa: F401
from app.seed import seed_bank_accounts


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true", help="overwrite even if accounts already exist")
    n = seed_bank_accounts(force=ap.parse_args().force)
    print(f"seeded {n} bank accounts" if n else "bank accounts already seeded (use --force to overwrite)")


if __name__ == "__main__":
    main()
