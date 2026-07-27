"""Shared fixtures for acceptance tests.

Provides:
- readiness_probe: checks provider availability, skips if unavailable
- pdb_3gb1 / pdb_1pga: ProteinStructure fixtures from pdbs/
- run_root: auto-creates var/runs/acceptance/{date}_{run_id}/
"""

import hashlib
import json
import os
import subprocess
import uuid
from datetime import datetime, timezone
from importlib.metadata import version
from pathlib import Path

import pytest

from datatypes import ProteinStructure
from core.provider_contract import (
    ESM_SDK_REVISION,
    SIMPLEFOLD_ARTIFACT_SHA256,
    esm_provider_identity,
    proteinmpnn_provider_identity,
    simplefold_provider_identity,
    validate_installed_provider_checkout,
    validate_local_esm3_snapshot,
)
from core.provider_evidence import record_provider_readiness

# Project root is three levels up from this file
PROJECT_ROOT = Path(__file__).parent.parent.parent
PDB_3GB1_SHA256 = (
    "1d061dc4998f18fe9a7cd8ada15b4b4bcf9d117ca9bb9ee139a79713857cccdf"
)
SEQUENCE_3GB1_SHA256 = (
    "7e859d82171047700fd3e9632f7a47eab4a39baedc8c3316d2fc62d3ce2260bb"
)


