"""CR-04: bank-staff applications, admin approval/reject/revoke, role checks on every route."""
from app import roles as R
from app.store import get_store

ADMIN = {"Authorization": "Bearer mock:admin:Root"}
APPLICANT_EMAIL = "priya.nair@hdfc-demo.example"
APP = {"Authorization": f"Bearer mock:staff:{APPLICANT_EMAIL}"}
APP_UID = R.mock_uid_for_email(APPLICANT_EMAIL)
VICTIM = {"Authorization": "Bearer mock:phone:+919000000001"}
ANALYST = {"Authorization": "Bearer mock:bank:Demo"}
FORM = {"fullName": "Priya Nair", "country": "IN", "bankName": "HDFC Bank", "employeeId": "HD-1042",
        "designation": "Fraud analyst", "note": "Cyber fraud desk, Mumbai"}


def _apply(client, h=APP, form=FORM):
    return client.post("/api/bank-access/request", json=form, headers=h)


def test_application_is_pending_and_grants_nothing(client):
    r = _apply(client)
    assert r.status_code == 200 and r.json()["status"] == "PENDING"
    me = client.get("/api/me", headers=APP).json()
    assert me["accountType"] == "staff" and me["role"] is None and me["requestStatus"] == "PENDING"
    assert "profile" not in me  # no victim profile for staff accounts
    assert client.get("/api/bank/cases", headers=APP).status_code == 403
    assert client.get("/api/bank/analytics", headers=APP).status_code == 403
    assert client.get("/api/admin/bank-requests", headers=APP).status_code == 403
    # a staff account is not a victim either
    r = client.post("/api/cases", json={"country": "IN", "language": "en"}, headers=APP)
    assert r.status_code == 403 and r.json()["detail"]["code"] == "VICTIM_ACCOUNT_REQUIRED"


def test_client_cannot_self_assign_a_role(client):
    r = _apply(client, form={**FORM, "role": "bank", "status": "APPROVED", "bankId": "x"})
    assert r.status_code == 200 and r.json()["status"] == "PENDING" and r.json()["bankId"] is None
    assert R.mock_claims(APP_UID) == {}
    assert client.post(f"/api/admin/bank-requests/{APP_UID}/approve", headers=APP).status_code == 403
    assert client.post(f"/api/admin/bank-requests/{APP_UID}/approve", headers=ANALYST).status_code == 403
    assert client.post(f"/api/admin/users/{APP_UID}/revoke-bank", json={}, headers=VICTIM).status_code == 403


def test_victim_phone_account_cannot_apply(client):
    r = _apply(client, h=VICTIM)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "USE_WORK_EMAIL"
    assert client.get("/api/me", headers=VICTIM).json()["role"] == "victim"


def test_validation(client):
    assert _apply(client, form={**FORM, "bankName": "Fake Bank"}).status_code == 422
    assert _apply(client, form={**FORM, "bankName": "Other"}).status_code == 422
    assert _apply(client, form={**FORM, "bankName": "Other", "bankOther": "Saraswat Co-op Bank"}).status_code == 200
    assert _apply(client, form={**FORM, "country": "SG"}).status_code == 422


def test_approve_reject_revoke_with_audit(client):
    _apply(client)
    lst = client.get("/api/admin/bank-requests?status=pending", headers=ADMIN).json()
    assert [r["uid"] for r in lst["requests"]] == [APP_UID] and lst["counts"]["PENDING"] == 1
    r = client.post(f"/api/admin/bank-requests/{APP_UID}/approve", json={}, headers=ADMIN)
    assert r.status_code == 200 and r.json()["status"] == "APPROVED" and r.json()["bankId"] == "in-hdfc-bank"
    assert R.mock_claims(APP_UID)["role"] == "bank" and R.mock_claims(APP_UID)["bankId"] == "in-hdfc-bank"
    me = client.get("/api/me", headers=APP).json()
    assert me["role"] == "bank" and me["requestStatus"] == "APPROVED"
    assert client.get("/api/bank/cases", headers=APP).status_code == 200
    assert client.post(f"/api/admin/bank-requests/{APP_UID}/reject", json={"reason": "late"}, headers=ADMIN).status_code == 409
    r = client.post(f"/api/admin/users/{APP_UID}/revoke-bank", json={"reason": "left the bank"}, headers=ADMIN)
    assert r.status_code == 200 and r.json()["status"] == "REVOKED"
    assert "role" not in R.mock_claims(APP_UID)
    assert client.get("/api/bank/cases", headers=APP).status_code == 403
    assert client.get("/api/me", headers=APP).json()["role"] is None
    audit = client.get("/api/admin/audit", headers=ADMIN).json()["entries"]
    acts = [a["action"] for a in audit]
    assert {"request_submitted", "approve", "revoke_bank"} <= set(acts)
    rv = next(a for a in audit if a["action"] == "revoke_bank")
    assert rv["actorEmail"] == "root@admin.mock" and rv["reason"] == "left the bank" and rv["targetUid"] == APP_UID and rv["at"]
    assert client.get("/api/admin/audit", headers=APP).status_code == 403


def test_revoke_is_immediate_even_with_old_token_claims(client):
    """A live ID token keeps its claims until it expires; the APPROVED-request check blocks it at once."""
    _apply(client)
    client.post(f"/api/admin/bank-requests/{APP_UID}/approve", json={}, headers=ADMIN)
    client.post(f"/api/admin/users/{APP_UID}/revoke-bank", json={}, headers=ADMIN)
    R.set_claims(APP_UID, {"role": "bank"})  # simulate the stale token
    assert client.get("/api/bank/cases", headers=APP).status_code == 403


def test_reject_needs_reason_and_applicant_can_reapply(client):
    _apply(client)
    assert client.post(f"/api/admin/bank-requests/{APP_UID}/reject", json={"reason": ""}, headers=ADMIN).status_code == 422
    r = client.post(f"/api/admin/bank-requests/{APP_UID}/reject", json={"reason": "Employee ID not verified"}, headers=ADMIN)
    assert r.json()["status"] == "REJECTED"
    me = client.get("/api/me", headers=APP).json()
    assert me["requestStatus"] == "REJECTED" and me["request"]["reason"] == "Employee ID not verified"
    assert client.get("/api/bank/cases", headers=APP).status_code == 403
    assert _apply(client).json()["status"] == "PENDING"


def test_seeded_analyst_keeps_working_and_admins_are_protected(client):
    assert client.get("/api/bank/cases", headers=ANALYST).status_code == 200
    assert client.get("/api/admin/bank-requests", headers=ANALYST).status_code == 403
    assert client.post("/api/admin/users/admin-Root/revoke-bank", json={}, headers=ADMIN).status_code == 409
    assert client.post("/api/admin/bank-requests/nobody/approve", json={}, headers=ADMIN).status_code == 404


def test_staff_delete_removes_request_keeps_audit(client):
    _apply(client)
    assert client.delete("/api/me", headers=APP).json()["deleted"]
    assert R.get_request(APP_UID) is None
    assert any(a["action"] == "request_deleted_by_applicant" for a in get_store().list_docs(R.AUDIT_COL))
    assert client.delete("/api/me", headers=ADMIN).status_code == 409
