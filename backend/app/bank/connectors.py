"""CR-01 / F8.1: outbound bank-system connectors.

Sandbox cases go through SandboxConnector, which records the call on the bank case and sends nothing. LiveConnector is
only an interface in the prototype (no real bank integration exists); it records that nothing was sent.
"""
from __future__ import annotations

import logging
from typing import Protocol

from ..store import get_store
from ..timeutil import utcnow

log = logging.getLogger("recoverai.bank.connectors")

ACTIONS = {"APPROVE_HOLD": "place_temporary_hold", "REQUEST_INFO": "request_customer_info", "REJECT": "close_case"}


class BankConnector(Protocol):
    name: str

    def record(self, bank_case_id: str, decision: str, details: dict) -> dict: ...


class SandboxConnector:
    name = "sandbox"

    def record(self, bank_case_id: str, decision: str, details: dict) -> dict:
        call = {"connector": self.name, "action": ACTIONS.get(decision, decision), "details": details, "at": utcnow(), "sent": False}
        bc = get_store().get_bank_case(bank_case_id) or {}
        get_store().update_bank_case(bank_case_id, {"connectorCalls": (bc.get("connectorCalls") or []) + [call]})
        log.info("sandbox_connector_call", extra={"bankCaseId": bank_case_id, "step": "connector", "action": call["action"]})
        return call


class LiveConnector:
    """Interface only: a real deployment would call the bank's hold/case-management API here."""

    name = "live"

    def record(self, bank_case_id: str, decision: str, details: dict) -> dict:
        call = {"connector": self.name, "action": ACTIONS.get(decision, decision), "details": details, "at": utcnow(),
                "sent": False, "note": "LiveConnector is not connected to any bank system in this prototype"}
        bc = get_store().get_bank_case(bank_case_id) or {}
        get_store().update_bank_case(bank_case_id, {"connectorCalls": (bc.get("connectorCalls") or []) + [call]})
        log.warning("live_connector_not_configured", extra={"bankCaseId": bank_case_id, "step": "connector"})
        return call


def connector_for(bank_case: dict) -> BankConnector:
    return SandboxConnector() if bank_case.get("sandbox") else LiveConnector()