@pytest.hookimpl(hookwrapper=True, tryfirst=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    setattr(item, f"rep_{call.when}", outcome.get_result())


def _read_pdb(path: str) -> str:
    """Read a PDB file from the project root."""
    full = PROJECT_ROOT / path
    if not full.exists():
        pytest.skip(f"PDB file not found: {full}")
    return full.read_text()


def _check_biohub_ready() -> bool:
    """Check if Biohub token is available."""
    configured = os.environ.get("PROTEIN_WORKBENCH_BIOHUB_TOKEN_FILE")
    token_path = Path(configured) if configured else PROJECT_ROOT / "keys" / "esmkey.txt"
    try:
        validate_installed_provider_checkout("esm", ESM_SDK_REVISION)
    except (ImportError, RuntimeError):
        return False
    return (
        not token_path.is_symlink()
        and token_path.is_file()
        and token_path.stat().st_size <= 16 * 1024
        and len(token_path.read_text().strip()) > 0
    )


def _check_local_esm3_ready() -> bool:
    try:
        validate_installed_provider_checkout("esm", ESM_SDK_REVISION)
        validate_local_esm3_snapshot()
    except (FileNotFoundError, ImportError, RuntimeError):
        return False
    return True


def _check_mkdssp_ready() -> bool:
    """Check if mkdssp binary is available."""
    binary = "/opt/homebrew/bin/mkdssp"
    try:
        completed = subprocess.run(
            [binary, "--version"],
            text=True,
            capture_output=True,
            check=True,
            timeout=10,
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return False
    return "mkdssp version 4.6.1" in (
        completed.stdout + completed.stderr
    )


def _check_proteinmpnn_ready() -> bool:
    """Check if ProteinMPNN checkpoints exist."""
    from modules.proteinmpnn import check_proteinmpnn_readiness

    return check_proteinmpnn_readiness().ready


def _check_simplefold_ready() -> bool:
    """Check if SimpleFold and required gate artifacts are installed."""
    from modules.simplefold_adapter import validated_simplefold_model_dir

    project_root = Path(os.environ["PROTEIN_WORKBENCH_PROJECT_ROOT"])
    try:
        validated_simplefold_model_dir(
            project_root / "simplefold_artifacts"
        )
    except (FileNotFoundError, RuntimeError):
        return False
    return True


def _check_alignment_ready() -> bool:
    try:
        import Bio
        import numpy
        import tmtools
    except ImportError:
        return False
    return all((Bio.__version__, numpy.__version__, tmtools.__name__))


@pytest.fixture(scope="session")
def readiness() -> dict:
    """Check all provider readiness. Returns status dict.

    Individual test files call _require_ready() with their provider name.
    """
    status = {
        "biohub": _check_biohub_ready(),
        "local_esm3": _check_local_esm3_ready(),
        "mkdssp": _check_mkdssp_ready(),
        "proteinmpnn": _check_proteinmpnn_ready(),
        "simplefold": _check_simplefold_ready(),
        "alignment": _check_alignment_ready(),
    }
    readiness_evidence = (
        (
            "biohub",
            status["biohub"],
            {
                **esm_provider_identity(),
            },
            {"credential_present": status["biohub"]},
        ),
        (
            "local_open",
            status["local_esm3"],
            esm_provider_identity(local=True),
            {"snapshot_validated": status["local_esm3"]},
        ),
        (
            "mkdssp",
            status["mkdssp"],
            {"binary": "mkdssp", "required_version": "4.6.1"},
            {"version_match": status["mkdssp"]},
        ),
        (
            "local-proteinmpnn",
            status["proteinmpnn"],
            proteinmpnn_provider_identity(),
            {
                "checkout_and_checkpoint_validated": status["proteinmpnn"],
            },
        ),
        (
            "simplefold",
            status["simplefold"],
            simplefold_provider_identity(SIMPLEFOLD_ARTIFACT_SHA256),
            {
                "artifact_contract_complete": status["simplefold"],
            },
        ),
        (
            "biopython-svd",
            status["alignment"],
            {
                "biopython_version": version("biopython"),
                "numpy_version": version("numpy"),
            },
            {"installed": status["alignment"]},
        ),
        (
            "tmtools",
            status["alignment"],
            {"tmtools_version": version("tmtools")},
            {"installed": status["alignment"]},
        ),
    )
    required_for_tier = {
        "live-provider": {"biohub"},
        "local-provider": {"mkdssp", "biopython-svd", "tmtools"},
        "heavy-model": {"local_open", "local-proteinmpnn", "simplefold"},
    }.get(os.environ.get("PROTEIN_WORKBENCH_VERIFICATION_TIER"), set())
    for provider, ready, identity, details in readiness_evidence:
        if provider not in required_for_tier:
            continue
        record_provider_readiness(
            provider=provider,
            ready=ready,
            identity=identity,
            details=details,
        )
    return status


def require_ready(provider: str, readiness: dict) -> None:
    """Require provider readiness, failing explicit provider gates."""
    if not readiness.get(provider, False):
        if os.environ.get("PROTEIN_WORKBENCH_REQUIRE_PROVIDER_CALL") == "1":
            pytest.fail(f"Required provider '{provider}' is not available")
        pytest.skip(f"Provider '{provider}' not available")


@pytest.fixture(autouse=True)
def require_adapter_provider_evidence(request: pytest.FixtureRequest):
    """Require evidence emitted by the adapter, not by the acceptance test."""
    evidence_path = Path(
        os.environ.get(
            "PROTEIN_WORKBENCH_PROVIDER_CALL_EVIDENCE",
            str(
                Path(os.environ["PROTEIN_WORKBENCH_RUN_ROOT"])
                / "provider-calls.jsonl"
            ),
        )
    )
    starting_size = evidence_path.stat().st_size if evidence_path.exists() else 0

    yield

    is_provider_test = (
        request.node.get_closest_marker("live_provider") is not None
        or request.node.get_closest_marker("local_provider") is not None
    )
    if (
        is_provider_test
        and os.environ.get("PROTEIN_WORKBENCH_REQUIRE_PROVIDER_CALL") == "1"
        and getattr(request.node, "rep_call", None) is not None
        and request.node.rep_call.passed
    ):
        if not evidence_path.exists():
            pytest.fail("Provider test completed without provider-call evidence")
        with evidence_path.open() as evidence:
            evidence.seek(starting_size)
            new_events = [
                json.loads(line) for line in evidence
                if line.strip()
            ]
        if not any(
            event.get("event_type") == "provider_call"
            and event.get("actual_call") is True
            and event.get("result", {}).get("status") == "succeeded"
            and event.get("test_id") == request.node.nodeid
            for event in new_events
        ):
            pytest.fail(
                "Provider test completed without adapter-boundary call evidence"
            )


@pytest.fixture(scope="session")
def pdb_3gb1() -> ProteinStructure:
    """Load 3GB1 PDB as a ProteinStructure."""
    pdb_str = _read_pdb("pdbs/3GB1.pdb")
    if hashlib.sha256(pdb_str.encode()).hexdigest() != PDB_3GB1_SHA256:
        pytest.fail("3GB1 acceptance fixture does not match its locked SHA-256")
    return ProteinStructure(pdb_string=pdb_str, source="3GB1")


@pytest.fixture(scope="session")
def pdb_1pga() -> ProteinStructure:
    """Load 1PGA variant PDB as a ProteinStructure."""
    pdb_str = _read_pdb("pdbs/1PGA-75-gen1_0690.pdb")
    return ProteinStructure(pdb_string=pdb_str, source="1PGA-variant")


@pytest.fixture(scope="session")
def run_root() -> str:
    """Create a dated run root directory for evidence output.

    Returns the path as a string. The directory is created under
    var/runs/acceptance/{date}_{run_id}/.
    """
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    run_id = str(uuid.uuid4())[:8]
    configured_root = Path(
        os.environ.get(
            "PROTEIN_WORKBENCH_RUN_ROOT",
            str(PROJECT_ROOT / "var" / "runs"),
        )
    )
    root = configured_root / "acceptance" / f"{date_str}_{run_id}"
    root.mkdir(parents=True, exist_ok=True)
    return str(root)
