"""Ordered project/run-scoped lifecycle event delivery."""

from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
import time
from typing import Any

from core.storage import validate_identifier


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


class RunEventType(str, Enum):
    """Valid lifecycle facts emitted by one Workflow run."""

    RUN_STARTED = "run_started"
    NODE_STATE = "node_state"
    NODE_COMPLETED = "node_completed"
    NODE_FAILED = "node_failed"
    NODE_BLOCKED = "node_blocked"
    NODE_CANCELLED = "node_cancelled"
    RUN_COMPLETED = "run_completed"
    RUN_FAILED = "run_failed"
    RUN_CANCELLED = "run_cancelled"

    @property
    def is_run_terminal(self) -> bool:
        return self in {
            RunEventType.RUN_COMPLETED,
            RunEventType.RUN_FAILED,
            RunEventType.RUN_CANCELLED,
        }


@dataclass(frozen=True)
class RunLifecycleEvent:
    """One immutable event before WebSocket JSON serialization."""

    event_type: RunEventType
    project_id: str
    run_id: str
    sequence: int
    timestamp: str
    node_id: str | None = None
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        event: dict[str, Any] = {
            "type": self.event_type.value,
            "project_id": self.project_id,
            "run_id": self.run_id,
            "sequence": self.sequence,
            "timestamp": self.timestamp,
        }
        if self.node_id is not None:
            event["node_id"] = self.node_id
        event.update(self.details)
        return event


@dataclass(frozen=True)
class RunEventSubscription:
    """Atomic replay snapshot plus a bounded queue of later events."""

    replay: tuple[dict[str, Any], ...]
    live: asyncio.Queue[dict[str, Any] | None]


class SubscriberLimitError(RuntimeError):
    """A run already has the maximum number of live subscribers."""


class RunCapacityError(ValueError):
    """A Workflow is too large for bounded lifecycle replay."""

    def __init__(self, *, nodes: int, edges: int) -> None:
        self.nodes = nodes
        self.edges = edges
        super().__init__("Workflow exceeds run lifecycle capacity")


@dataclass
class RunEventStream:
    """One ordered event history with bounded live-subscriber queues."""

    project_id: str
    run_id: str
    max_subscribers: int = 32
    subscriber_queue_size: int = 256
    _on_terminal: Callable[["RunEventStream"], None] | None = field(
        default=None,
        repr=False,
    )
    _events: list[RunLifecycleEvent] = field(default_factory=list)
    _subscribers: set[asyncio.Queue[dict[str, Any] | None]] = field(
        default_factory=set
    )
    _overflowed: set[asyncio.Queue[dict[str, Any] | None]] = field(
        default_factory=set
    )
    _started_monotonic: float = field(default_factory=time.monotonic)
    _terminal: bool = False

    def __post_init__(self) -> None:
        self.project_id = validate_identifier(self.project_id, "project_id")
        self.run_id = validate_identifier(self.run_id, "run_id")
        if self.max_subscribers < 1 or self.subscriber_queue_size < 1:
            raise ValueError("Run event stream bounds must be positive")

    def publish(
        self,
        event_type: RunEventType,
        *,
        node_id: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Append one event and fan it out without blocking execution."""
        if self._terminal:
            raise RuntimeError("Run event stream is already terminal")
        reserved = {
            "type",
            "project_id",
            "run_id",
            "sequence",
            "timestamp",
            "node_id",
        }
        safe_details = (
            {
                key: value
                for key, value in (details or {}).items()
                if key not in reserved
            }
        )
        lifecycle_event = RunLifecycleEvent(
            event_type=event_type,
            project_id=self.project_id,
            run_id=self.run_id,
            sequence=len(self._events) + 1,
            timestamp=_timestamp(),
            node_id=(
                validate_identifier(node_id, "node_id")
                if node_id is not None
                else None
            ),
            details=safe_details,
        )
        self._events.append(lifecycle_event)
        event = lifecycle_event.to_dict()

        slow_subscribers: list[asyncio.Queue[dict[str, Any] | None]] = []
        for subscriber in self._subscribers:
            if subscriber in self._overflowed:
                continue
            try:
                subscriber.put_nowait(dict(event))
            except asyncio.QueueFull:
                slow_subscribers.append(subscriber)
        for subscriber in slow_subscribers:
            self._overflowed.add(subscriber)
            while not subscriber.empty():
                subscriber.get_nowait()
            subscriber.put_nowait(None)
        if event_type.is_run_terminal:
            self._terminal = True
            if self._on_terminal is not None:
                self._on_terminal(self)
        return event

    def subscribe(
        self,
    ) -> RunEventSubscription:
        """Atomically snapshot replay and subscribe to later bounded events."""
        if len(self._subscribers) >= self.max_subscribers:
            raise SubscriberLimitError(
                "Run has too many lifecycle subscribers"
            )
        queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue(
            maxsize=self.subscriber_queue_size
        )
        self._subscribers.add(queue)
        return RunEventSubscription(
            replay=tuple(event.to_dict() for event in self._events),
            live=queue,
        )

    def unsubscribe(
        self,
        subscription: RunEventSubscription,
    ) -> None:
        self._subscribers.discard(subscription.live)
        self._overflowed.discard(subscription.live)

    @property
    def terminal(self) -> bool:
        return self._terminal

    @property
    def elapsed_ms(self) -> int:
        return max(0, int((time.monotonic() - self._started_monotonic) * 1000))


class RunEventBroker:
    """Own exact project/run streams; never multiplex between scopes."""

    def __init__(self, *, max_completed_streams: int = 32) -> None:
        if max_completed_streams < 1:
            raise ValueError("Completed stream retention must be positive")
        self._streams: dict[tuple[str, str], RunEventStream] = {}
        self._completed: deque[tuple[str, str]] = deque()
        self._max_completed_streams = max_completed_streams

    def create(self, project_id: str, run_id: str) -> RunEventStream:
        safe_project_id = validate_identifier(project_id, "project_id")
        safe_run_id = validate_identifier(run_id, "run_id")
        key = (safe_project_id, safe_run_id)
        if key in self._streams:
            raise ValueError("Run event stream already exists")
        stream = RunEventStream(
            safe_project_id,
            safe_run_id,
            _on_terminal=self._retain_terminal,
        )
        self._streams[key] = stream
        return stream

    def _retain_terminal(self, stream: RunEventStream) -> None:
        key = (stream.project_id, stream.run_id)
        self._completed.append(key)
        while len(self._completed) > self._max_completed_streams:
            expired = self._completed.popleft()
            expired_stream = self._streams.get(expired)
            if expired_stream is not None and expired_stream.terminal:
                del self._streams[expired]

    def get(self, project_id: str, run_id: str) -> RunEventStream | None:
        safe_project_id = validate_identifier(project_id, "project_id")
        safe_run_id = validate_identifier(run_id, "run_id")
        return self._streams.get((safe_project_id, safe_run_id))

    def clear(self) -> None:
        self._streams.clear()
        self._completed.clear()
