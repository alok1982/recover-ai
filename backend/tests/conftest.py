import os
import sys
from pathlib import Path

os.environ.update({"MOCK_MODE": "true", "DEMO_MODE": "true", "AUTH_MODE": "mock", "LOCAL_DATA_DIR": ":memory:",
                   "SEED_ON_STARTUP": "true", "ALLOWED_ORIGINS": "http://localhost:5173"})
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import storage, store  # noqa: E402
from app.llm import set_llm  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
FIX = REPO / "fixtures"


@pytest.fixture(autouse=True)
def fresh_state(tmp_path):
    store.set_store(store.MemoryStore())
    storage.set_blobs(storage.LocalBlobStore(str(tmp_path / "blobs")))
    set_llm(None)
    yield
    store.set_store(None)
    storage.set_blobs(None)


@pytest.fixture
def client():
    from app.main import create_app

    with TestClient(create_app()) as c:
        yield c


def H(uid="victim1"):
    return {"Authorization": f"Bearer mock:{uid}"}


BANK = {"Authorization": "Bearer mock:bank:Rahul"}
