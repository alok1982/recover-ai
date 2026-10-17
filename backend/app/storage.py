"""Evidence/audio/PDF blobs: private Cloud Storage bucket + V4 signed URLs (15 min).

LocalBlobStore mirrors the API on disk for offline runs; its "signed" URLs are HMAC tokens served by
/api/local-blob (only mounted in MOCK_MODE).
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import shutil
import time
from datetime import timedelta
from pathlib import Path
from typing import Protocol

from .config import get_settings

SIGNED_URL_TTL = timedelta(minutes=15)


class BlobStore(Protocol):
    def upload_url(self, path: str, mime_type: str, max_bytes: int) -> dict: ...
    def read_url(self, path: str, download_name: str | None = None) -> str: ...
    def read_bytes(self, path: str) -> bytes: ...
    def write_bytes(self, path: str, data: bytes, mime_type: str) -> None: ...
    def size(self, path: str) -> int | None: ...
    def gs_uri(self, path: str) -> str | None: ...
    def delete_prefix(self, prefix: str) -> None: ...


class GCSBlobStore:
    def __init__(self, bucket: str):
        from google.cloud import storage

        self.client = storage.Client()
        self.bucket_name = bucket
        self.bucket = self.client.bucket(bucket)

    def _signing_kwargs(self) -> dict:
        """On Cloud Run there is no private key: sign via IAM signBlob (needs serviceAccountTokenCreator on itself)."""
        import google.auth
        from google.auth.transport.requests import Request
        from google.oauth2 import service_account

        creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
        if isinstance(creds, service_account.Credentials):
            return {}  # key-based creds sign locally
        creds.refresh(Request())
        email = getattr(creds, "service_account_email", None)
        if not email:
            raise RuntimeError("signed URLs need service-account credentials (run on Cloud Run or impersonate an SA)")
        return {"service_account_email": email, "access_token": creds.token}

    def upload_url(self, path: str, mime_type: str, max_bytes: int) -> dict:
        blob = self.bucket.blob(path)
        headers = {"x-goog-content-length-range": f"0,{max_bytes}"}
        url = blob.generate_signed_url(
            version="v4", expiration=SIGNED_URL_TTL, method="PUT", content_type=mime_type,
            headers=headers, **self._signing_kwargs(),
        )
        return {"url": url, "method": "PUT", "headers": {"Content-Type": mime_type, **headers}, "path": path}

    def read_url(self, path: str, download_name: str | None = None) -> str:
        kw = {}
        if download_name:
            kw["response_disposition"] = f'attachment; filename="{download_name}"'
        return self.bucket.blob(path).generate_signed_url(
            version="v4", expiration=SIGNED_URL_TTL, method="GET", **kw, **self._signing_kwargs()
        )

    def read_bytes(self, path: str) -> bytes:
        return self.bucket.blob(path).download_as_bytes()

    def write_bytes(self, path: str, data: bytes, mime_type: str) -> None:
        self.bucket.blob(path).upload_from_string(data, content_type=mime_type)

    def size(self, path: str) -> int | None:
        blob = self.bucket.get_blob(path)
        return blob.size if blob else None

    def gs_uri(self, path: str) -> str | None:
        return f"gs://{self.bucket_name}/{path}"

    def delete_prefix(self, prefix: str) -> None:
        for b in self.client.list_blobs(self.bucket_name, prefix=prefix):
            b.delete()


class LocalBlobStore:
    def __init__(self, root: str):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._key = (os.getenv("LOCAL_BLOB_KEY") or secrets.token_hex(16)).encode()

    def _p(self, path: str) -> Path:
        p = (self.root / path).resolve()
        if not str(p).startswith(str(self.root.resolve())):
            raise ValueError("bad path")
        return p

    def make_token(self, path: str, method: str, max_bytes: int = 0, mime: str = "", name: str = "") -> str:
        body = json.dumps({"p": path, "m": method, "x": int(time.time() + SIGNED_URL_TTL.total_seconds()),
                           "n": max_bytes, "t": mime, "d": name}).encode()
        sig = hmac.new(self._key, body, hashlib.sha256).hexdigest()[:32]
        return base64.urlsafe_b64encode(body).decode().rstrip("=") + "." + sig

    def check_token(self, token: str, method: str) -> dict:
        b64, _, sig = token.partition(".")
        body = base64.urlsafe_b64decode(b64 + "=" * (-len(b64) % 4))
        if not hmac.compare_digest(hmac.new(self._key, body, hashlib.sha256).hexdigest()[:32], sig):
            raise PermissionError("bad signature")
        d = json.loads(body)
        if d["m"] != method or d["x"] < time.time():
            raise PermissionError("expired or wrong method")
        return d

    def upload_url(self, path: str, mime_type: str, max_bytes: int) -> dict:
        tok = self.make_token(path, "PUT", max_bytes, mime_type)
        return {"url": f"/api/local-blob/{tok}", "method": "PUT", "headers": {"Content-Type": mime_type}, "path": path}

    def read_url(self, path: str, download_name: str | None = None) -> str:
        return f"/api/local-blob/{self.make_token(path, 'GET', name=download_name or '')}"

    def read_bytes(self, path: str) -> bytes:
        return self._p(path).read_bytes()

    def write_bytes(self, path: str, data: bytes, mime_type: str) -> None:
        p = self._p(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
        p.with_name(p.name + ".mime").write_text(mime_type)

    def mime(self, path: str) -> str:
        m = self._p(path).with_name(self._p(path).name + ".mime")
        return m.read_text() if m.exists() else "application/octet-stream"

    def size(self, path: str) -> int | None:
        p = self._p(path)
        return p.stat().st_size if p.exists() else None

    def gs_uri(self, path: str) -> str | None:
        return None

    def delete_prefix(self, prefix: str) -> None:
        p = self._p(prefix)
        if p.is_dir():
            shutil.rmtree(p)


_blobs: BlobStore | None = None


def get_blobs() -> BlobStore:
    global _blobs
    if _blobs is None:
        s = get_settings()
        if s.mock_mode or not s.evidence_bucket:
            _blobs = LocalBlobStore(str(Path(s.local_data_dir if s.local_data_dir != ":memory:" else "/tmp/recoverai") / "blobs"))
        else:
            _blobs = GCSBlobStore(s.evidence_bucket)
    return _blobs


def set_blobs(b: BlobStore | None) -> None:
    global _blobs
    _blobs = b
