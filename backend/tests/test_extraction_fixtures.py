"""Extraction against synthetic fixtures (PRD §12.2).

Offline this exercises the mock intake path; set RUN_LIVE_GEMINI=1 with ADC + MOCK_MODE=false to run the
same assertions against Gemini on Vertex AI."""
import asyncio
import json
import os

import pytest

from app.actions import sha256_hex
from app.agents import intake
from app.agents.intake import get_field
from conftest import FIX


def _ev(fname, typ, mime):
    data = (FIX / fname).read_bytes()
    e = {"id": fname, "type": typ, "mimeType": mime, "sha256": sha256_hex(data), "gcsPath": f"fixtures/{fname}"}
    if typ == "text":
        e["textContent"] = data.decode("utf-8")
    return e


@pytest.mark.parametrize("name,files", [
    ("in_case", [("in_upi_success.png", "image", "image/png"), ("in_whatsapp_scam.txt", "text", "text/plain")]),
    ("my_case", [("my_bank_transfer.png", "image", "image/png"), ("my_sms.txt", "text", "text/plain")]),
])
def test_key_fields_match_expected(name, files):
    exp = json.loads((FIX / "expected" / f"{name}.json").read_text())
    case = {"id": "t", "country": exp["country"], "language": exp["language"]}
    ex, source = asyncio.run(intake.extract(case, [_ev(*f) for f in files], []))
    d = ex.model_dump()
    for k in exp["key_fields"]:
        got, want = get_field(d, k), get_field(exp["extraction"], k)
        if k == "beneficiary.account_or_vpa":
            got, want = got.replace(" ", "").lower(), want.replace(" ", "").lower()
        assert got == want, (k, got, want)
    for k in exp["key_fields"]:
        assert d["confidence"].get(k, 0) >= (0.7 if source == "mock" else 0.5)
    assert "beneficiary.ifsc_or_code" in d["missing_fields"]


def test_text_only_heuristics():
    h = intake.heuristic_extract([(FIX / "my_sms.txt").read_text()], "MY")
    assert h["amount"] == 4800 and h["scam_type"] == "fake_courier_customs"
    assert h["urls"] == ["http://kastam-parcel.example/bayar"]
    assert h["beneficiary"]["account_or_vpa"] == "5140 1234 5678"


def test_confidence_levels():
    assert intake.confidence_level(0.9) == "green"
    assert intake.confidence_level(0.75) == "amber"
    assert intake.confidence_level(0.62) == "red"
    assert intake.confidence_level(None) == "red"


@pytest.mark.skipif(os.getenv("RUN_LIVE_GEMINI") != "1", reason="live Gemini test (needs ADC + MOCK_MODE=false)")
def test_live_marker():
    assert os.getenv("MOCK_MODE") == "false"
