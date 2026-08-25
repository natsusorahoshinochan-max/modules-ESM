"""Safe defaults shared by every pytest invocation in this repository."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest


DATA_ROOT_VARIABLE = "PROTEIN_WORKBENCH_DATA_ROOT"
_owned_test_root: tempfile.TemporaryDirectory[str] | None = None


def _initialize_isolated_roots() -> None:
    global _owned_test_root
    if os.environ.get("PROTEIN_WORKBENCH_TEST_ROOTS_INITIALIZED") != "1":
        tier = os.environ.get("PROTEIN_WORKBENCH_VERIFICATION_TIER", "routine")
        _owned_test_root = tempfile.TemporaryDirectory(
            prefix=f"protein-workbench-{tier}-"
        )
        os.environ[DATA_ROOT_VARIABLE] = _owned_test_root.name
        os.environ["PROTEIN_WORKBENCH_TEST_ROOTS_INITIALIZED"] = "1"

    Path(os.environ[DATA_ROOT_VARIABLE]).mkdir(parents=True, exist_ok=True)


def pytest_configure(config: pytest.Config) -> None:
    _initialize_isolated_roots()


def pytest_report_header(config: pytest.Config) -> str:
    tier = os.environ.get("PROTEIN_WORKBENCH_VERIFICATION_TIER", "routine")
    return f"backend verification tier: {tier}"


@pytest.fixture
def isolated_project_dir() -> str:
    """Return a per-test directory beneath the isolated project root."""
    project_root = Path(os.environ[DATA_ROOT_VARIABLE]) / "projects"
    project_root.mkdir(parents=True, exist_ok=True)
    return tempfile.mkdtemp(prefix="test-project-", dir=project_root)


def pytest_unconfigure(config: pytest.Config) -> None:
    global _owned_test_root
    if _owned_test_root is not None:
        _owned_test_root.cleanup()
        _owned_test_root = None
