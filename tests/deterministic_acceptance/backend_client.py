"""Small frontend-independent client for backend acceptance."""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import httpx
from websockets.exceptions import ConnectionClosed, InvalidStatus
from websockets.sync.client import connect


TRUSTED_ORIGIN = "http://127.0.0.1:5173"
TERMINAL_EVENTS = frozenset({
    "run_completed",
    "run_failed",
    "run_cancelled",
})


@dataclass(frozen=True)
class DownloadedArtifact:
    """One manifest-bound artifact retrieved through the public API."""

    payload: bytes
    sha256: str


class BackendAcceptanceClient:
    """Exercise only the REST and run-scoped WebSocket contracts."""

    def __init__(
        self,
        base_url: str,
        *,
        event_timeout_seconds: float = 30,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.event_timeout_seconds = event_timeout_seconds
        self._http = httpx.Client(
            base_url=self.base_url,
            headers={"origin": TRUSTED_ORIGIN},
            timeout=10,
        )

    def close(self) -> None:
        self._http.close()

    def _websocket_url(self, project_id: str, run_id: str) -> str:
        return (
            self.base_url.replace("http://", "ws://", 1)
            + f"/api/projects/{project_id}/run/{run_id}/ws"
        )

    def get_workflow(self, project_id: str) -> dict[str, Any]:
        response = self._http.get(f"/api/projects/{project_id}/workflow")
        response.raise_for_status()
        return response.json()

    def modules(self) -> list[dict[str, Any]]:
        response = self._http.get("/api/modules")
        response.raise_for_status()
        return response.json()

    def cache_entries(self, project_id: str) -> dict[str, Any]:
        response = self._http.get(f"/api/projects/{project_id}/cache")
        response.raise_for_status()
        return response.json()

    def create_project(self, name: str) -> str:
        response = self._http.post("/api/projects", json={"name": name})
        response.raise_for_status()
        return str(response.json()["id"])

    def save_workflow(
        self,
        project_id: str,
        workflow: dict[str, Any],
    ) -> None:
        response = self._http.put(
            f"/api/projects/{project_id}/workflow",
            json=workflow,
        )
        response.raise_for_status()

    def run_saved(
        self,
        project_id: str,
        *,
        seed: int,
        force_rerun_nodes: list[str] | None = None,
    ) -> dict[str, Any]:
        response = self.run_saved_raw(
            project_id,
            seed=seed,
            force_rerun_nodes=force_rerun_nodes,
        )
        response.raise_for_status()
        return response.json()

    def run_saved_raw(
        self,
        project_id: str,
        *,
        seed: int,
        force_rerun_nodes: list[str] | None = None,
        extra_options: dict[str, Any] | None = None,
    ) -> httpx.Response:
        payload: dict[str, Any] = {"seed": seed}
        if force_rerun_nodes is not None:
            payload["force_rerun_nodes"] = force_rerun_nodes
        if extra_options is not None:
            payload.update(extra_options)
        response = self._http.post(
            f"/api/projects/{project_id}/run",
            json=payload,
        )
        return response

    def cancel(self, project_id: str, run_id: str) -> httpx.Response:
        return self._http.post(
            f"/api/projects/{project_id}/run/{run_id}/cancel"
        )

    def receive_run_events(
        self,
        project_id: str,
        run_id: str,
        *,
        on_event: Callable[[dict[str, Any]], None] | None = None,
    ) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        deadline = time.monotonic() + self.event_timeout_seconds
        with connect(
            self._websocket_url(project_id, run_id),
            origin=TRUSTED_ORIGIN,
            open_timeout=10,
            close_timeout=2,
        ) as websocket:
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError(
                        "Run event stream exceeded configured timeout"
                    )
                event = json.loads(
                    websocket.recv(timeout=remaining)
                )
                events.append(event)
                if on_event is not None:
                    on_event(event)
                if event["type"] in TERMINAL_EVENTS:
                    return events

    def manifest(self, project_id: str, run_id: str) -> dict[str, Any]:
        response = self.manifest_raw(project_id, run_id)
        response.raise_for_status()
        return response.json()

    def manifest_raw(self, project_id: str, run_id: str) -> httpx.Response:
        return self._http.get(
            f"/api/projects/{project_id}/run/{run_id}/manifest"
        )

    def websocket_rejection_status(
        self,
        project_id: str,
        run_id: str,
        *,
        origin: str = TRUSTED_ORIGIN,
    ) -> int:
        """Return the HTTP denial status or post-upgrade close code."""
        try:
            with connect(
                self._websocket_url(project_id, run_id),
                origin=origin,
                open_timeout=5,
                close_timeout=2,
            ) as websocket:
                websocket.recv(timeout=2)
        except ConnectionClosed as error:
            return int(error.code)
        except InvalidStatus as error:
            return int(error.response.status_code)
        raise AssertionError("WebSocket connection was not rejected")

    def outputs(self, project_id: str, run_id: str) -> dict[str, Any]:
        response = self._http.get(
            f"/api/projects/{project_id}/run/{run_id}/outputs"
        )
        response.raise_for_status()
        return response.json()

    def artifact(
        self,
        project_id: str,
        run_id: str,
        reference: str,
    ) -> DownloadedArtifact:
        response = self._http.get(
            f"/api/projects/{project_id}/run/{run_id}/artifacts/{reference}"
        )
        response.raise_for_status()
        return DownloadedArtifact(
            payload=response.content,
            sha256=hashlib.sha256(response.content).hexdigest(),
        )
