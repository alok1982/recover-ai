"""RecoverAI API — FastAPI app served on Cloud Run."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .config import get_settings
from .logging_setup import setup_logging
from .routers import bank, cases, local_blob

setup_logging()
log = logging.getLogger("recoverai")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    s = get_settings()
    if s.seed_on_startup:
        try:
            from .seed import seed_bank_accounts

            seed_bank_accounts()
        except Exception:  # noqa: BLE001 - never block startup on seeding
            log.exception("seeding failed")
    log.info("startup", extra={"mock": s.mock_mode, "demo": s.demo_mode, "auth": s.effective_auth_mode,
                               "model": s.gemini_model, "runtime": s.copilot_runtime})
    yield


def create_app() -> FastAPI:
    s = get_settings()
    app = FastAPI(title="RecoverAI API", version="1.0.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(s.allowed_origins),
        allow_credentials=False,
        allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-A2A-Token"],
    )
    app.include_router(cases.router)
    app.include_router(bank.router)
    app.include_router(bank.api_router)
    if s.mock_mode:
        app.include_router(local_blob.router)

    @app.exception_handler(Exception)
    async def unhandled(request: Request, exc: Exception):  # friendly retry instead of a stack trace
        log.exception("unhandled error", extra={"path": request.url.path})
        return JSONResponse({"detail": "Something went wrong. Please try again."}, status_code=500)

    @app.get("/healthz")
    @app.get("/api/healthz")
    def healthz() -> dict:
        return {"ok": True, "mock": s.mock_mode, "demo": s.demo_mode, "runtime": s.copilot_runtime}

    return app


app = create_app()
