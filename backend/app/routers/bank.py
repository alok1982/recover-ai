"""Bank side: A2A inbox (BankCaseReceiverAgent) + analyst dashboard API. Mounted at /bank and /api/bank."""
from __future__ import annotations

import hmac
import logging

from fastapi import APIRouter, Depends, Header, HTTPException

from .. import actions
from ..agents import bank_receiver
from ..auth import User, bank_user
from ..config import get_settings
from ..models import DecisionReq
from ..services import jsonable
from ..storage import get_blobs
from ..store import get_store
from ..timeutil import utcnow

log = logging.getLogger("recoverai.bank")


def make_router(prefix: str) -> APIRouter:
    r = APIRouter(prefix=prefix, tags=["bank"])

    @r.post("/a2a/inbox")
    async def inbox(envelope: dict, x_a2a_token: str | None = Header(default=None)) -> dict:
        token = get_settings().a2a_token
        if not token or not x_a2a_token or not hmac.compare_digest(token, x_a2a_token):
            raise HTTPException(401, "invalid A2A token")
        try:
            bc = await bank_receiver.receive(envelope)
        except (KeyError, ValueError) as e:
            raise HTTPException(400, f"bad envelope: {e}") from e
        return jsonable(bc)

    @r.get("/cases")
    def list_cases(user: User = Depends(bank_user)) -> dict:
        now = utcnow()
        out = []
        for b in get_store().list_bank_cases():
            v = jsonable({k: b.get(k) for k in ("id", "caseId", "country", "receivedAt", "amount", "currency", "amountDisplay",
                                                "scam_type", "riskLevel", "riskScore", "recommendedAction",
                                                "recommendedActionLabel", "status", "holdLimitDisplay", "occurredAt")})
            occ = b.get("occurredAt")
            v["hoursSinceTxn"] = round((now - occ).total_seconds() / 3600, 1) if occ else None
            out.append(v)
        return {"cases": out}

    @r.get("/cases/{bank_case_id}")
    def get_case(bank_case_id: str, user: User = Depends(bank_user)) -> dict:
        store = get_store()
        b = store.get_bank_case(bank_case_id)
        if not b:
            raise HTTPException(404, "not found")
        blobs = get_blobs()
        ev = []
        for e in b.get("evidence") or []:
            item = dict(e)
            if e.get("gcsPath") and e.get("type") == "image":
                try:
                    item["previewUrl"] = blobs.read_url(e["gcsPath"])
                except Exception:  # noqa: BLE001
                    item["previewUrl"] = None
            item.pop("gcsPath", None)
            ev.append(item)
        account = store.get_bank_account(b.get("beneficiaryKey") or "") if b.get("beneficiaryKey") else None
        return {"case": jsonable({**b, "evidence": ev}), "account": jsonable(account),
                "audit": jsonable(store.list_audit(bank_case_id=bank_case_id))}

    @r.post("/cases/{bank_case_id}/decision")
    async def decide(bank_case_id: str, req: DecisionReq, user: User = Depends(bank_user)) -> dict:
        analyst = user.name or user.email or user.uid
        bc = await actions.bank_decision(bank_case_id, req.decision, req.note, analyst)
        return {"case": jsonable(bc)}

    @r.get("/analytics")
    def analytics(user: User = Depends(bank_user)) -> dict:
        if not get_settings().bigquery_enabled:
            raise HTTPException(501, "Scam intelligence (BigQuery, stretch S2) is not enabled in this deployment")
        from ..analytics import bq

        return bq.run_queries()

    return r


router = make_router("/bank")
api_router = make_router("/api/bank")
