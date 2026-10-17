"""RecoverAI API — FastAPI app served on Cloud Run."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .config import get_settings
from .logging_setup import setup_logging
from .routers import bank, cases, events, local_blob
from .timeutil import utcnow

setup_logging()
log = logging.getLogger("recoverai")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    s = get_settings()
    if s.seed_on_startup and s.effective_analytics_backend == "local":
        try:  # offline: build the synthetic transaction data once (BigQuery is seeded by scripts/seed_bigquery.py)
            from .analytics.bq import get_analytics

            get_analytics().features("warmup", utcnow())
        except Exception:  # noqa: BLE001 - never block startup on seeding
            log.exception("local analytics warm-up failed")
    if s.effective_analytics_backend == "bigquery" or s.effective_event_bus == "pubsub":
        import threading

        def _warm() -> None:  # create clients + auth once, so the first push isn't paying for it
            try:
                if s.effective_analytics_backend == "bigquery":
                    from .analytics.bq import get_analytics

                    get_analytics().features("warmup-no-such-account", utcnow())
                if s.effective_event_bus == "pubsub":
                    from .events.pubsub import get_bus

                    get_bus()
            except Exception:  # noqa: BLE001
                log.warning("cloud client warm-up failed", exc_info=True)

        threading.Thread(target=_warm, daemon=True).start()
    log.info("startup", extra={"mock": s.mock_mode, "demo": s.demo_mode, "auth": s.effective_auth_mode,
                               "model": s.gemini_model, "runtime": s.copilot_runtime, "bus": s.effective_event_bus,
                               "analytics": s.effective_analytics_backend,
                               "search": "vertex" if s.vertex_search_serving_config else "local/playbook"})
    yield


def create_app() -> FastAPI:
    s = get_settings()
    app = FastAPI(title="RecoverAI API", version="1.0.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(s.allowed_origins),
        allow_credentials=False,
        allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
    )
    app.include_router(cases.router)
    app.include_router(bank.router)
    app.include_router(bank.api_router)
    app.include_router(events.router)
    if s.mock_mode:
        app.include_router(local_blob.router)

    @app.exception_handler(Exception)
    async def unhandled(request: Request, exc: Exception):  # friendly retry instead of a stack trace
        log.exception("unhandled error", extra={"path": request.url.path})
        return JSONResponse({"detail": "Something went wrong. Please try again."}, status_code=500)

    @app.get("/healthz")
    @app.get("/api/healthz")
    @app.get("/api/health")  # Cloud Run reserves paths ending in "z" (/healthz never reaches the container)
    def healthz() -> dict:
        return {"ok": True, "mock": s.mock_mode, "demo": s.demo_mode, "runtime": s.copilot_runtime}

    return app


app = create_app()
