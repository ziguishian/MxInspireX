"""Stream observable planning stages; generation continues if the view closes."""
from __future__ import annotations

import asyncio
import contextvars
import json
import logging
import threading

from .providers.http import ProviderError


async def schedule_plan_events(service, payload):
    loop = asyncio.get_running_loop()
    events = asyncio.Queue()
    closed = threading.Event()

    def send(kind, data):
        if not closed.is_set():
            try:
                loop.call_soon_threadsafe(events.put_nowait, (kind, data))
            except RuntimeError:
                pass  # The client/event loop closed; keep the save operation independent.

    def run():
        current = None

        def progress(event):
            nonlocal current
            current = event if event["status"] == "running" else None
            send("progress", event)

        try:
            send("result", service.arrange(payload, progress=progress))
        except Exception as error:
            if isinstance(error, (ValueError, ProviderError)):
                message = str(error)
            else:
                logging.getLogger(__name__).exception("Schedule planning failed")
                message = "计划组织失败，请重试或查看本地服务日志"
            if current:
                send("progress", {**current, "status": "failed", "label": message})
            send("error", {"message": message})

    context = contextvars.copy_context()
    threading.Thread(target=lambda: context.run(run), name="schedule-planning", daemon=True).start()
    try:
        while True:
            try:
                kind, data = await asyncio.wait_for(events.get(), timeout=5)
            except TimeoutError:
                yield ": heartbeat\n\n"
                continue
            yield f"event: {kind}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
            if kind in {"result", "error"}:
                break
    finally:
        closed.set()
