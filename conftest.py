"""Safe defaults shared by every pytest invocation in this repository."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest


ROOT_VARIABLES = (
    "PROTEIN_WORKBENCH_PROJECT_ROOT",
    "PROTEIN_WORKBENCH_CACHE_ROOT",
    "PROTEIN_WORKBENCH_OUTPUT_ROOT",
    "PROTEIN_WORKBENCH_RUN_ROOT",
)
_owned_test_root: tempfile.TemporaryDirectory[str] | None = None


def _initialize_isolated_roots() -> None:
    global _owned_test_root
    if os.environ.get("PROTEIN_WORKBENCH_TEST_ROOTS_INITIALIZED") != "1":
        tier = os.environ.get("PROTEIN_WORKBENCH_VERIFICATION_TIER", "routine")
        _owned_test_root = tempfile.TemporaryDirectory(
            prefix=f"protein-workbench-{tier}-"
        )
        base = Path(_owned_test_root.name)
        for variable in ROOT_VARIABLES:
            name = variable.removeprefix("PROTEIN_WORKBENCH_").removesuffix("_ROOT")
            os.environ[variable] = str(base / name.lower())
        os.environ["PROTEIN_WORKBENCH_TEST_ROOTS_INITIALIZED"] = "1"

    for variable in ROOT_VARIABLES:
        Path(os.environ[variable]).mkdir(parents=True, exist_ok=True)


def pytest_configure(config: pytest.Config) -> None:
    _initialize_isolated_roots()


def pytest_report_header(config: pytest.Config) -> str:
    tier = os.environ.get("PROTEIN_WORKBENCH_VERIFICATION_TIER", "routine")
    return f"backend verification tier: {tier}"


@pytest.fixture
def isolated_project_dir() -> str:
    """Return a per-test directory beneath the isolated project root."""
    project_root = Path(os.environ["PROTEIN_WORKBENCH_PROJECT_ROOT"])
    return tempfile.mkdtemp(prefix="test-project-", dir=project_root)


def pytest_unconfigure(config: pytest.Config) -> None:
    global _owned_test_root
    if _owned_test_root is not None:
        _owned_test_root.cleanup()
        _owned_test_root = None
