"""Real mkdssp 4.6.1 acceptance for the active DSSP contract."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

import pytest

from core import ReadinessCheckInput, build_frozen_catalog
from datatypes import (
    Candidate,
    CandidateCollection,
    CandidateDataReference,
)
from modules.structure_annotation.domain import DSSPAnnotation
from modules.structure_annotation.package import MODULE_PACKAGE, _dssp_ready
from modules.prompt_authoring.package import (
    MODULE_PACKAGE as PROMPT_AUTHORING_PACKAGE,
)
from modules.structure_transform import (
    CandidateResolvedResidueAxisAssociation,
    CandidateResolvedResidueAxisAssociations,
)
from modules.structure_transform.implementation import resolve_residue_axis
from modules.structure_transform.package import (
    MODULE_PACKAGE as STRUCTURE_TRANSFORM_PACKAGE,
)
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
    catalog = build_frozen_catalog(
        (
            MODULE_PACKAGE,
            PROMPT_AUTHORING_PACKAGE,
            STRUCTURE_TRANSFORM_PACKAGE,
        )
    )
    subject = CandidateDataReference(
        candidate_id="3gb1",
        data_type_id="protein.structure",
        content_digest=catalog.require_port_type(
            "protein.structure",
            "4.0.0",
        ).content_digest(pdb_3gb1),
    )
    candidates = CandidateCollection(
        collection_id="3gb1-structures",
        item_type="protein.structure",
        items=(Candidate(subject.candidate_id, pdb_3gb1),),
    )
    residue_axis = resolve_residue_axis(pdb_3gb1)
    residue_axes = CandidateResolvedResidueAxisAssociations(
        entries=(
            CandidateResolvedResidueAxisAssociation(
                subject,
                residue_axis,
            ),
        )
    )
    implementation = build_operation(
        catalog,
        "structure_annotation.dssp_compute.mkdssp_local",
        resources,
        binding_version="6.0.0",
        environment={"dssp_binary": _MKDSSP},
    )
    output = implementation.execute(
        operation_call(
            catalog=catalog,
            binding_id="structure_annotation.dssp_compute.mkdssp_local",
            binding_version="6.0.0",
            inputs={
                "structure_candidates": candidates,
                "residue_axes": residue_axes,
            },
            node_parameters={},
            binding_parameters={},
        )
    )

    annotation = output["annotations"]
    assert type(annotation) is DSSPAnnotation
    assert annotation.subject == subject
    assert annotation.layout == residue_axis.layout
    assert annotation.layout.residue_ids == tuple(
        f"A:{residue_number}" for residue_number in range(1, 57)
    )
    assert "".join(annotation.secondary_structure) == (
        "CEEEEEEECSSCEEEEEEECSSHHHHHHHHHHHHHHTTCCSEEEEETTTTEEEEEC"
    )
    assert annotation.sasa == (
        123.5,
        83.4,
        15.7,
        77.5,
        0.0,
        56.5,
        14.2,
        66.5,
        2.0,
        142.4,
        132.3,
        71.9,
        135.2,
        33.5,
        129.9,
        44.3,
        76.9,
        45.2,
        160.3,
        7.9,
        120.4,
        62.6,
        17.1,
        38.8,
        56.5,
        0.0,
        72.8,
        126.3,
        63.9,
        3.9,
        84.5,
        108.7,
        103.0,
        0.3,
        100.4,
        110.2,
        62.0,
        61.4,
        7.9,
        117.4,
        20.0,
        129.5,
        72.7,
        78.9,
        73.2,
        70.4,
        121.2,
        90.7,
        73.2,
        59.9,
        21.5,
        4.5,
        41.7,
        0.3,
        56.2,
        87.8,
    )
    assert resources.invocations == 1
