"""Ordered project/run-scoped lifecycle event delivery."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from core.storage import validate_identifier


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class RunEventStream:
    """One ordered event history with bounded live-subscriber queues."""

    project_id: str
    run_id: str
    _events: list[dict[str, Any]] = field(default_factory=list)
    _subscribers: set[asyncio.Queue[dict[str, Any] | None]] = field(
        default_factory=set
    )

    def __post_init__(self) -> None:
        self.project_id = validate_identifier(self.project_id, "project_id")
        self.run_id = validate_identifier(self.run_id, "run_id")

    def publish(
        self,
        event_type: str,
        *,
        node_id: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Append one event and fan it out without blocking execution."""
        event: dict[str, Any] = {
            "type": event_type,
            "project_id": self.project_id,
            "run_id": self.run_id,
            "sequence": len(self._events) + 1,
            "timestamp": _timestamp(),
        }
        if node_id is not None:
            event["node_id"] = validate_identifier(node_id, "node_id")
        if details:
            reserved = {
                "type",
                "project_id",
                "run_id",
                "sequence",
                "timestamp",
                "node_id",
            }
            event.update({
                key: value
                for key, value in details.items()
                if key not in reserved
            })
        self._events.append(event)

        slow_subscribers: list[asyncio.Queue[dict[str, Any] | None]] = []
        for subscriber in self._subscribers:
            try:
                subscriber.put_nowait(dict(event))
            except asyncio.QueueFull:
                slow_subscribers.append(subscriber)
        for subscriber in slow_subscribers:
            self._subscribers.discard(subscriber)
            try:
                subscriber.get_nowait()
            except asyncio.QueueEmpty:
                pass
            subscriber.put_nowait(None)
        return event

    def subscribe(
        self,
    ) -> asyncio.Queue[dict[str, Any] | None]:
        """Subscribe with a complete replay followed by live events."""
        queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue(
            maxsize=max(256, len(self._events) + 1)
        )
        for event in self._events:
            queue.put_nowait(dict(event))
        self._subscribers.add(queue)
        return queue

    def unsubscribe(
        self,
        queue: asyncio.Queue[dict[str, Any] | None],
    ) -> None:
        self._subscribers.discard(queue)


class RunEventBroker:
    """Own exact project/run streams; never multiplex between scopes."""

    def __init__(self) -> None:
        self._streams: dict[tuple[str, str], RunEventStream] = {}

    def create(self, project_id: str, run_id: str) -> RunEventStream:
        safe_project_id = validate_identifier(project_id, "project_id")
        safe_run_id = validate_identifier(run_id, "run_id")
        key = (safe_project_id, safe_run_id)
        if key in self._streams:
            raise ValueError("Run event stream already exists")
        stream = RunEventStream(safe_project_id, safe_run_id)
        self._streams[key] = stream
        return stream

    def get(self, project_id: str, run_id: str) -> RunEventStream | None:
        safe_project_id = validate_identifier(project_id, "project_id")
        safe_run_id = validate_identifier(run_id, "run_id")
        return self._streams.get((safe_project_id, safe_run_id))

    def clear(self) -> None:
        self._streams.clear()
