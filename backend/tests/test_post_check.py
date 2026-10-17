from datetime import datetime, timezone

from app.agents.post_check import StreamGate, build_allowed, find_values, normalize_digits, sanitize, violations

STATE = {
    "extraction": {"amount": 195000.0, "reference_id": "612345678901", "scammer_contacts": ["+91 90000 12345"]},
    "incidentAt": datetime(2026, 10, 17, 8, 32, tzinfo=timezone.utc),
    "clocks": [{"dueDisplay": "22 Oct 2026, 14:02 IST"}],
    "rules": "85% of the loss up to ₹25,000 ... from 1 Jan 2027; call 1930",
}
AL = build_allowed(STATE, tz_names=["Asia/Kolkata"])


def test_normalize_devanagari_digits():
    assert normalize_digits("१,९५,०००") == "1,95,000"


def test_amount_forms_all_match():
    for s in ["₹1,95,000", "Rs. 195000", "195,000 rupees", "₹१,९५,०००", "1.95 lakh", "1.95 लाख", "INR 1,95,000/-",
              "आपने १९५००० रुपये भेजे"]:
        assert violations(s, AL) == [], s


def test_wrong_amount_and_date_are_flagged():
    assert [f.value for f in violations("You will get ₹2,00,000 back", AL)] == ["200000"]
    assert [f.kind for f in violations("Deadline is 23 Oct 2026", AL)] == ["date"]
    assert [f.kind for f in violations("RM 50 fee", AL)] == ["amount"]


def test_dates_multi_language_and_formats():
    for s in ["22 Oct 2026", "22 October 2026", "Oct 22, 2026", "22 अक्टूबर 2026", "22 Okt 2026", "2026-10-22",
              "22/10/2026", "17 Oct", "on १७ अक्टूबर"]:
        assert violations(s, AL) == [], s
    vals = [f.value for f in find_values("२२ अक्टूबर २०२६")]
    assert vals == [(2026, 10, 22)]


def test_long_numbers_and_phones():
    assert violations("Your UTR is 612345678901.", AL) == []
    assert violations("Call 1930 now.", AL) == []
    assert violations("Scammer number +91 90000 12345 or +919000012345", AL) == []
    assert [f.value for f in violations("Reference 999888777", AL)] == ["999888777"]
    assert violations("Do step 2 within 5 days.", AL) == []  # small counts are not checked


def test_sanitize_drops_only_bad_sentences():
    text = "आपने ₹१,९५,००० भेजे। आपको ₹3,00,000 मिलेंगे। अभी 1930 पर कॉल करें।"
    clean, bad = sanitize(text, AL)
    assert "3,00,000" not in clean and "1930" in clean and "१,९५,०००" in clean
    assert len(bad) == 1


def test_stream_gate_releases_only_verified_sentences():
    g = StreamGate(AL)
    out = []
    for chunk in ["You paid ₹1,95", ",000 today. You will ", "get ₹9,99,999 back. Call ", "1930 now."]:
        out += g.feed(chunk)
    out += g.flush()
    joined = "".join(out)
    assert "₹1,95,000" in joined and "1930" in joined and "9,99,999" not in joined
    assert len(g.dropped) == 1
