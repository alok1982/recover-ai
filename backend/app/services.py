"""Case helpers shared by routers and agents."""
from __future__ import annotations

import contextvars
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


# QA BUG-11: one card of each kind+key per chat turn. chat_events opens a scope; inside it a second card with the same
# key (for example a guard warning and the co-pilot's check_recovery_scam on the same text, or a tool called twice)
# is not stored again: the first message is returned and the stream drops the repeat by message id.
_TURN_CARDS: contextvars.ContextVar[dict | None] = contextvars.ContextVar("turn_cards", default=None)


def card_key(card_: dict | None) -> tuple[str, str] | None:
    if not card_:
        return None
    d = card_.get("data") or {}
    k = (d.get("clockId") or d.get("key") or d.get("id") or "") if isinstance(d, dict) else ""
    return str(card_.get("kind") or ""), str(k)


def open_turn_scope() -> contextvars.Token:
    return _TURN_CARDS.set({})


def close_turn_scope(tok: contextvars.Token) -> None:
    try:
        _TURN_CARDS.reset(tok)
    except ValueError:  # reset from another context (generator closed elsewhere): just drop the scope
        _TURN_CARDS.set(None)


def append_message(case_id: str, *, role: str, text: str | None = None, card: dict | None = None,
                   lang: str = "en", audio_path: str | None = None, tool_calls: list | None = None,
                   meta: dict | None = None, store: Store | None = None, msg_id: str | None = None) -> dict:
    msg = {
        "role": role, "text": text, "card": card, "audioPath": audio_path, "lang": lang,
        "toolCalls": tool_calls or [],
    }
    if meta:
        msg["meta"] = meta
    if msg_id:
        msg["id"] = msg_id
    scope = _TURN_CARDS.get()
    key = card_key(card) if scope is not None else None
    if key and (case_id, key) in scope:
        log.info("duplicate_card_dropped", extra={"caseId": case_id, "step": "card", "kind": key[0]})
        return scope[(case_id, key)]
    saved = (store or get_store()).add_message(case_id, msg)
    if key:
        scope[(case_id, key)] = saved
    return saved


def system_event(case_id: str, text: str, lang: str = "en", store: Store | None = None, msg_id: str | None = None) -> dict:
    log.info("system_event", extra={"caseId": case_id, "step": "system_event", "event": text})
    return append_message(case_id, role="system_event", text=text, lang=lang, store=store, msg_id=msg_id)


def card(kind: str, data: dict) -> dict:
    return {"kind": kind, "data": jsonable(data)}


def mark_profile_changed(uid: str) -> int:
    """CR-03 C: drafts already generated carry the old name/address/bank → flag them "Profile changed — regenerate"."""
    store = get_store()
    n = 0
    for c in store.list_cases(owner_uid=uid):
        if c.get("drafts"):
            store.update_case(c["id"], {"draftsStale": "profile_changed", "updatedAt": utcnow()})
            n += 1
    return n
