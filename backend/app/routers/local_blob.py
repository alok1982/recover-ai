"""Offline stand-in for GCS signed URLs (MOCK_MODE only)."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response

from ..storage import LocalBlobStore, get_blobs

router = APIRouter(prefix="/api/local-blob", tags=["local"])


def _store() -> LocalBlobStore:
    b = get_blobs()
    if not isinstance(b, LocalBlobStore):
        raise HTTPException(404, "not available")
    return b


@router.put("/{token}")
async def put_blob(token: str, request: Request) -> dict:
    b = _store()
    try:
        d = b.check_token(token, "PUT")
    except (PermissionError, ValueError) as e:
        raise HTTPException(403, str(e)) from e
    data = await request.body()
    if d["n"] and len(data) > d["n"]:
        raise HTTPException(413, "too large")
    b.write_bytes(d["p"], data, request.headers.get("content-type") or d["t"] or "application/octet-stream")
    return {"ok": True, "size": len(data)}


@router.get("/{token}")
def get_blob(token: str) -> Response:
    b = _store()
    try:
        d = b.check_token(token, "GET")
        data = b.read_bytes(d["p"])
    except (PermissionError, ValueError, FileNotFoundError) as e:
        raise HTTPException(403, str(e)) from e
    headers = {"Content-Disposition": f'attachment; filename="{d["d"]}"'} if d.get("d") else {}
    return Response(content=data, media_type=b.mime(d["p"]), headers=headers)
