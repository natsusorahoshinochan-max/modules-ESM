"""Explicit configured Provider paths; never infer downloads or fallback roots."""

from __future__ import annotations

import os
from pathlib import Path


def trusted_soluprot_root() -> Path:
    configured = os.environ.get("PROTEIN_WORKBENCH_SOLUPROT_ROOT")
    assert configured is not None, (
        "PROTEIN_WORKBENCH_SOLUPROT_ROOT must select the trusted SoluProt "
        "runtime root"
    )
    root = Path(configured).expanduser()
    assert root.is_absolute()
    return root


def trusted_protein_sol_root() -> Path:
    configured = os.environ.get("PROTEIN_WORKBENCH_PROTEIN_SOL_ROOT")
    assert configured is not None, (
        "PROTEIN_WORKBENCH_PROTEIN_SOL_ROOT must select the trusted "
        "Protein-Sol source root"
    )
    root = Path(configured).expanduser()
    assert root.is_absolute()
    return root.resolve()


def required_absolute_path(variable: str) -> Path:
    configured = os.environ.get(variable)
    assert configured is not None, f"{variable} must be configured"
    path = Path(configured).expanduser()
    assert path.is_absolute(), f"{variable} must be an absolute path"
    return path.resolve()
