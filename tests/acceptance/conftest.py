"""Shared fixtures for acceptance tests.

Provides:
- pdb_3gb1 / pdb_1pga: ProteinStructure fixtures from pdbs/
- run_root: auto-creates var/runs/acceptance/{date}_{run_id}/
"""

import hashlib
import os
import uuid
from collections.abc import Iterator
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from datatypes import ProteinStructure
from tests.acceptance.retained_evidence import (
    retain_proteinmpnn_lifecycle,
)

# Project root is three levels up from this file
PROJECT_ROOT = Path(__file__).parent.parent.parent
PDB_3GB1_SHA256 = (
    "ee623d3d9fd77a131895dc367c31ac8d7266b1d4f241b56325170e5f62ed7811"
)
SEQUENCE_3GB1_SHA256 = (
    "7e859d82171047700fd3e9632f7a47eab4a39baedc8c3316d2fc62d3ce2260bb"
)


@pytest.fixture(scope="session", autouse=True)
def retain_installed_proteinmpnn_load_count() -> Iterator[None]:
    """Record the one fact not present in public invocation events."""
    if os.environ.get("PROTEIN_WORKBENCH_VERIFICATION_TIER") != (
        "installed-proteinmpnn"
    ):
        yield
        return
    import modules.proteinmpnn.provider_runtime as runtime

    original_load = runtime._load_model
    load_count = 0

    def counted_load(*args: Any, **kwargs: Any) -> Any:
        nonlocal load_count
        load_count += 1
        return original_load(*args, **kwargs)

    runtime._load_model = counted_load
    try:
        yield
    finally:
        runtime._load_model = original_load
        retain_proteinmpnn_lifecycle(load_count=load_count)


@pytest.hookimpl(hookwrapper=True, tryfirst=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    setattr(item, f"rep_{call.when}", outcome.get_result())


def _read_pdb(path: str) -> str:
    """Read a PDB file from the project root."""
    return (PROJECT_ROOT / path).read_text()


@pytest.fixture(scope="session")
def pdb_3gb1() -> ProteinStructure:
    """Load 3GB1 PDB as a ProteinStructure."""
    pdb_str = _read_pdb("pdbs/3GB1.pdb")
    if hashlib.sha256(pdb_str.encode()).hexdigest() != PDB_3GB1_SHA256:
        pytest.fail("3GB1 acceptance fixture does not match its locked SHA-256")
    return ProteinStructure(pdb_string=pdb_str)


@pytest.fixture(scope="session")
def pdb_1pga() -> ProteinStructure:
    """Load 1PGA variant PDB as a ProteinStructure."""
    pdb_str = _read_pdb("pdbs/1PGA-75-gen1_0690.pdb")
    return ProteinStructure(pdb_string=pdb_str)


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
