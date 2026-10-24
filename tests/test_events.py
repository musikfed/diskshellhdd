from __future__ import annotations

import queue

from backend.core.events import emit_event, subscribe, subscriber_count, unsubscribe


def test_event_fabric_delivers_typed_payload():
    subscriber = subscribe()
    try:
        assert subscriber_count() >= 1
        emitted = emit_event("workspace.changed", {"active_page": "files"})
        received = subscriber.get(timeout=1)
        assert received["id"] == emitted["id"]
        assert received["type"] == "workspace.changed"
        assert received["payload"]["active_page"] == "files"
        assert received["at"]
    finally:
        unsubscribe(subscriber)


def test_event_fabric_unsubscribe_stops_delivery():
    subscriber = subscribe()
    unsubscribe(subscriber)
    emit_event("test.after_unsubscribe", {"ok": True})
    try:
        subscriber.get_nowait()
    except queue.Empty:
        pass
    else:
        raise AssertionError("unsubscribed queue received an event")
