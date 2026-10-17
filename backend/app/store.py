"""Persistence layer. Firestore is the source of truth in the cloud; MemoryStore mirrors it offline.

Both implementations take and return plain dicts with timezone-aware datetimes.
"""
from __future__ import annotations

import copy
import json
import logging
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol

from .config import get_settings
from .timeutil import ensure_utc, utcnow

log = logging.getLogger("recoverai.store")


def new_id(prefix: str = "") -> str:
    return f"{prefix}{uuid.uuid4().hex[:20]}"


def _seq() -> int:
    return time.time_ns()


class Store(Protocol):
    # cases
    def create_case(self, data: dict) -> str: ...
    def get_case(self, case_id: str) -> dict | None: ...
    def update_case(self, case_id: str, patch: dict) -> None: ...
    def delete_case(self, case_id: str) -> None: ...
    def list_cases(self, owner_uid: str | None = None) -> list[dict]: ...
    # messages
    def add_message(self, case_id: str, msg: dict) -> dict: ...
    def list_messages(self, case_id: str, limit: int | None = None) -> list[dict]: ...
    # evidence
    def add_evidence(self, case_id: str, ev: dict) -> dict: ...
    def list_evidence(self, case_id: str) -> list[dict]: ...
    def get_evidence(self, case_id: str, evidence_id: str) -> dict | None: ...
    # bank
    def put_bank_case(self, bank_case_id: str, data: dict) -> None: ...
    def get_bank_case(self, bank_case_id: str) -> dict | None: ...
    def update_bank_case(self, bank_case_id: str, patch: dict) -> None: ...
    def list_bank_cases(self, limit: int = 100) -> list[dict]: ...
    def delete_bank_case(self, bank_case_id: str) -> None: ...
    def create_bank_case_if_absent(self, bank_case_id: str, data: dict) -> bool: ...
    # Pub/Sub dedupe (F15)
    def get_processed_event(self, event_key: str) -> dict | None: ...
    def put_processed_event(self, event_key: str, data: dict) -> None: ...
    def delete_processed_events(self) -> int: ...
    def add_audit(self, entry: dict) -> dict: ...
    def list_audit(self, bank_case_id: str | None = None, case_id: str | None = None) -> list[dict]: ...
    def delete_audit(self, audit_id: str) -> None: ...


# --------------------------------------------------------------------------- memory


def _enc(o: Any) -> Any:
    if isinstance(o, datetime):
        return {"$dt": ensure_utc(o).isoformat()}
    if isinstance(o, dict):
        return {k: _enc(v) for k, v in o.items()}
    if isinstance(o, list):
        return [_enc(v) for v in o]
    return o


def _dec(o: Any) -> Any:
    if isinstance(o, dict):
        if set(o.keys()) == {"$dt"}:
            return datetime.fromisoformat(o["$dt"])
        return {k: _dec(v) for k, v in o.items()}
    if isinstance(o, list):
        return [_dec(v) for v in o]
    return o


