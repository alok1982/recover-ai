"""Server-Sent Events with keep-alive comments (Cloud Run: --timeout 300, no buffering)."""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, AsyncIterator

from fastapi.responses import StreamingResponse

from .services import jsonable

log = logging.getLogger("recoverai.sse")
KEEPALIVE_S = 15.0


def encode(event: dict[str, Any]) -> str:
    return f"data: {json.dumps(jsonable(event), ensure_ascii=False)}\n\n"


async def with_keepalive(events: AsyncIterator[dict], interval: float = KEEPALIVE_S) -> AsyncIterator[str]:
    queue: asyncio.Queue = asyncio.Queue()
    done = object()

    async def pump() -> None:
        try:
            async for ev in events:
                await queue.put(encode(ev))
        except Exception as e:  # noqa: BLE001
            log.exception("sse producer failed")
            await queue.put(encode({"type": "error", "message": str(e)[:200]}))
        finally:
            await queue.put(done)

    task = asyncio.create_task(pump())
    try:
        while True:
            try:
                item = await asyncio.wait_for(queue.get(), timeout=interval)
            except asyncio.TimeoutError:
                yield ": keep-alive\n\n"
                continue
            if item is done:
                break
            yield item
    finally:
        if not task.done():
            task.cancel()


def sse_response(events: AsyncIterator[dict]) -> StreamingResponse:
    return StreamingResponse(
        with_keepalive(events),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no", "Connection": "keep-alive"},
    )
