"""Pub/Sub push endpoints on the victim side (F15)."""
from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException

from ..events import handlers
from ..events.pubsub import decode_push, verify_push_auth
from ..services import jsonable

router = APIRouter(prefix="/api/events", tags=["events"])


@router.post("/bank-decision")
async def bank_decision(body: dict, authorization: str | None = Header(default=None)) -> dict:
    """Push from `bank-decision` (OIDC-verified): update the victim case and post the co-pilot message (idempotent)."""
    verify_push_auth(authorization)
    event, meta = decode_push(body)
    try:
        result = await handlers.on_bank_decision(event, meta)
    except (KeyError, ValueError) as e:
        raise HTTPException(400, f"bad event: {e}") from e
    return jsonable(result)
