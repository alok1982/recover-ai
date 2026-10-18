"""CR-03 A/B: phone accounts, anonymous tokens rejected, /api/me endpoints, case list."""
from app import profile as P
from conftest import H

PH = {"Authorization": "Bearer mock:phone:+919000000099"}
FULL = {"fullName": "Asha Verma", "country": "IN", "language": "hi", "state": "Uttar Pradesh", "district": "Lucknow",
        "postalCode": "226001", "primaryBank": "HDFC Bank"}


def test_phone_normalisation_and_synthetic_email():
    assert P.normalize_phone("+91 90000 00001", "IN") == "+919000000001"
    assert P.normalize_phone("90000 00001", "IN") == "+919000000001"
    assert P.normalize_phone("+60 10000 0001", "MY") == "+60100000001"
    assert P.normalize_phone("+44 7700 900000", "IN") is None
    assert P.phone_email("+919000000001") == "919000000001@phone.recoverai.app"
    assert P.phone_from_email("919000000001@phone.recoverai.app") == "+919000000001"
    assert P.mask_phone("+919000000001") == "+91 ••••••0001"


def test_anonymous_tokens_rejected_on_victim_routes(client):
    r = client.post("/api/cases", json={"country": "IN", "language": "en"}, headers=H("anon-x1"))
    assert r.status_code == 401 and r.json()["detail"]["code"] == "SIGN_IN_REQUIRED"
    assert client.get("/api/me", headers=H("anon-x1")).status_code == 401
    assert client.get("/api/cases", headers={}).status_code == 401


def test_me_created_on_first_get_with_phone_from_token(client):
    me = client.get("/api/me", headers=PH).json()
    assert me["phoneE164"] == "+919000000099" and me["phoneVerified"] is False
    assert me["profile"] == {"country": "IN"} and me["profileStatus"]["complete"] is False
    assert "HDFC Bank" in me["banks"]["IN"] and me["phoneMasked"].endswith("0099")


def test_terms_then_profile_signup_flow(client):
    r = client.post("/api/me/terms", json={"version": P.TERMS_VERSION}, headers=PH).json()
    assert r["termsVersion"] == P.TERMS_VERSION and r["termsAcceptedAt"]
    r = client.put("/api/me/profile", json={"profile": {"fullName": "Asha Verma", "country": "IN", "language": "hi"}}, headers=PH)
    assert r.status_code == 200
    assert r.json()["profileStatus"] == {"complete": False, "missing": ["state", "district", "postalCode", "primaryBank"]}
    r = client.put("/api/me/profile", json={"profile": FULL}, headers=PH).json()
    assert r["profileStatus"] == {"complete": True, "missing": []} and r["firstName"] == "Asha"


def test_profile_validation(client):
    bad = client.put("/api/me/profile", json={"profile": {**FULL, "postalCode": "2260", "fullName": "A"}}, headers=PH)
    assert bad.status_code == 422 and set(bad.json()["detail"]["errors"]) == {"postalCode", "fullName"}
    my = client.put("/api/me/profile", json={"profile": {**FULL, "country": "MY", "language": "ms", "postalCode": "50450",
                                                          "primaryBank": "HDFC Bank"}}, headers=PH)
    assert my.status_code == 422 and "primaryBank" in my.json()["detail"]["errors"]
    other = client.put("/api/me/profile", json={"profile": {**FULL, "primaryBank": "Other"}}, headers=PH)
    assert other.status_code == 422
    ok = client.put("/api/me/profile", json={"profile": {**FULL, "primaryBank": "Other", "primaryBankOther": "Fino Bank"}},
                    headers=PH)
    assert ok.status_code == 200 and ok.json()["profileStatus"]["complete"]
    assert P.bank_name(ok.json()["profile"]) == "Fino Bank"


def test_case_list_is_per_user(client):
    cid = client.post("/api/cases", json={"country": "IN", "language": "en"}, headers=PH).json()["caseId"]
    mine = client.get("/api/cases", headers=PH).json()["cases"]
    assert [c["id"] for c in mine] == [cid] and mine[0]["sandbox"] is True and "publicRef" in mine[0]
    other = client.get("/api/cases", headers={"Authorization": "Bearer mock:phone:+919000000098"}).json()["cases"]
    assert other == []


def test_delete_account(client):
    client.post("/api/cases", json={"country": "IN", "language": "en"}, headers=PH)
    r = client.delete("/api/me", headers=PH).json()
    assert r["deleted"] and r["cases"] == 1
    assert client.get("/api/cases", headers=PH).json()["cases"] == []
