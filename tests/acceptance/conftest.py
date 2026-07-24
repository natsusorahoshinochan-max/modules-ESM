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
    mpnn_dir = PROJECT_ROOT / "repositories" / "ProteinMPNN"
    if not mpnn_dir.exists():
        return False
    v_weights = mpnn_dir / "vanilla_model_weights" / "v_48_020.pt"
    s_weights = mpnn_dir / "soluble_model_weights" / "v_48_020.pt"
    return v_weights.exists() or s_weights.exists()


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
    """Skip the current test if the provider is not ready."""
    if not readiness.get(provider, False):
        pytest.skip(f"Provider '{provider}' not available")


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
    root = PROJECT_ROOT / "var" / "runs" / "acceptance" / f"{date_str}_{run_id}"
    root.mkdir(parents=True, exist_ok=True)
    return str(root)
