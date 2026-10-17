"""Firebase ID-token verification (anonymous victims; email/password analyst with role=bank claim)."""
from __future__ import annotations

import logging
from dataclasses import dataclass

from fastapi import Header, HTTPException

from .config import get_settings

log = logging.getLogger("recoverai.auth")
_firebase_ready = False


@dataclass(frozen=True)
class User:
    uid: str
    role: str | None = None
    name: str | None = None
    email: str | None = None

    @property
    def is_bank(self) -> bool:
        return self.role == "bank"


def _init_firebase() -> None:
    global _firebase_ready
    if not _firebase_ready:
        import firebase_admin

        if not firebase_admin._apps:
            opts = {"projectId": get_settings().project_id} if get_settings().project_id else None
            firebase_admin.initialize_app(options=opts)
        _firebase_ready = True


def verify_token(token: str) -> User:
    mode = get_settings().effective_auth_mode
    if mode == "mock":
        # Local/offline only: "mock:<uid>" or "mock:bank:<analyst name>"
        if not token.startswith("mock:"):
            raise HTTPException(401, "invalid mock token")
        parts = token.split(":", 2)
        if len(parts) == 3 and parts[1] == "bank":
            return User(uid=f"bank-{parts[2]}", role="bank", name=parts[2])
        return User(uid=parts[1] or "anon")
    _init_firebase()
    from firebase_admin import auth as fb_auth

    try:
        claims = fb_auth.verify_id_token(token, clock_skew_seconds=10)
    except Exception as e:  # noqa: BLE001
        log.info("token rejected", extra={"err": str(e)[:200]})
        raise HTTPException(401, "invalid or expired token") from e
    return User(uid=claims["uid"], role=claims.get("role"), name=claims.get("name"), email=claims.get("email"))


def current_user(authorization: str | None = Header(default=None)) -> User:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "missing bearer token")
    return verify_token(authorization.split(" ", 1)[1].strip())


def bank_user(authorization: str | None = Header(default=None)) -> User:
    user = current_user(authorization)
    if not user.is_bank:
        raise HTTPException(403, "bank analyst role required")
    return user
