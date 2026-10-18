"""Push-subscription handlers (F15). Called by the HTTP push endpoints and, offline, directly by LocalBus."""
from __future__ import annotations

from .pubsub import process_once, stable_key


def bank_case_key(envelope: dict) -> str:
    """Dedupe key for fraud_case.submit: caseId + sent_at (PRD F8). Also the deterministic bank case id."""
    p = envelope.get("payload") or {}
    return stable_key("fraud_case.submit", p.get("caseId"), envelope.get("sent_at"))


async def on_fraud_case_submitted(envelope: dict, meta: dict) -> dict:
    from ..agents import bank_receiver

    if envelope.get("intent") == "fraud_case.withdraw" and (envelope.get("payload") or {}).get("caseId"):
        p = envelope["payload"]
        wkey = stable_key("fraud_case.withdraw", p["caseId"], envelope.get("sent_at"))

        async def run_withdraw() -> dict:
            return await bank_receiver.withdraw(envelope, meta)

        return await process_once(f"withdraw-{wkey}", "fraud-case-submitted", meta, run_withdraw)
    if envelope.get("intent") != "fraud_case.submit" or not (envelope.get("payload") or {}).get("caseId"):
        raise ValueError("unsupported or malformed envelope")
    key = bank_case_key(envelope)

    async def run() -> dict:
        bc = await bank_receiver.receive(envelope, meta)
        return {"bankCaseId": bc["id"]}

    return await process_once(f"case-{key}", "fraud-case-submitted", meta, run)


async def on_bank_decision(event: dict, meta: dict) -> dict:
    from .. import actions

    if not event.get("eventId") or not event.get("caseId"):
        raise ValueError("malformed bank-decision event")

    async def run() -> dict:
        return await actions.apply_bank_decision(event)

    return await process_once(f"decision-{event['eventId']}", "bank-decision", meta, run)
