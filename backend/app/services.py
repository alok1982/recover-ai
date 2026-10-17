"""Case helpers shared by routers and agents."""
from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Any

from fastapi import HTTPException

from .auth import User
from .store import Store, get_store
from .timeutil import to_iso, utcnow

log = logging.getLogger("recoverai.case")


def jsonable(o: Any) -> Any:
    if isinstance(o, datetime):
        return to_iso(o)
    if isinstance(o, date):
        return o.isoformat()
    if isinstance(o, dict):
        return {k: jsonable(v) for k, v in o.items() if not str(k).startswith("_")}
    if isinstance(o, (list, tuple)):
        return [jsonable(v) for v in o]
    return o


def get_owned_case(user: User, case_id: str, store: Store | None = None) -> dict:
    store = store or get_store()
    case = store.get_case(case_id)
    if not case or case.get("ownerUid") != user.uid:
        raise HTTPException(404, "case not found")
    return case


def update_case(case_id: str, patch: dict, store: Store | None = None) -> None:
    (store or get_store()).update_case(case_id, {**patch, "updatedAt": utcnow()})


def append_message(case_id: str, *, role: str, text: str | None = None, card: dict | None = None,
                   lang: str = "en", audio_path: str | None = None, tool_calls: list | None = None,
                   meta: dict | None = None, store: Store | None = None) -> dict:
    msg = {
        "role": role, "text": text, "card": card, "audioPath": audio_path, "lang": lang,
        "toolCalls": tool_calls or [],
    }
    if meta:
        msg["meta"] = meta
    return (store or get_store()).add_message(case_id, msg)


def system_event(case_id: str, text: str, lang: str = "en", store: Store | None = None) -> dict:
    log.info("system_event", extra={"caseId": case_id, "step": "system_event", "event": text})
    return append_message(case_id, role="system_event", text=text, lang=lang, store=store)


def card(kind: str, data: dict) -> dict:
    return {"kind": kind, "data": jsonable(data)}
