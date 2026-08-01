"""Real mkdssp 4.6.1 acceptance for the active DSSP contract."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

import pytest

from core import ReadinessCheckInput, build_frozen_catalog
from modules.structure_annotation.domain import DSSPAnnotation
from modules.structure_annotation.package import MODULE_PACKAGE, _dssp_ready
from tests.fixtures.scientific_operation import build_operation, operation_call

from .conftest import require_ready


pytestmark = pytest.mark.acceptance
_MKDSSP = "/opt/homebrew/bin/mkdssp"


class _RunResources:
    def __init__(self, root: Path) -> None:
        self._root = root
        self.invocations = 0

    @contextmanager
    def temporary_directory(self, *, prefix: str) -> Iterator[Path]:
        with TemporaryDirectory(prefix=prefix, dir=self._root) as path:
            yield Path(path)

    @contextmanager
    def engine_invocation(
        self,
        **_: Any,
    ) -> Iterator[None]:
        self.invocations += 1
        yield


def test_mkdssp_4_6_1_publishes_complete_3gb1_sasa_and_coil(
    tmp_path: Path,
    readiness: dict[str, bool],
    pdb_3gb1: Any,
) -> None:
    require_ready("mkdssp", readiness)
    conclusion = _dssp_ready(
        ReadinessCheckInput({"dssp_binary": _MKDSSP}, None)
    )
    assert conclusion.passing

    resources = _RunResources(tmp_path)
    catalog = build_frozen_catalog((MODULE_PACKAGE,))
    implementation = build_operation(
        catalog,
        "structure_annotation.dssp_compute.mkdssp_local",
        resources,
        binding_version="3.0.0",
        environment={"dssp_binary": _MKDSSP},
    )
    output = implementation.execute(operation_call(
            catalog=catalog,
            binding_id="structure_annotation.dssp_compute.mkdssp_local",
            binding_version="3.0.0",
            inputs={"structure": pdb_3gb1},
        node_parameters={},
        binding_parameters={},
    ))

    annotation = output["annotations"]
    assert type(annotation) is DSSPAnnotation
    assert annotation.layout.length == 56
    assert len(annotation.secondary_structure) == 56
    assert len(annotation.sasa) == 56
    assert all(type(value) is float and value >= 0 for value in annotation.sasa)
    assert "C" in annotation.secondary_structure
    assert "_" not in annotation.secondary_structure
    assert resources.invocations == 1
