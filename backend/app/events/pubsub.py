"""F15 Pub/Sub event backbone: publish helpers, push-endpoint OIDC verification, idempotent processing.

Topics: fraud-case-submitted (victim → bank, F8) and bank-decision (bank → victim, F9). Each has a push subscription to
Cloud Run, authenticated with an OIDC token minted for the dedicated pubsub-push service account; dead-letter topic
recoverai-dlq after 5 attempts (created by deploy/deploy.sh).

* PubSubBus  — production publisher (google-cloud-pubsub).
* LocalBus   — offline: wraps each message in the exact push-request JSON Pub/Sub would POST and hands it to the same
               handler the HTTP endpoint uses, so mock mode and tests exercise the real decode/dedupe path.

Idempotency: every event carries a stable ``dedupe key`` (bank case: caseId + sent_at; decision: eventId). Handlers
skip keys already in ``processed_events`` and are themselves idempotent (deterministic ids + create-if-absent), so a
redelivery or a duplicate publish never creates a second bank case or a second co-pilot message.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
import uuid
from typing import Any, Awaitable, Callable, Protocol

from fastapi import HTTPException

from ..config import get_settings
from ..store import get_store
from ..timeutil import to_iso, utcnow

log = logging.getLogger("recoverai.events")

Handler = Callable[[dict, dict], Awaitable[dict]]  # (data, meta) -> result
MOCK_PUSH_TOKEN = "mock-push"


def stable_key(*parts: Any) -> str:
    return hashlib.sha256("|".join(str(p) for p in parts).encode()).hexdigest()[:24]


class EventBus(Protocol):
    async def publish(self, topic: str, data: dict, attributes: dict[str, str] | None = None) -> str: ...


class PubSubBus:
    def __init__(self, project: str):
        from google.cloud import pubsub_v1

        self.project = project
        self.client = pubsub_v1.PublisherClient()

    async def publish(self, topic: str, data: dict, attributes: dict[str, str] | None = None) -> str:
        path = self.client.topic_path(self.project, topic)
        body = json.dumps(data, ensure_ascii=False, default=str).encode()

        def _pub() -> str:
            return self.client.publish(path, body, **(attributes or {})).result(timeout=30)

        mid = await asyncio.to_thread(_pub)
        log.info("published", extra={"step": "pubsub_publish", "topic": topic, "messageId": mid})
        return mid


class LocalBus:
    """In-process delivery that mimics a push subscription (same envelope, same handler, sync for determinism)."""

    def __init__(self) -> None:
        self.handlers: dict[str, Handler] = {}
        self.delivered: list[dict] = []  # push bodies, kept for tests (redelivery)

    def subscribe(self, topic: str, handler: Handler) -> None:
        self.handlers[topic] = handler

    async def publish(self, topic: str, data: dict, attributes: dict[str, str] | None = None) -> str:
        mid = uuid.uuid4().hex[:16]
        body = push_body(topic, data, mid, attributes)
        self.delivered.append(body)
        handler = self.handlers.get(topic)
        if handler is None:
            log.warning("no local subscriber", extra={"topic": topic})
            return mid
        data_, meta = decode_push(body)
        await handler(data_, meta)
        return mid

    async def redeliver(self, index: int = -1) -> dict:
        body = self.delivered[index]
        data_, meta = decode_push(body)
        return await self.handlers[meta["topic"]](data_, meta)


def push_body(topic: str, data: dict, message_id: str, attributes: dict[str, str] | None = None) -> dict:
    return {
        "message": {
            "data": base64.b64encode(json.dumps(data, ensure_ascii=False, default=str).encode()).decode(),
            "messageId": message_id, "publishTime": to_iso(utcnow()), "attributes": {"topic": topic, **(attributes or {})},
        },
        "subscription": f"projects/local/subscriptions/{topic}-push",
    }


def decode_push(body: dict) -> tuple[dict, dict]:
    try:
        msg = body["message"]
        data = json.loads(base64.b64decode(msg["data"]).decode())
    except (KeyError, TypeError, ValueError) as e:
        raise HTTPException(400, f"malformed Pub/Sub push body: {e}") from e
    attrs = msg.get("attributes") or {}
    return data, {"messageId": msg.get("messageId") or msg.get("message_id"), "topic": attrs.get("topic"),
                  "attributes": attrs, "subscription": body.get("subscription"),
                  "deliveryAttempt": body.get("deliveryAttempt")}


# ------------------------------------------------------------------ push authentication
_google_request = None


def verify_push_auth(authorization: str | None) -> dict:
    """Verify the OIDC bearer token Pub/Sub attaches to push requests (audience + push service account)."""
    s = get_settings()
    token = authorization.split(" ", 1)[1].strip() if authorization and authorization.lower().startswith("bearer ") else None
    if not token:
        raise HTTPException(401, "missing push token")
    if s.effective_auth_mode == "mock":
        if token != MOCK_PUSH_TOKEN:
            raise HTTPException(401, "invalid mock push token")
        return {"email": "pubsub-push@local", "mock": True}
    if not s.push_audience or not s.push_sa_email:
        raise HTTPException(503, "push authentication not configured (PUSH_AUDIENCE / PUSH_SA_EMAIL)")
    global _google_request
    from google.auth.transport import requests as ga_requests
    from google.oauth2 import id_token

    if _google_request is None:
        _google_request = ga_requests.Request()  # caches Google's public certs between calls
    try:
        claims = id_token.verify_oauth2_token(token, _google_request, audience=s.push_audience)
    except Exception as e:  # noqa: BLE001
        log.warning("push token rejected", extra={"err": str(e)[:200]})
        raise HTTPException(401, "invalid push token") from e
    if claims.get("email") != s.push_sa_email or not claims.get("email_verified"):
        raise HTTPException(403, "push token from unexpected service account")
    return claims


# ------------------------------------------------------------------ idempotent processing
async def process_once(dedupe_key: str, topic: str, meta: dict, fn: Callable[[], Awaitable[dict]]) -> dict:
    store = get_store()
    done = store.get_processed_event(dedupe_key)
    if done:
        log.info("duplicate event skipped", extra={"step": "pubsub_dedupe", "topic": topic, "key": dedupe_key,
                                                   "messageId": meta.get("messageId")})
        return {"duplicate": True, **(done.get("result") or {})}
    result = await fn()
    store.put_processed_event(dedupe_key, {"topic": topic, "messageId": meta.get("messageId"), "processedAt": utcnow(),
                                           "result": result})
    return result


# ------------------------------------------------------------------ bus selection
_bus: EventBus | None = None


def get_bus() -> EventBus:
    global _bus
    if _bus is None:
        s = get_settings()
        if s.effective_event_bus == "pubsub":
            _bus = PubSubBus(s.project_id)
        else:
            _bus = LocalBus()
            _wire_local(_bus)
    return _bus


def set_bus(bus: EventBus | None) -> None:
    global _bus
    _bus = bus
    if isinstance(bus, LocalBus):
        _wire_local(bus)


def _wire_local(bus: LocalBus) -> None:
    from . import handlers

    s = get_settings()
    bus.subscribe(s.topic_case_submitted, handlers.on_fraud_case_submitted)
    bus.subscribe(s.topic_bank_decision, handlers.on_bank_decision)


async def publish(topic: str, data: dict, attributes: dict[str, str] | None = None) -> str:
    return await get_bus().publish(topic, data, attributes)
