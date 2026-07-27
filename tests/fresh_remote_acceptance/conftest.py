"""Launch the production backend with only reviewed real-provider resources."""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from collections.abc import Iterator
from importlib.metadata import version
from pathlib import Path

import httpx
import pytest

from core.provider_contract import (
    ESM_SDK_REVISION,
    esm_provider_identity,
    proteinmpnn_provider_identity,
    validate_biohub_token_file,
    validate_installed_provider_checkout,
    validate_local_esm3_snapshot,
)
from core.provider_evidence import record_provider_readiness
from tests.deterministic_acceptance.backend_client import (
    BackendAcceptanceClient,
)


PROJECT_ROOT = Path(__file__).parents[2]
ROOT_VARIABLES = (
    "PROTEIN_WORKBENCH_PROJECT_ROOT",
    "PROTEIN_WORKBENCH_CACHE_ROOT",
    "PROTEIN_WORKBENCH_OUTPUT_ROOT",
    "PROTEIN_WORKBENCH_RUN_ROOT",
)


def _unused_local_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _biohub_ready() -> bool:
    configured = os.environ.get("PROTEIN_WORKBENCH_BIOHUB_TOKEN_FILE")
    if not configured:
        return False
    try:
        validate_installed_provider_checkout("esm", ESM_SDK_REVISION)
        validate_biohub_token_file(configured)
    except (ImportError, OSError, RuntimeError):
        return False
    return True


def _local_esm3_ready() -> bool:
    try:
        validate_installed_provider_checkout("esm", ESM_SDK_REVISION)
        validate_local_esm3_snapshot()
    except (FileNotFoundError, ImportError, RuntimeError):
        return False
    return True


def _mkdssp_ready() -> bool:
    try:
        completed = subprocess.run(
            ["/opt/homebrew/bin/mkdssp", "--version"],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return False
    return "mkdssp version 4.6.1" in (
        completed.stdout + completed.stderr
    )


def _proteinmpnn_ready() -> bool:
    from modules.proteinmpnn import check_proteinmpnn_readiness

    return check_proteinmpnn_readiness().ready


def _alignment_ready() -> bool:
    try:
        import Bio
        import numpy
        import tmtools
    except ImportError:
        return False
    return bool(Bio.__version__ and numpy.__version__ and tmtools.__name__)


def _backend_environment() -> dict[str, str]:
    """Rebuild the reviewed child allowlist after pytest plugin setup."""
    allowed = {
        "PATH",
        "LANG",
        "LC_ALL",
        "SSL_CERT_FILE",
        "SSL_CERT_DIR",
        "NO_PROXY",
        "OBJC_DISABLE_INITIALIZE_FORK_SAFETY",
        "HOME",
        "TMPDIR",
        "PYTHONHASHSEED",
        "PYTHONPYCACHEPREFIX",
        "PROTEIN_WORKBENCH_APPROVED_SOURCE_REVISION",
        "PROTEIN_WORKBENCH_BIOHUB_TOKEN_FILE",
        "PROTEIN_WORKBENCH_PROTEINMPNN_ROOT",
        "PROTEIN_WORKBENCH_PROVIDER_CALL_EVIDENCE",
        "PROTEIN_WORKBENCH_PROCESS_CONTAINMENT",
        "PROTEIN_WORKBENCH_REAL_GATE_FRESH",
        "PROTEIN_WORKBENCH_REAL_GATE_NONCE",
        "PROTEIN_WORKBENCH_REQUIRE_PROVIDER_CALL",
        "PROTEIN_WORKBENCH_TEST_ROOTS_INITIALIZED",
        "PROTEIN_WORKBENCH_VERIFICATION_TIER",
        "PROTEIN_WORKBENCH_ACCEPTANCE_EVIDENCE_ROOT",
        "HF_HOME",
        "HF_HUB_CACHE",
        "HF_HUB_OFFLINE",
        "TRANSFORMERS_OFFLINE",
        "TORCH_HOME",
        "PYTEST_CURRENT_TEST",
        *ROOT_VARIABLES,
    }
    env = {key: os.environ[key] for key in allowed if key in os.environ}
    env["PYTHONPATH"] = str(PROJECT_ROOT)
    return env


@pytest.fixture(scope="session")
def fresh_provider_readiness() -> dict[str, bool]:
    """Fail closed and retain readiness without reading credential contents."""
    readiness = {
        "biohub": _biohub_ready(),
        "local_open": _local_esm3_ready(),
        "local-proteinmpnn": _proteinmpnn_ready(),
        "mkdssp": _mkdssp_ready(),
        "biopython-svd": _alignment_ready(),
        "tmtools": _alignment_ready(),
    }
    identities = {
        "biohub": esm_provider_identity(),
        "local_open": esm_provider_identity(local=True),
        "local-proteinmpnn": proteinmpnn_provider_identity(),
        "mkdssp": {"binary": "mkdssp", "required_version": "4.6.1"},
        "biopython-svd": {
            "biopython_version": version("biopython"),
            "numpy_version": version("numpy"),
        },
        "tmtools": {"tmtools_version": version("tmtools")},
    }
    details = {
        "biohub": {"credential_present": readiness["biohub"]},
        "local_open": {"snapshot_validated": readiness["local_open"]},
        "local-proteinmpnn": {
            "checkout_and_checkpoint_validated": (
                readiness["local-proteinmpnn"]
            )
        },
        "mkdssp": {"version_match": readiness["mkdssp"]},
        "biopython-svd": {"installed": readiness["biopython-svd"]},
        "tmtools": {"installed": readiness["tmtools"]},
    }
    for provider in sorted(readiness):
        record_provider_readiness(
            provider=provider,
            ready=readiness[provider],
            identity=identities[provider],
            details=details[provider],
        )
    missing = sorted(
        provider for provider, ready in readiness.items() if not ready
    )
    if missing:
        pytest.fail(
            "Required fresh-run providers are unavailable: "
            + ", ".join(missing)
        )
    return readiness


@pytest.fixture
def real_backend_client(
    fresh_provider_readiness: dict[str, bool],
) -> Iterator[BackendAcceptanceClient]:
    """Yield a client connected to the unmodified production ASGI app."""
    assert all(fresh_provider_readiness.values())
    roots = {
        variable: Path(os.environ[variable])
        for variable in ROOT_VARIABLES
    }
    if any(
        root.is_symlink()
        or not root.is_dir()
        or any(root.iterdir())
        for root in roots.values()
    ):
        pytest.fail("Fresh acceptance roots must be distinct and initially empty")

    port = _unused_local_port()
    base_url = f"http://127.0.0.1:{port}"
    env = _backend_environment()
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "core.server:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--log-level",
            "warning",
        ],
        cwd=PROJECT_ROOT,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline and process.poll() is None:
            try:
                response = httpx.get(f"{base_url}/api/modules", timeout=0.5)
                if response.status_code == 200:
                    break
            except httpx.HTTPError:
                time.sleep(0.1)
        else:
            pytest.fail("Production backend did not start")
        client = BackendAcceptanceClient(
            base_url,
            event_timeout_seconds=3 * 60 * 60,
        )
        try:
            yield client
        finally:
            client.close()
    finally:
        if process.poll() is None:
            process.terminate()
        try:
            process.wait(timeout=30)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
