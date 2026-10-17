"""Deadline agent (PRD F7): lazy, idempotent clock evaluation.

There is no scheduler: clocks are evaluated whenever a case is read or touched (GET case, chat turn, time travel).
The arithmetic lives in rules.engine.evaluate_clocks; escalation posting (exactly once, guarded by
escalationNotifiedAt) lives in actions.evaluate. This module is the stable entry point for both.
"""
from __future__ import annotations

from ..rules.engine import evaluate_clocks  # noqa: F401  (pure: case + playbook + now -> clocks, due escalations)


async def evaluate(case_id: str, now=None) -> list[dict]:
    """Recompute clocks for a case and post any newly-due escalation card. Returns new messages."""
    from .. import actions

    return await actions.evaluate(case_id, now)
