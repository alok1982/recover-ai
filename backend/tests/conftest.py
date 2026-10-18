import os
import sys
from pathlib import Path

os.environ.update({"MOCK_MODE": "true", "DEMO_MODE": "true", "AUTH_MODE": "mock", "LOCAL_DATA_DIR": ":memory:",
                   "SEED_ON_STARTUP": "true", "ALLOWED_ORIGINS": "http://localhost:5173"})
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import storage, store  # noqa: E402
from app.analytics import bq  # noqa: E402
from app.events import pubsub  # noqa: E402
from app.llm import set_llm  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
FIX = REPO / "fixtures"


DEFAULT_PROFILE = {"fullName": "Test Victim", "country": "IN", "language": "en", "state": "Uttar Pradesh",
                   "district": "Lucknow", "postalCode": "226001", "primaryBank": "HDFC Bank"}


class ProfiledStore(store.MemoryStore):
    """Pre-CR-03 tests use bare mock uids ("victim1", "a", …): give them a complete profile so the existing story
    runs unchanged. Phone accounts ("ph-…") and explicitly stored users behave exactly like production."""

    def get_user(self, uid):
        u = super().get_user(uid)
        if u is None and uid and not uid.startswith("ph-"):
            prof = dict(DEFAULT_PROFILE)
            return {"uid": uid, "phoneE164": None, "phoneVerified": False, "profile": prof,
                    "profileStatus": {"complete": True, "missing": []}}
        return u

    def update_user(self, uid, patch):
        if uid not in self.db.setdefault("users", {}):
            self.set_user(uid, self.get_user(uid) or {})
        super().update_user(uid, patch)


@pytest.fixture(autouse=True)
def fresh_state(tmp_path):
    store.set_store(ProfiledStore())
    storage.set_blobs(storage.LocalBlobStore(str(tmp_path / "blobs")))
    set_llm(None)
    bq.set_analytics(_shared_analytics())
    pubsub.set_bus(pubsub.LocalBus())
    yield
    store.set_store(None)
    storage.set_blobs(None)
    bq.set_analytics(None)
    pubsub.set_bus(None)


_ANALYTICS = None


def _shared_analytics():
    """One synthetic dataset per test session (seeding trains the S2 model); case_events reset per test."""
    global _ANALYTICS
    if _ANALYTICS is None:
        _ANALYTICS = bq.LocalAnalytics(None)
        _ANALYTICS.seed()
        _ANALYTICS._seed_events = list(_ANALYTICS.data["case_events"])
    _ANALYTICS.data["case_events"] = list(_ANALYTICS._seed_events)
    return _ANALYTICS


@pytest.fixture
def client():
    from app.main import create_app

    with TestClient(create_app()) as c:
        yield c


def H(uid="victim1"):
    return {"Authorization": f"Bearer mock:{uid}"}


BANK = {"Authorization": "Bearer mock:bank:Rahul"}
PUSH = {"Authorization": "Bearer mock-push"}
