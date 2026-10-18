"""CR-01 / F8.1: write fixtures/hashes.json — SHA-256 of every bundled demo file.

Uploads whose hash matches are demo evidence: the case is forced into sandbox and locked. Text fixtures are also hashed
the way the API hashes pasted text (stripped, UTF-8), so pasting a demo message matches too.
Run after changing fixtures:  python scripts/make_fixture_hashes.py
"""
import hashlib
import json
from pathlib import Path

FIX = Path(__file__).resolve().parents[1] / "fixtures"


def main() -> None:
    out = {}
    for f in sorted(FIX.iterdir()):
        if not f.is_file() or f.name in ("hashes.json", "manifest.json"):
            continue
        data = f.read_bytes()
        out[hashlib.sha256(data).hexdigest()] = f.name
        if f.suffix == ".txt":
            out[hashlib.sha256(data.decode("utf-8").strip().encode("utf-8")).hexdigest()] = f.name + " (pasted)"
    (FIX / "hashes.json").write_text(json.dumps({"sha256": out}, indent=1, sort_keys=True) + "\n")
    print(f"{len(out)} hashes → {FIX / 'hashes.json'}")


if __name__ == "__main__":
    main()
