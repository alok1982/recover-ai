"""RecoverAI API — FastAPI app served on Cloud Run."""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import get_settings
from .logging_setup import setup_logging

setup_logging()
settings = get_settings()

app = FastAPI(title="RecoverAI API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.allowed_origins),
    allow_credentials=False,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-A2A-Token"],
)


@app.get("/healthz")
def healthz() -> dict:
    return {"ok": True, "mock": settings.mock_mode, "demo": settings.demo_mode}
