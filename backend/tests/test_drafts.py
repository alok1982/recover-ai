import asyncio
from datetime import datetime, timezone

from app.agents.filing import draft_facts, ensure_values, generate_all, missing_values
from app.rules.engine import compute_plan, get_playbook

CASE = {
    "id": "c_test", "country": "IN", "language": "hi", "incidentAt": datetime(2026, 10, 17, 8, 32, tzinfo=timezone.utc),
    "extraction": {"reference_id": "612345678901", "amount": 195000.0, "currency": "INR", "occurred_at": "2026-10-17T14:02:00+05:30",
                   "payment_method": "UPI", "payer_bank": "Bank of Demo", "scam_type": "digital_arrest",
                   "beneficiary": {"name": "CBI Verification Desk", "account_or_vpa": "cbi.verify.desk@okdemo", "bank": "Sample Bank"},
                   "scammer_contacts": ["+91 90000 12345"], "urls": [], "narrative_en": "x", "narrative_local": "y"},
}
PB = get_playbook("IN")
FACTS = draft_facts(CASE, PB)


def test_complete_draft_passes_in_any_digit_form():
    en = "UTR 612345678901, Rs 195000 on 17/10/2026 to CBI Verification Desk (cbi.verify.desk@okdemo)."
    assert missing_values(en, FACTS, CASE, PB) == []
    hi = "UTR 612345678901, ₹१,९५,००० — १७ अक्टूबर २०२६ — CBI Verification Desk, CBI.VERIFY.DESK@okdemo"
    assert missing_values(hi, FACTS, CASE, PB) == []


def test_missing_values_detected_and_inserted():
    bad = "I paid ₹2,00,000 to someone on 18 Oct 2026."
    miss = missing_values(bad, FACTS, CASE, PB)
    assert set(miss) == {"reference_id", "amount", "occurred_at", "beneficiary_account", "beneficiary_name"}
    fixed, inserted = ensure_values(bad, FACTS, CASE, PB, "hi")
    assert inserted == miss and fixed.startswith("पुष्टि किए गए केस विवरण")
    assert missing_values(fixed, FACTS, CASE, PB) == []


def test_generated_drafts_contain_confirmed_values():
    case = dict(CASE)
    case["plan"] = compute_plan(case, PB)
    drafts = asyncio.run(generate_all(case, PB, case["plan"]))
    assert set(drafts) == {"call_1930", "file_ncrp", "report_bank"}
    for d in drafts.values():
        assert d["insertedValues"] == []
        assert missing_values(d["en"], FACTS, case, PB) == [] and missing_values(d["local"], FACTS, case, PB) == []
        assert d["localLang"] == "hi"
    assert "85%" in drafts["report_bank"]["en"]  # cites playbook rules_text
