"""Real mkdssp 4.6.1 acceptance for the v2.1 annotation contract."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

import pytest

from core import ReadinessCheckInput
from modules.structure_annotation.domain import DSSPAnnotation
from modules.structure_annotation.implementation import (
    StructureAnnotationImplementation,
)
from modules.structure_annotation.package import _dssp_ready

from .conftest import require_ready


pytestmark = pytest.mark.acceptance
_MKDSSP = "/opt/homebrew/bin/mkdssp"


class _RunResources:
    def __init__(self, root: Path) -> None:
        self._root = root
        self.invocations: list[str] = []

    @contextmanager
    def temporary_directory(self, *, prefix: str) -> Iterator[Path]:
        with TemporaryDirectory(prefix=prefix, dir=self._root) as path:
            yield Path(path)

    @contextmanager
    def engine_invocation(
        self,
        *,
        engine_identity: str,
        **_: Any,
    ) -> Iterator[None]:
        self.invocations.append(engine_identity)
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
    implementation = StructureAnnotationImplementation(
        resources,
        "dssp_compute",
        {"dssp_binary": _MKDSSP},
        None,
    )
    output = implementation.execute(
        inputs={"structure": pdb_3gb1},
        node_parameters={},
        binding_parameters={},
    )

    annotation = output["annotations"]
    assert type(annotation) is DSSPAnnotation
    assert annotation.layout.length == 56
    assert len(annotation.secondary_structure) == 56
    assert len(annotation.sasa) == 56
    assert all(type(value) is float and value >= 0 for value in annotation.sasa)
    assert "C" in annotation.secondary_structure
    assert "_" not in annotation.secondary_structure
    assert resources.invocations == ["structure_annotation.mkdssp/4.6.1"]