class MemoryStore:
    """In-process store with optional JSON persistence (local dev / tests)."""

    def __init__(self, persist_path: str | None = None):
        self._lock = threading.RLock()
        self._path = Path(persist_path) if persist_path else None
        self.db: dict[str, dict[str, dict]] = {
            "cases": {}, "messages": {}, "evidence": {}, "bank_cases": {}, "audit_log": {}, "processed_events": {},
        }
        if self._path and self._path.exists():
            try:
                loaded = _dec(json.loads(self._path.read_text()))
                loaded.pop("bank_accounts", None)  # moved to BigQuery (F14)
                self.db.update(loaded)
            except Exception:  # corrupted local file: start fresh
                log.warning("could not load local store; starting empty")

    def _save(self) -> None:
        if self._path:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._path.with_suffix(".tmp")
            tmp.write_text(json.dumps(_enc(self.db), ensure_ascii=False))
            tmp.replace(self._path)

    # cases
    def create_case(self, data: dict) -> str:
        with self._lock:
            cid = data.get("id") or new_id("c_")
            self.db["cases"][cid] = copy.deepcopy({**data, "id": cid})
            self._save()
            return cid

    def get_case(self, case_id: str) -> dict | None:
        with self._lock:
            c = self.db["cases"].get(case_id)
            return copy.deepcopy(c) if c else None

    def update_case(self, case_id: str, patch: dict) -> None:
        with self._lock:
            if case_id not in self.db["cases"]:
                raise KeyError(case_id)
            self.db["cases"][case_id].update(copy.deepcopy(patch))
            self._save()

    def delete_case(self, case_id: str) -> None:
        with self._lock:
            self.db["cases"].pop(case_id, None)
            for col in ("messages", "evidence"):
                for k in [k for k, v in self.db[col].items() if v.get("_caseId") == case_id]:
                    self.db[col].pop(k)
            self._save()

    def list_cases(self, owner_uid: str | None = None) -> list[dict]:
        with self._lock:
            out = [copy.deepcopy(c) for c in self.db["cases"].values() if owner_uid is None or c.get("ownerUid") == owner_uid]
            return sorted(out, key=lambda c: c.get("createdAt") or utcnow(), reverse=True)

    # messages
    def add_message(self, case_id: str, msg: dict) -> dict:
        with self._lock:
            mid = msg.get("id") or new_id("m_")
            if mid in self.db["messages"]:  # idempotent write with a caller-supplied id
                return {k: v for k, v in copy.deepcopy(self.db["messages"][mid]).items() if k != "_caseId"}
            rec = {**msg, "id": mid, "seq": msg.get("seq") or _seq(), "createdAt": msg.get("createdAt") or utcnow()}
            self.db["messages"][mid] = copy.deepcopy({**rec, "_caseId": case_id})
            self._save()
            return rec

    def list_messages(self, case_id: str, limit: int | None = None) -> list[dict]:
        with self._lock:
            out = [
                {k: v for k, v in copy.deepcopy(m).items() if k != "_caseId"}
                for m in self.db["messages"].values() if m.get("_caseId") == case_id
            ]
            out.sort(key=lambda m: m["seq"])
            return out[-limit:] if limit else out

    # evidence
    def add_evidence(self, case_id: str, ev: dict) -> dict:
        with self._lock:
            eid = ev.get("id") or new_id("e_")
            rec = {**ev, "id": eid}
            self.db["evidence"][eid] = copy.deepcopy({**rec, "_caseId": case_id})
            self._save()
            return rec

    def list_evidence(self, case_id: str) -> list[dict]:
        with self._lock:
            out = [
                {k: v for k, v in copy.deepcopy(e).items() if k != "_caseId"}
                for e in self.db["evidence"].values() if e.get("_caseId") == case_id
            ]
            return sorted(out, key=lambda e: e.get("uploadedAt") or utcnow())

    def get_evidence(self, case_id: str, evidence_id: str) -> dict | None:
        with self._lock:
            e = self.db["evidence"].get(evidence_id)
            if not e or e.get("_caseId") != case_id:
                return None
            return {k: v for k, v in copy.deepcopy(e).items() if k != "_caseId"}

    # bank
    def put_bank_case(self, bank_case_id: str, data: dict) -> None:
        with self._lock:
            self.db["bank_cases"][bank_case_id] = copy.deepcopy({**data, "id": bank_case_id})
            self._save()

    def get_bank_case(self, bank_case_id: str) -> dict | None:
        with self._lock:
            b = self.db["bank_cases"].get(bank_case_id)
            return copy.deepcopy(b) if b else None

    def update_bank_case(self, bank_case_id: str, patch: dict) -> None:
        with self._lock:
            self.db["bank_cases"][bank_case_id].update(copy.deepcopy(patch))
            self._save()

    def list_bank_cases(self, limit: int = 100) -> list[dict]:
        with self._lock:
            out = [copy.deepcopy(b) for b in self.db["bank_cases"].values()]
            out.sort(key=lambda b: b.get("receivedAt") or utcnow(), reverse=True)
            return out[:limit]

    def delete_bank_case(self, bank_case_id: str) -> None:
        with self._lock:
            self.db["bank_cases"].pop(bank_case_id, None)
            self._save()

    def create_bank_case_if_absent(self, bank_case_id: str, data: dict) -> bool:
        with self._lock:
            if bank_case_id in self.db["bank_cases"]:
                return False
            self.db["bank_cases"][bank_case_id] = copy.deepcopy({**data, "id": bank_case_id})
            self._save()
            return True

    def get_processed_event(self, event_key: str) -> dict | None:
        with self._lock:
            e = self.db["processed_events"].get(event_key)
            return copy.deepcopy(e) if e else None

    def put_processed_event(self, event_key: str, data: dict) -> None:
        with self._lock:
            self.db["processed_events"][event_key] = copy.deepcopy({**data, "id": event_key})
            self._save()

    def delete_processed_events(self) -> int:
        with self._lock:
            n = len(self.db["processed_events"])
            self.db["processed_events"].clear()
            self._save()
            return n

    def add_audit(self, entry: dict) -> dict:
        with self._lock:
            aid = new_id("a_")
            rec = {**entry, "id": aid, "at": entry.get("at") or utcnow()}
            self.db["audit_log"][aid] = copy.deepcopy(rec)
            self._save()
            return rec

    def list_audit(self, bank_case_id: str | None = None, case_id: str | None = None) -> list[dict]:
        with self._lock:
            out = [
                copy.deepcopy(a) for a in self.db["audit_log"].values()
                if (bank_case_id is None or a.get("bankCaseId") == bank_case_id)
                and (case_id is None or a.get("caseId") == case_id)
            ]
            return sorted(out, key=lambda a: a["at"])

    def delete_audit(self, audit_id: str) -> None:
        with self._lock:
            self.db["audit_log"].pop(audit_id, None)
            self._save()


