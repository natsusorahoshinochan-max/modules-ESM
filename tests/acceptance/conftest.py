"""Shared fixtures for acceptance tests.

Provides:
- readiness_probe: checks provider availability, skips if unavailable
- pdb_3gb1 / pdb_1pga: ProteinStructure fixtures from pdbs/
- run_root: auto-creates var/runs/acceptance/{date}_{run_id}/
"""

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest

from datatypes import ProteinStructure

# Project root is three levels up from this file
PROJECT_ROOT = Path(__file__).parent.parent.parent


def _read_pdb(path: str) -> str:
    """Read a PDB file from the project root."""
    full = PROJECT_ROOT / path
    if not full.exists():
        pytest.skip(f"PDB file not found: {full}")
    return full.read_text()


def _check_biohub_ready() -> bool:
    """Check if Biohub token is available."""
    token_path = PROJECT_ROOT / "keys" / "esmkey.txt"
    return token_path.exists() and len(token_path.read_text().strip()) > 0


def _check_mkdssp_ready() -> bool:
    """Check if mkdssp binary is available."""
    import shutil
    binary = "/opt/homebrew/bin/mkdssp"
    return shutil.which(binary) is not None


def _check_proteinmpnn_ready() -> bool:
    """Check if ProteinMPNN checkpoints exist."""
    from modules.proteinmpnn import check_proteinmpnn_readiness

    return check_proteinmpnn_readiness().ready


def _check_simplefold_ready() -> bool:
    """Check if SimpleFold is installed."""
    try:
        import simplefold
        return True
    except ImportError:
        return False


@pytest.fixture(scope="session")
def readiness() -> dict:
    """Check all provider readiness. Returns status dict.

    Individual test files call _require_ready() with their provider name.
    """
    status = {
        "biohub": _check_biohub_ready(),
        "mkdssp": _check_mkdssp_ready(),
        "proteinmpnn": _check_proteinmpnn_ready(),
        "simplefold": _check_simplefold_ready(),
    }
    return status


def require_ready(provider: str, readiness: dict) -> None:
    """Require provider readiness, failing explicit provider gates."""
    if not readiness.get(provider, False):
        if os.environ.get("PROTEIN_WORKBENCH_REQUIRE_PROVIDER_CALL") == "1":
            pytest.fail(f"Required provider '{provider}' is not available")
        pytest.skip(f"Provider '{provider}' not available")


@pytest.fixture(autouse=True)
def record_provider_call(request: pytest.FixtureRequest):
    """Record and require post-call evidence for each selected provider test."""
    recorded = False

    def record(provider: str, operation: str) -> None:
        nonlocal recorded
        evidence_path = Path(
            os.environ.get(
                "PROTEIN_WORKBENCH_PROVIDER_CALL_EVIDENCE",
                str(
                    Path(os.environ["PROTEIN_WORKBENCH_RUN_ROOT"])
                    / "provider-calls.jsonl"
                ),
            )
        )
        evidence_path.parent.mkdir(parents=True, exist_ok=True)
        with evidence_path.open("a") as evidence:
            evidence.write(json.dumps({
                "provider": provider,
                "operation": operation,
                "test_id": request.node.nodeid,
            }, sort_keys=True) + "\n")
        recorded = True

    yield record

    is_provider_test = (
        request.node.get_closest_marker("live_provider") is not None
        or request.node.get_closest_marker("local_provider") is not None
    )
    if (
        is_provider_test
        and os.environ.get("PROTEIN_WORKBENCH_REQUIRE_PROVIDER_CALL") == "1"
        and not recorded
    ):
        pytest.fail("Provider test completed without provider-call evidence")


@pytest.fixture(scope="session")
def pdb_3gb1() -> ProteinStructure:
    """Load 3GB1 PDB as a ProteinStructure."""
    pdb_str = _read_pdb("pdbs/3GB1.pdb")
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
