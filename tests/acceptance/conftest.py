"""Shared fixtures for acceptance tests.

Provides:
- readiness_probe: checks provider availability, skips if unavailable
- pdb_3gb1 / pdb_1pga: ProteinStructure fixtures from pdbs/
- run_root: auto-creates var/runs/acceptance/{date}_{run_id}/
"""

import hashlib
import os
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest

from datatypes import ProteinStructure
from modules.provider_contract import (
    ESM_SDK_REVISION,
    SIMPLEFOLD_REVISION,
    validate_installed_provider_checkout,
    validate_local_esm3_snapshot,
)
from modules.folding.simplefold_adapter import (
    SIMPLEFOLD_DEVICE,
    configured_runtime_fingerprint,
    validate_simplefold_folding_environment,
)
from modules.folding.simplefold_confidence_adapter import (
    SIMPLEFOLD_CONFIDENCE_DEVICE,
    configured_runtime_fingerprint as confidence_runtime_fingerprint,
    validate_simplefold_confidence_environment,
)

# Project root is three levels up from this file
PROJECT_ROOT = Path(__file__).parent.parent.parent
PDB_3GB1_SHA256 = (
    "ee623d3d9fd77a131895dc367c31ac8d7266b1d4f241b56325170e5f62ed7811"
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
    from modules.proteinmpnn.adapter import (
        PROTEINMPNN_DEVICE,
        configured_runtime_fingerprint,
        proteinmpnn_readiness,
    )

    root = os.environ.get("PROTEIN_WORKBENCH_PROTEINMPNN_ROOT")
    if root is None:
        return False
    return proteinmpnn_readiness(
        {
            "device": PROTEINMPNN_DEVICE,
            "provider_root": Path(root),
            "resolved_runtime_fingerprint": configured_runtime_fingerprint(),
        }
    ).passing


def _check_simplefold_ready() -> bool:
    """Check if SimpleFold and required gate artifacts are installed."""
    if (
        os.environ.get("PROTEIN_WORKBENCH_PROVIDER_IDENTITY_PROFILE")
        == "simplefold-v2-confidence"
    ):
        try:
            validate_installed_provider_checkout(
                "simplefold",
                SIMPLEFOLD_REVISION,
            )
            validate_simplefold_confidence_environment({
                "model_root": Path(
                    os.environ["PROTEIN_WORKBENCH_SIMPLEFOLD_MODEL_ROOT"]
                ),
                "esm2_source_root": Path(
                    os.environ["PROTEIN_WORKBENCH_SIMPLEFOLD_ESM2_ROOT"]
                ),
                "esm2_model_root": Path(
                    os.environ[
                        "PROTEIN_WORKBENCH_SIMPLEFOLD_ESM2_MODEL_ROOT"
                    ]
                ),
                "device": SIMPLEFOLD_CONFIDENCE_DEVICE,
                "resolved_runtime_fingerprint": (
                    confidence_runtime_fingerprint()
                ),
            })
        except (
            FileNotFoundError,
            ImportError,
            KeyError,
            OSError,
            RuntimeError,
            ValueError,
        ):
            return False
        return True
    if (
        os.environ.get("PROTEIN_WORKBENCH_PROVIDER_IDENTITY_PROFILE")
        == "simplefold-v2-folding"
    ):
        try:
            validate_installed_provider_checkout(
                "simplefold",
                SIMPLEFOLD_REVISION,
            )
            validate_simplefold_folding_environment({
                "model_root": Path(
                    os.environ["PROTEIN_WORKBENCH_SIMPLEFOLD_MODEL_ROOT"]
                ),
                "esm2_source_root": Path(
                    os.environ["PROTEIN_WORKBENCH_SIMPLEFOLD_ESM2_ROOT"]
                ),
                "esm2_model_root": Path(
                    os.environ[
                        "PROTEIN_WORKBENCH_SIMPLEFOLD_ESM2_MODEL_ROOT"
                    ]
                ),
                "device": SIMPLEFOLD_DEVICE,
                "resolved_runtime_fingerprint": (
                    configured_runtime_fingerprint()
                ),
            })
        except (
            FileNotFoundError,
            ImportError,
            KeyError,
            OSError,
            RuntimeError,
            ValueError,
        ):
            return False
        return True
    return False


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
    return status


def require_ready(provider: str, readiness: dict) -> None:
    """Require provider readiness, failing explicit provider gates."""
    if not readiness.get(provider, False):
        if os.environ.get("PROTEIN_WORKBENCH_REQUIRE_PROVIDER_CALL") == "1":
            pytest.fail(f"Required provider '{provider}' is not available")
        pytest.skip(f"Provider '{provider}' not available")


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
