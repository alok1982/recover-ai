"""Shared eval plumbing: live Vertex AI env, in-memory stores, per-task model override and a token spy."""
from __future__ import annotations

import contextvars
import os
import sys
import tempfile
import time
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
BACKEND = HERE.parent
sys.path.insert(0, str(BACKEND))

LIVE_ENV = {
    "MOCK_MODE": "false", "DEMO_MODE": "true", "AUTH_MODE": "mock", "EVENT_BUS": "local", "ANALYTICS_BACKEND": "local",
    "CHAT_LIGHT_MODEL": "", "GOOGLE_GENAI_USE_VERTEXAI": "TRUE", "GOOGLE_CLOUD_PROJECT": "recoverai-511917",
    "GOOGLE_CLOUD_LOCATION": "asia-south1", "GEMINI_LOCATION": "global", "SEED_ON_STARTUP": "true",
    "MAX_TURNS_PER_HOUR": "100000", "MAX_OPEN_CASES": "100000", "VERTEX_SEARCH_SERVING_CONFIG": "",
}
for k, v in LIVE_ENV.items():
    os.environ.setdefault(k, v)
os.environ.setdefault("LOCAL_DATA_DIR", tempfile.mkdtemp(prefix="rai_eval_"))

# Prices (USD per 1M tokens, Vertex AI global, standard tier, Oct 2026; output includes thinking tokens).
PRICES = {
    "gemini-3.5-flash-lite": (0.30, 2.50),
    "gemini-3.1-flash-lite": (0.25, 1.50),
    "gemini-3.8-flash": (0.75, 3.75),
    "gemini-3.5-flash": (1.50, 9.00),
    "gemini-3.1-pro-preview": (2.00, 12.00),
}

current_item: contextvars.ContextVar[str | None] = contextvars.ContextVar("current_item", default=None)
USAGE: dict[str, list[dict]] = defaultdict(list)  # item id -> raw model calls


def _classify(system: str) -> str:
    s = (system or "")[:120]
    for key, task in (("You are RecoverAI, a calm", "copilot"), ("Classify whether this message", "guard"),
                      ("You are the Intake Agent", "intake"), ("You are the Playbook Agent", "plan_explain"),
                      ("You are the Filing Agent", "drafts"), ("You are the Bank Case Receiver", "bank_reason"),
                      ("Transcribe this voice", "transcribe"), ("Rewrite the assistant reply", "post_check_regen")):
        if key in s:
            return task
    return "other"


def _record(model: str, config, resp) -> None:
    um = getattr(resp, "usage_metadata", None)
    sysi = getattr(config, "system_instruction", None) if config is not None else None
    if sysi is not None and not isinstance(sysi, str):
        sysi = " ".join(getattr(p, "text", "") or "" for p in (getattr(sysi, "parts", None) or []))
    USAGE[current_item.get() or "_"].append({
        "model": model, "task": _classify(sysi or ""),
        "in": getattr(um, "prompt_token_count", None) or 0,
        "out": getattr(um, "candidates_token_count", None) or 0,
        "think": getattr(um, "thoughts_token_count", None) or 0,
        "cached": getattr(um, "cached_content_token_count", None) or 0,
    })


def install_spy() -> None:
    from google.genai import models

    if getattr(models.AsyncModels, "_eval_spy", False):
        return
    orig, orig_stream = models.AsyncModels.generate_content, models.AsyncModels.generate_content_stream

    async def gc(self, *, model, contents, config=None, **kw):
        r = await orig(self, model=model, contents=contents, config=config, **kw)
        _record(model, config, r)
        return r

    async def gcs(self, *, model, contents, config=None, **kw):
        stream = await orig_stream(self, model=model, contents=contents, config=config, **kw)

        async def wrap():
            last = None
            async for ch in stream:
                if getattr(ch, "usage_metadata", None) is not None:
                    last = ch
                yield ch
            if last is not None:
                _record(model, config, last)
        return wrap()

    models.AsyncModels.generate_content, models.AsyncModels.generate_content_stream = gc, gcs
    models.AsyncModels._eval_spy = True


def configure(task: str, model: str, thinking: str | None = None, max_output: int | None = None) -> None:
    """Point one task at a model (and thinking / max_output) for the following calls."""
    from app.config import reset_settings_cache
    from app.llm import set_llm

    os.environ[f"GEMINI_MODEL_{task.upper()}"] = model
    if thinking is None:
        os.environ.pop(f"GEMINI_THINKING_{task.upper()}", None)
    else:
        os.environ[f"GEMINI_THINKING_{task.upper()}"] = thinking
    if max_output is None:
        os.environ.pop(f"GEMINI_MAX_OUTPUT_{task.upper()}", None)
    else:
        os.environ[f"GEMINI_MAX_OUTPUT_{task.upper()}"] = str(max_output)
    reset_settings_cache()
    set_llm(None)


def fresh_state(tmp: str | None = None) -> None:
    from app import storage, store
    from app.analytics import bq
    from app.events import pubsub

    store.set_store(store.MemoryStore())
    storage.set_blobs(storage.LocalBlobStore(tmp or tempfile.mkdtemp(prefix="rai_blobs_")))
    a = bq.LocalAnalytics(None)
    a.seed()
    bq.set_analytics(a)
    pubsub.set_bus(pubsub.LocalBus())


def usage_summary(ids: list[str], task: str | None) -> dict:
    calls = [c for i in ids for c in USAGE.get(i, []) if task is None or c["task"] == task]
    n = max(1, len(ids))
    tin = sum(c["in"] for c in calls)
    tout = sum(c["out"] for c in calls)
    tth = sum(c["think"] for c in calls)
    cost = sum((c["in"] * PRICES.get(c["model"], (0, 0))[0] + (c["out"] + c["think"]) * PRICES.get(c["model"], (0, 0))[1]) / 1e6
               for c in calls)
    return {"calls": len(calls), "calls_per_item": round(len(calls) / n, 2), "avg_in": round(tin / n), "avg_out": round(tout / n),
            "avg_think": round(tth / n), "avg_total": round((tin + tout + tth) / n), "usd_per_item": round(cost / n, 6),
            "models": sorted({c["model"] for c in calls}),
            "calls_by_model": {m: sum(1 for c in calls if c["model"] == m) for m in sorted({c["model"] for c in calls})}}


class Timer:
    def __enter__(self):
        self.t = time.perf_counter()
        return self

    def __exit__(self, *a):
        self.s = time.perf_counter() - self.t
