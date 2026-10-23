from __future__ import annotations

import json
import queue

from flask import Blueprint, Response, stream_with_context

from backend.core.events import subscribe, unsubscribe


bp = Blueprint("events", __name__, url_prefix="/api/events")


@bp.get("")
def events():
    subscriber = subscribe()

    @stream_with_context
    def stream():
        try:
            yield "retry: 2500\n\n"
            while True:
                try:
                    event = subscriber.get(timeout=15)
                except queue.Empty:
                    yield ": keepalive\n\n"
                    continue
                payload = json.dumps(event, ensure_ascii=False, separators=(",", ":"))
                yield (
                    f"id: {event['id']}\n"
                    f"event: {event['type']}\n"
                    f"data: {payload}\n\n"
                )
        finally:
            unsubscribe(subscriber)

    response = Response(stream(), mimetype="text/event-stream")
    response.headers["Cache-Control"] = "no-cache, no-transform"
    response.headers["X-Accel-Buffering"] = "no"
    return response
