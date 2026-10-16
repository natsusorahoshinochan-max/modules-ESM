"""Filesystem probe executed through the public routine verification tier."""

from __future__ import annotations

import os
from pathlib import Path
import warnings


def test_backend_roots_are_isolated_for_the_verification_process() -> None:
    assert "PYTEST_ADDOPTS" not in os.environ
    assert "PROTEIN_WORKBENCH_PROVIDER_CALL_EVIDENCE" not in os.environ
    assert "PROTEIN_WORKBENCH_PROVIDER_EVIDENCE_SCOPE" not in os.environ
    data_root = Path(os.environ["PROTEIN_WORKBENCH_DATA_ROOT"])

    assert data_root.is_absolute()
    assert data_root.is_dir()
    assert "protein-workbench-" in str(data_root)
    (data_root / "probe").write_text("isolated")
    if os.environ.get("PROTEIN_WORKBENCH_RESOURCE_WARNING_PROBE") == "1":
        warnings.warn(
            "ResourceTracker called reentrantly for resource cleanup, "
            "which is unsupported. "
            "The semaphore object '/mp-verification-probe' might leak.",
            UserWarning,
        )