# --------------------------------------------------------------------------- firestore


class FirestoreStore:
    """Firestore (native mode) implementation. Uses ADC on Cloud Run."""

    def __init__(self, project: str | None = None):
        from google.cloud import firestore  # imported lazily so mock mode needs no GCP libs at runtime

        self._fs = firestore
        self.client = firestore.Client(project=project or None)

    def _cases(self):
        return self.client.collection("cases")

    def create_case(self, data: dict) -> str:
        ref = self._cases().document(data.get("id") or new_id("c_"))
        ref.set({**data, "id": ref.id})
        return ref.id

    def get_case(self, case_id: str) -> dict | None:
        snap = self._cases().document(case_id).get()
        return {**snap.to_dict(), "id": snap.id} if snap.exists else None

    def update_case(self, case_id: str, patch: dict) -> None:
        # update() replaces each top-level field wholesale (no deep merge surprises).
        self._cases().document(case_id).update(patch)

    def delete_case(self, case_id: str) -> None:
        ref = self._cases().document(case_id)
        for sub in ("messages", "evidence"):
            for d in ref.collection(sub).stream():
                d.reference.delete()
        ref.delete()

    def list_cases(self, owner_uid: str | None = None) -> list[dict]:
        q = self._cases()
        if owner_uid:
            q = q.where(filter=self._fs.FieldFilter("ownerUid", "==", owner_uid))
        out = [{**d.to_dict(), "id": d.id} for d in q.stream()]
        return sorted(out, key=lambda c: c.get("createdAt") or utcnow(), reverse=True)

    def add_message(self, case_id: str, msg: dict) -> dict:
        """A caller-supplied id makes the write idempotent (Pub/Sub redelivery): an existing message is returned as is."""
        from google.api_core.exceptions import AlreadyExists

        ref = self._cases().document(case_id).collection("messages").document(msg.get("id") or new_id("m_"))
        rec = {**msg, "id": ref.id, "seq": msg.get("seq") or _seq(), "createdAt": msg.get("createdAt") or utcnow()}
        try:
            ref.create(rec)
        except AlreadyExists:
            snap = ref.get()
            return {**snap.to_dict(), "id": snap.id}
        return rec

    def list_messages(self, case_id: str, limit: int | None = None) -> list[dict]:
        col = self._cases().document(case_id).collection("messages")
        if limit:
            docs = col.order_by("seq", direction=self._fs.Query.DESCENDING).limit(limit).stream()
            return list(reversed([{**d.to_dict(), "id": d.id} for d in docs]))
        return [{**d.to_dict(), "id": d.id} for d in col.order_by("seq").stream()]

    def add_evidence(self, case_id: str, ev: dict) -> dict:
        ref = self._cases().document(case_id).collection("evidence").document(ev.get("id") or new_id("e_"))
        rec = {**ev, "id": ref.id}
        ref.set(rec)
        return rec

    def list_evidence(self, case_id: str) -> list[dict]:
        docs = self._cases().document(case_id).collection("evidence").stream()
        return sorted(({**d.to_dict(), "id": d.id} for d in docs), key=lambda e: e.get("uploadedAt") or utcnow())

    def get_evidence(self, case_id: str, evidence_id: str) -> dict | None:
        snap = self._cases().document(case_id).collection("evidence").document(evidence_id).get()
        return {**snap.to_dict(), "id": snap.id} if snap.exists else None

    def put_bank_case(self, bank_case_id: str, data: dict) -> None:
        self.client.collection("bank_cases").document(bank_case_id).set({**data, "id": bank_case_id})

    def get_bank_case(self, bank_case_id: str) -> dict | None:
        snap = self.client.collection("bank_cases").document(bank_case_id).get()
        return {**snap.to_dict(), "id": snap.id} if snap.exists else None

    def update_bank_case(self, bank_case_id: str, patch: dict) -> None:
        self.client.collection("bank_cases").document(bank_case_id).update(patch)

    def list_bank_cases(self, limit: int = 100) -> list[dict]:
        q = self.client.collection("bank_cases").order_by("receivedAt", direction=self._fs.Query.DESCENDING).limit(limit)
        return [{**d.to_dict(), "id": d.id} for d in q.stream()]

    def delete_bank_case(self, bank_case_id: str) -> None:
        self.client.collection("bank_cases").document(bank_case_id).delete()

    def create_bank_case_if_absent(self, bank_case_id: str, data: dict) -> bool:
        from google.api_core.exceptions import AlreadyExists

        try:
            self.client.collection("bank_cases").document(bank_case_id).create({**data, "id": bank_case_id})
            return True
        except AlreadyExists:
            return False

    def get_processed_event(self, event_key: str) -> dict | None:
        snap = self.client.collection("processed_events").document(event_key).get()
        return {**snap.to_dict(), "id": snap.id} if snap.exists else None

    def put_processed_event(self, event_key: str, data: dict) -> None:
        self.client.collection("processed_events").document(event_key).set({**data, "id": event_key})

    def delete_processed_events(self) -> int:
        n = 0
        for d in self.client.collection("processed_events").stream():
            d.reference.delete()
            n += 1
        return n

    def add_audit(self, entry: dict) -> dict:
        ref = self.client.collection("audit_log").document(new_id("a_"))
        rec = {**entry, "id": ref.id, "at": entry.get("at") or utcnow()}
        ref.set(rec)
        return rec

    def list_audit(self, bank_case_id: str | None = None, case_id: str | None = None) -> list[dict]:
        q = self.client.collection("audit_log")
        if bank_case_id:
            q = q.where(filter=self._fs.FieldFilter("bankCaseId", "==", bank_case_id))
        if case_id:
            q = q.where(filter=self._fs.FieldFilter("caseId", "==", case_id))
        return sorted(({**d.to_dict(), "id": d.id} for d in q.stream()), key=lambda a: a["at"])

    def delete_audit(self, audit_id: str) -> None:
        self.client.collection("audit_log").document(audit_id).delete()


_store: Store | None = None


def get_store() -> Store:
    global _store
    if _store is None:
        s = get_settings()
        if s.mock_mode:
            persist = None if s.local_data_dir in ("", ":memory:") else str(Path(s.local_data_dir) / "db.json")
            _store = MemoryStore(persist)
        else:
            _store = FirestoreStore(s.project_id or None)
    return _store


def set_store(store: Store | None) -> None:
    global _store
    _store = store
