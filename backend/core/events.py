from __future__ import annotations

import itertools
import queue
import threading
from datetime import UTC, datetime
from typing import Any


_MAX_SUBSCRIBER_BACKLOG = 256
_counter = itertools.count(1)
_lock = threading.Lock()
_subscribers: set[queue.Queue[dict[str, Any]]] = set()


def _now() -> str:
    return datetime.now(UTC).isoformat()


def emit_event(event_type: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    event = {
        "id": next(_counter),
        "type": str(event_type),
        "at": _now(),
        "payload": dict(payload or {}),
    }
    with _lock:
        subscribers = list(_subscribers)
    for subscriber in subscribers:
        try:
            subscriber.put_nowait(event)
        except queue.Full:
            try:
                subscriber.get_nowait()
            except queue.Empty:
                pass
            try:
                subscriber.put_nowait(event)
            except queue.Full:
                pass
    return event


def subscribe() -> queue.Queue[dict[str, Any]]:
    subscriber: queue.Queue[dict[str, Any]] = queue.Queue(
        maxsize=_MAX_SUBSCRIBER_BACKLOG
    )
    with _lock:
        _subscribers.add(subscriber)
    return subscriber


def unsubscribe(subscriber: queue.Queue[dict[str, Any]]) -> None:
    with _lock:
        _subscribers.discard(subscriber)


def subscriber_count() -> int:
    with _lock:
        return len(_subscribers)
