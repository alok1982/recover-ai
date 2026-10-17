"""Runtime configuration, read once from environment variables."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
REPO_DIR = BACKEND_DIR.parent


def _bool(name: str, default: bool) -> bool:
    v = os.getenv(name)
    if v is None or v == "":
        return default
    return v.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    mock_mode: bool = field(default_factory=lambda: _bool("MOCK_MODE", False))
    demo_mode: bool = field(default_factory=lambda: _bool("DEMO_MODE", True))
    auth_mode: str = field(default_factory=lambda: os.getenv("AUTH_MODE", ""))
    project_id: str = field(default_factory=lambda: os.getenv("GOOGLE_CLOUD_PROJECT", ""))
    location: str = field(default_factory=lambda: os.getenv("GOOGLE_CLOUD_LOCATION", "asia-south1"))
    gemini_location: str = field(default_factory=lambda: os.getenv("GEMINI_LOCATION", "") or os.getenv("GOOGLE_CLOUD_LOCATION", "global"))
    gemini_model: str = field(default_factory=lambda: os.getenv("GEMINI_MODEL", "gemini-3.8-flash"))
    gemini_lite_model: str = field(default_factory=lambda: os.getenv("GEMINI_LITE_MODEL", "gemini-3.5-flash-lite"))
    evidence_bucket: str = field(default_factory=lambda: os.getenv("EVIDENCE_BUCKET", ""))
    allowed_origins: tuple[str, ...] = field(
        default_factory=lambda: tuple(
            o.strip()
            for o in (os.getenv("ALLOWED_ORIGINS") or os.getenv("ALLOWED_ORIGIN") or "http://localhost:5173").split(",")
            if o.strip()
        )
    )
    # F15 Pub/Sub: "pubsub" in production; "local" delivers push messages in-process (mock mode / tests)
    event_bus: str = field(default_factory=lambda: os.getenv("EVENT_BUS", ""))
    topic_case_submitted: str = field(default_factory=lambda: os.getenv("TOPIC_CASE_SUBMITTED", "fraud-case-submitted"))
    topic_bank_decision: str = field(default_factory=lambda: os.getenv("TOPIC_BANK_DECISION", "bank-decision"))
    push_audience: str = field(default_factory=lambda: os.getenv("PUSH_AUDIENCE", ""))
    push_sa_email: str = field(default_factory=lambda: os.getenv("PUSH_SA_EMAIL", ""))
    # F14 BigQuery: "bigquery" in production; "local" = synthetic rows in-process
    analytics_backend: str = field(default_factory=lambda: os.getenv("ANALYTICS_BACKEND", ""))
    bq_dataset: str = field(default_factory=lambda: os.getenv("BQ_DATASET", "recoverai_analytics"))
    bq_location: str = field(default_factory=lambda: os.getenv("BQ_LOCATION", ""))
    enable_ml_score: bool = field(default_factory=lambda: _bool("ENABLE_ML_SCORE", True))
    # F16 Vertex AI Search serving config, e.g.
    # projects/P/locations/global/collections/default_collection/engines/recoverai-rules/servingConfigs/default_search
    vertex_search_serving_config: str = field(default_factory=lambda: os.getenv("VERTEX_SEARCH_SERVING_CONFIG", ""))
    knowledge_dir: str = field(default_factory=lambda: os.getenv("KNOWLEDGE_DIR", str(REPO_DIR / "knowledge")))
    copilot_runtime: str = field(default_factory=lambda: os.getenv("COPILOT_RUNTIME", "cloudrun"))
    agent_engine_resource: str = field(default_factory=lambda: os.getenv("AGENT_ENGINE_RESOURCE", ""))
    seed_on_startup: bool = field(default_factory=lambda: _bool("SEED_ON_STARTUP", True))
    local_data_dir: str = field(default_factory=lambda: os.getenv("LOCAL_DATA_DIR", str(BACKEND_DIR / ".localdata")))
    public_base_url: str = field(default_factory=lambda: os.getenv("PUBLIC_BASE_URL", "http://localhost:8080"))
    # Abuse limits (NFR)
    max_open_cases_per_user: int = field(default_factory=lambda: int(os.getenv("MAX_OPEN_CASES", "3")))
    max_turns_per_hour: int = field(default_factory=lambda: int(os.getenv("MAX_TURNS_PER_HOUR", "30")))
    max_evidence_per_case: int = field(default_factory=lambda: int(os.getenv("MAX_EVIDENCE_PER_CASE", "10")))
    max_image_bytes: int = 10 * 1024 * 1024
    max_audio_bytes: int = 8 * 1024 * 1024  # ~2 min of compressed audio
    max_text_chars: int = 20_000
    gemini_timeout_s: float = 45.0
    gemini_retries: int = 2

    @property
    def effective_event_bus(self) -> str:
        return self.event_bus or ("local" if self.mock_mode else "pubsub")

    @property
    def effective_analytics_backend(self) -> str:
        return self.analytics_backend or ("local" if self.mock_mode else "bigquery")

    @property
    def effective_auth_mode(self) -> str:
        if self.auth_mode:
            return self.auth_mode
        return "mock" if self.mock_mode else "firebase"


@lru_cache
def get_settings() -> Settings:
    return Settings()


def reset_settings_cache() -> None:
    get_settings.cache_clear()
