"""In-memory event bus for live edge dashboard updates."""

import logging
import queue
import threading
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

READING = "reading"
THRESHOLDS = "thresholds"
FLOW = "flow"

SENSITIVE_KEYS = {
    "api_key",
    "apikey",
    "apiKey",
    "authorization",
    "password",
    "token",
    "x-api-key",
    "X-API-Key",
}


def redact(value: Any):
    if isinstance(value, dict):
        return {
            key: "***"
            if str(key) in SENSITIVE_KEYS or str(key).lower() in SENSITIVE_KEYS
            else redact(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact(item) for item in value]
    return value


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class EventBus:
    """Thread-safe pub/sub where each subscriber owns its queue."""

    def __init__(self):
        self._subscribers: set[queue.Queue] = set()
        self._lock = threading.Lock()

    def subscribe(self) -> "queue.Queue[dict]":
        q: queue.Queue[dict] = queue.Queue(maxsize=100)
        with self._lock:
            self._subscribers.add(q)
        return q

    def unsubscribe(self, q) -> None:
        with self._lock:
            self._subscribers.discard(q)

    def publish(self, event_type: str, payload: dict | None = None) -> None:
        event = {
            "type": event_type,
            "payload": redact(payload or {}),
            "at": utc_now(),
        }
        with self._lock:
            subscribers = list(self._subscribers)
        for q in subscribers:
            try:
                q.put_nowait(event)
            except queue.Full:
                logger.debug("Drop %s: subscriber queue is full", event_type)


bus = EventBus()
