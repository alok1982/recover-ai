"""Bank side: Pub/Sub push inbox (BankCaseReceiverAgent, F8/F15) + analyst dashboard API (F9) + Scam intelligence (F14).

Mounted at /bank and /api/bank. The push subscription targets the Cloud Run URL directly (/bank/a2a/inbox)."""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Header, HTTPException

from .. import actions
from ..analytics import bq
from ..auth import User, bank_user
from ..events import handlers
from ..events.pubsub import decode_push, verify_push_auth
from ..models import DecisionReq
from ..services import jsonable
from ..storage import get_blobs
from ..store import get_store
from ..timeutil import utcnow

log = logging.getLogger("recoverai.bank")


def make_router(prefix: str) -> APIRouter:
    r = APIRouter(prefix=prefix, tags=["bank"])

    @r.post("/a2a/inbox")
    async def inbox(body: dict, authorization: str | None = Header(default=None)) -> dict:
        """Pub/Sub push from `fraud-case-submitted` (OIDC-verified). 2xx = ack; anything else is retried, then DLQ."""
        verify_push_auth(authorization)
        envelope, meta = decode_push(body)
        try:
            result = await handlers.on_fraud_case_submitted(envelope, meta)
        except (KeyError, ValueError) as e:
            raise HTTPException(400, f"bad envelope: {e}") from e
        return jsonable(result)

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
        return {"case": jsonable({**b, "evidence": ev}), "account": jsonable(b.get("txnFeatures")),
                "audit": jsonable(store.list_audit(bank_case_id=bank_case_id))}

    @r.post("/cases/{bank_case_id}/decision")
    async def decide(bank_case_id: str, req: DecisionReq, user: User = Depends(bank_user)) -> dict:
        analyst = user.name or user.email or user.uid
        bc = await actions.bank_decision(bank_case_id, req.decision, req.note, analyst)
        return {"case": jsonable(bc)}

    @r.get("/analytics")
    def analytics(user: User = Depends(bank_user)) -> dict:
        """F14 [SHOULD] Scam intelligence: three BigQuery queries over anonymised case_events."""
        try:
            data = bq.run_queries(utcnow())
        except Exception as e:  # noqa: BLE001
            log.warning("scam intelligence query failed", extra={"err": str(e)[:300]})
            raise HTTPException(503, "Scam intelligence is temporarily unavailable") from e
        return {"source": bq.get_analytics().name, **jsonable(data)}

    return r


router = make_router("/bank")
api_router = make_router("/api/bank")
