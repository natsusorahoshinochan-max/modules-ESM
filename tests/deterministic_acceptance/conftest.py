"""Launch an equivalent real backend process for deterministic acceptance."""

from __future__ import annotations

import os
import socket
import subprocess
import time
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest

from tests.deterministic_acceptance.backend_client import (
    BackendAcceptanceClient,
)
from tests.deterministic_acceptance.provider_probe import ProviderCallProbe


PROJECT_ROOT = Path(__file__).parents[2]


def _unused_local_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


@pytest.fixture
def provider_call_probe(tmp_path: Path) -> ProviderCallProbe:
    return ProviderCallProbe(tmp_path / "fixture-provider-calls.txt")


@pytest.fixture
def backend_client(
    tmp_path: Path,
    provider_call_probe: ProviderCallProbe,
) -> Iterator[BackendAcceptanceClient]:
    """Yield a network client connected to the fixture-backed backend."""
    port = _unused_local_port()
    base_url = f"http://127.0.0.1:{port}"
    env = os.environ.copy()
    for variable in (
        "PROTEIN_WORKBENCH_CANONICAL_WORKFLOW",
        "PROTEIN_WORKBENCH_CANONICAL_UI",
        "PROTEIN_WORKBENCH_CANONICAL_VERSION",
        "PROTEIN_WORKBENCH_PROTEINMPNN_ROOT",
        "PROTEIN_WORKBENCH_REQUIRE_PROVIDER_CALL",
        "PROTEIN_WORKBENCH_PROVIDER_CALL_EVIDENCE",
    ):
        env.pop(variable, None)
    env["PYTHONPATH"] = str(PROJECT_ROOT)
    env["PROTEIN_WORKBENCH_CANONICAL_WORKFLOW"] = str(
        PROJECT_ROOT / "examples" / "3gb1_pipeline.json"
    )
    env["PROTEIN_WORKBENCH_CANONICAL_UI"] = str(
        PROJECT_ROOT / "examples" / "3gb1_pipeline_ui.json"
    )
    env["PROTEIN_WORKBENCH_CANONICAL_VERSION"] = "18-deterministic"
    env["PROTEIN_WORKBENCH_DETERMINISTIC_PROVIDER_CALLS"] = str(
        provider_call_probe.path
    )
    for name in ("PROJECT", "CACHE", "OUTPUT", "RUN"):
        root = tmp_path / name.lower()
        root.mkdir()
        env[f"PROTEIN_WORKBENCH_{name}_ROOT"] = str(root)
    process = subprocess.Popen(
        [
            str(PROJECT_ROOT / ".venv" / "bin" / "python"),
            "-m",
            "uvicorn",
            "tests.fixtures.deterministic_backend:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--log-level",
            "warning",
        ],
        cwd=PROJECT_ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline and process.poll() is None:
            try:
                response = httpx.get(f"{base_url}/api/modules", timeout=0.5)
                if response.status_code == 200:
                    break
            except httpx.HTTPError:
                time.sleep(0.05)
        else:
            output = process.communicate(timeout=2)[0]
            pytest.fail(f"Deterministic backend did not start:\n{output}")
        client = BackendAcceptanceClient(base_url)
        try:
            yield client
        finally:
            client.close()
    finally:
        if process.poll() is None:
            process.terminate()
        try:
            process.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.communicate()
