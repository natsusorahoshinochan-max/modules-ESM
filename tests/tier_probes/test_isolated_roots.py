"""Filesystem probe executed through the public routine verification tier."""

from __future__ import annotations

import os
from pathlib import Path


ROOT_VARIABLES = (
    "PROTEIN_WORKBENCH_PROJECT_ROOT",
    "PROTEIN_WORKBENCH_CACHE_ROOT",
    "PROTEIN_WORKBENCH_OUTPUT_ROOT",
    "PROTEIN_WORKBENCH_RUN_ROOT",
)


def test_backend_roots_are_isolated_for_the_verification_process() -> None:
    roots = [Path(os.environ[variable]).resolve() for variable in ROOT_VARIABLES]

    assert len(set(roots)) == len(ROOT_VARIABLES)
    assert all(root.is_dir() for root in roots)
    assert all("protein-workbench-" in str(root) for root in roots)
    for root in roots:
        (root / "probe").write_text("isolated")
