"""Real ProteinMPNN acceptance for designed-first chain decoding."""

from __future__ import annotations

import math
import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from core.operation import (
    EngineInvocationProvenance,
)
from datatypes.residue import ResidueLayout
from datatypes.sequence import ProteinSequence
from datatypes.structure import ProteinStructure
from modules.proteinmpnn.domain import ProteinMPNNConstraints
from modules.proteinmpnn.adapter import (
    LocalProteinMPNNAdapter,
)
from modules.structure_transform.csh_normalization import normalize_csh_parent_span
from modules.structure_transform.residue_axis import resolve_residue_axis

pytestmark = [
    pytest.mark.acceptance,
    pytest.mark.local_provider,
    pytest.mark.slow,
]


class _RunResources:
    def __init__(self, root: Path) -> None:
        self._root = root
        self.invocations: list[dict[str, object]] = []

    @staticmethod
    @contextmanager
    def local_provider(
        provider_id: str,
    ) -> Iterator[dict[object, object]]:
        assert provider_id == "proteinmpnn"
        yield {}

    @contextmanager
    def temporary_directory(self, *, prefix: str) -> Iterator[Path]:
        with TemporaryDirectory(prefix=prefix, dir=self._root) as path:
            yield Path(path)

    @contextmanager
    def engine_invocation(self, **details: object) -> Iterator[None]:
        self.invocations.append(details)
        yield

    @property
    def public_invocations(self) -> list[dict[str, object]]:
        result: list[dict[str, object]] = []
        for invocation in self.invocations:
            details = dict(invocation)
            provenance = details.get("invocation_provenance")
            if type(provenance) is EngineInvocationProvenance:
                details["invocation_provenance"] = provenance.to_public()
            result.append(details)
        return result


def _split_3gb1_into_two_chains(structure: ProteinStructure) -> ProteinStructure:
    lines: list[str] = []
    entered_chain_b = False
    for line in structure.pdb_string.splitlines():
        if not line.startswith("ATOM  "):
            if not line.startswith("TER"):
                lines.append(line)
            continue
        residue_number = int(line[22:26])
        if residue_number <= 28:
            chain = "B"
            chain_residue_number = residue_number
        else:
            chain = "A"
            chain_residue_number = residue_number - 28
            if not entered_chain_b:
                lines.append("TER")
                entered_chain_b = True
        lines.append(
            line[:21]
            + chain
            + f"{chain_residue_number:4d}"
            + line[26:]
        )
    lines.extend(("TER", "END"))
    return ProteinStructure(
        "\n".join(lines) + "\n",
    )


def _stage_identity_edge_cases(
    structure: ProteinStructure,
) -> ProteinStructure:
    lines: list[str] = []
    for line in structure.pdb_string.splitlines():
        if not line.startswith("ATOM  "):
            lines.append(line)
            continue
        residue_number = int(line[22:26])
        if residue_number == 1:
            staged_number = -2
            insertion_code = " "
        elif residue_number == 2:
            staged_number = 1
            insertion_code = "A"
        else:
            staged_number = residue_number
            insertion_code = line[26]
        lines.append(
            line[:22]
            + f"{staged_number:4d}"
            + insertion_code
            + line[27:]
        )
    return ProteinStructure("\n".join(lines) + "\n")


def _split_3gb1_into_same_chain_segments(
    structure: ProteinStructure,
) -> ProteinStructure:
    lines: list[str] = []
    inserted_boundary = False
    for line in structure.pdb_string.splitlines():
        if line.startswith("TER"):
            continue
        if (
            line.startswith("ATOM  ")
            and int(line[22:26]) == 29
            and not inserted_boundary
        ):
            lines.append("TER")
            inserted_boundary = True
        lines.append(line)
    lines.extend(("TER", "END"))
    return ProteinStructure("\n".join(lines) + "\n")


def test_real_proteinmpnn_reversed_axis_design_restores_b_then_a_layout(
    tmp_path: Path,
    pdb_3gb1: ProteinStructure,
) -> None:
    provider_root = Path(
        os.environ["PROTEIN_WORKBENCH_PROTEINMPNN_ROOT"]
    ).resolve()
    resources = _RunResources(tmp_path)
    adapter = LocalProteinMPNNAdapter(
        environment={
            "device": "cpu",
            "provider_root": provider_root,
        },
        resources=resources,
    )
    structure = _split_3gb1_into_two_chains(pdb_3gb1)
    layout = ResidueLayout(
        "B,A",
        56,
        [
            *(f"B:{position}" for position in range(1, 29)),
            *(f"A:{position}" for position in range(1, 29)),
        ],
    )
    result = adapter.design(
        residue_axis=resolve_residue_axis(structure),
        num_sequences=1,
        temperature=0.1,
        backbone_noise=0,
        seed=1603,
        constraints=ProteinMPNNConstraints(
            layout=layout,
            designed_chains=["A"],
            fixed_chains=["B"],
        ),
        reference_sequence=None,
        engine_role="design_parent_0",
    )

    restored = result[0]

    assert restored.sequence[:28] == "MTYKLILNGKTLKGETTTEAVDAATAEK"
    assert restored.residue_ids == layout.residue_ids
    assert resources.public_invocations == [
        {
            "engine_role": "design_parent_0",
            "invocation_provenance": {
                "effective_randomness": {
                    "control": "exact_seed",
                    "effective_seed": 1603,
                },
                "provider_residue_projection": {
                    "position_semantics": "one_based_chain_local",
                    "workbench_chain_order": ["B", "A"],
                    "provider_structure_chain_order": ["A", "B"],
                    "provider_chain_order": ["B", "A"],
                    "entries": [
                        *(
                            {
                                "residue_id": f"B:{position}",
                                "segment_index": 0,
                                "provider_chain_id": "A",
                                "provider_position": position,
                            }
                            for position in range(1, 29)
                        ),
                        *(
                            {
                                "residue_id": f"A:{position}",
                                "segment_index": 1,
                                "provider_chain_id": "B",
                                "provider_position": position,
                            }
                            for position in range(1, 29)
                        ),
                    ],
                },
            },
        }
    ]


def test_real_proteinmpnn_design_and_score_preserve_same_chain_segments(
    tmp_path: Path,
    pdb_3gb1: ProteinStructure,
) -> None:
    provider_root = Path(
        os.environ["PROTEIN_WORKBENCH_PROTEINMPNN_ROOT"]
    ).resolve()
    resources = _RunResources(tmp_path)
    adapter = LocalProteinMPNNAdapter(
        environment={
            "device": "cpu",
            "provider_root": provider_root,
        },
        resources=resources,
    )
    residue_axis = resolve_residue_axis(
        _split_3gb1_into_same_chain_segments(pdb_3gb1)
    )

    result = adapter.design(
        residue_axis=residue_axis,
        num_sequences=1,
        temperature=0.1,
        backbone_noise=0,
        seed=1603,
        constraints=ProteinMPNNConstraints(
            layout=residue_axis.layout,
            designed_chains=["A"],
            fixed_residue_ids=["A:28", "A:29"],
        ),
        reference_sequence=ProteinSequence(
            residue_axis.sequence,
            residue_axis.layout.residue_ids,
        ),
        engine_role="design_parent_0",
    )
    score = adapter.score(
        residue_axis=residue_axis,
        sequence=result[0],
    )

    assert len(residue_axis.segments) == 2
    assert [segment.chain_id for segment in residue_axis.segments] == ["A", "A"]
    assert result[0].residue_ids == residue_axis.layout.residue_ids
    assert result[0].sequence[27:29] == residue_axis.sequence[27:29]
    assert math.isfinite(score)
    projection = resources.public_invocations[0]["invocation_provenance"][
        "provider_residue_projection"
    ]
    assert projection["workbench_chain_order"] == ["A"]
    assert projection["provider_structure_chain_order"] == ["A", "B"]
    assert projection["provider_chain_order"] == ["A", "B"]
    assert projection["entries"][27] == {
        "residue_id": "A:28",
        "segment_index": 0,
        "provider_chain_id": "A",
        "provider_position": 28,
    }
    assert projection["entries"][28] == {
        "residue_id": "A:29",
        "segment_index": 1,
        "provider_chain_id": "B",
        "provider_position": 1,
    }
    assert resources.public_invocations[1]["invocation_provenance"][
        "provider_residue_projection"
    ] == projection


def test_real_proteinmpnn_preserves_fixed_csh_parent_with_missing_backbone_atom(
    tmp_path: Path,
) -> None:
    provider_root = Path(
        os.environ["PROTEIN_WORKBENCH_PROTEINMPNN_ROOT"]
    ).resolve()
    resources = _RunResources(tmp_path)
    adapter = LocalProteinMPNNAdapter(
        environment={
            "device": "cpu",
            "provider_root": provider_root,
        },
        resources=resources,
    )
    source = ProteinStructure(
        (
            Path(__file__).parent.parent.parent
            / "examples"
            / "v2"
            / "structures"
            / "2EMO.pdb"
        ).read_text(),
    )
    structure, normalizations = normalize_csh_parent_span(source)
    residue_axis = resolve_residue_axis(structure, normalizations)
    layout = ResidueLayout(
        "A",
        224,
        [f"A:{position}" for position in range(6, 230)],
    )
    result = adapter.design(
        residue_axis=residue_axis,
        num_sequences=1,
        temperature=0.1,
        backbone_noise=0,
        seed=1603,
        constraints=ProteinMPNNConstraints(
            layout=layout,
            fixed_residue_ids=["A:65", "A:66", "A:67"],
        ),
        reference_sequence=None,
        engine_role="design_parent_0",
    )

    restored = result[0]
    csh_parent_offset = layout.residue_ids.index("A:65")
    native_score = adapter.score(
        residue_axis=residue_axis,
        sequence=restored,
    )

    assert restored.sequence[csh_parent_offset : csh_parent_offset + 3] == "SHG"
    assert len(restored.sequence) == layout.length
    assert restored.residue_ids == layout.residue_ids
    expected_entries = [
        {
            "residue_id": f"A:{residue_number}",
            "segment_index": 0,
            "provider_chain_id": "A",
            "provider_position": provider_position,
        }
        for provider_position, residue_number in enumerate(
            range(6, 230),
            start=1,
        )
    ]
    expected_projection = {
        "position_semantics": "one_based_chain_local",
        "workbench_chain_order": ["A"],
        "provider_structure_chain_order": ["A"],
        "provider_chain_order": ["A"],
        "entries": expected_entries,
    }
    assert resources.public_invocations == [
        {
            "engine_role": "design_parent_0",
            "invocation_provenance": {
                "effective_randomness": {
                    "control": "exact_seed",
                    "effective_seed": 1603,
                },
                "provider_residue_projection": expected_projection,
            },
        },
        {
            "engine_role": "score_subject",
            "invocation_provenance": {
                "effective_randomness": {
                    "control": "exact_seed",
                    "effective_seed": 42,
                },
                "provider_residue_projection": expected_projection,
            },
        },
    ]
    assert math.isfinite(native_score)


def test_real_proteinmpnn_scores_signed_insertion_and_gap_axis(
    tmp_path: Path,
    pdb_3gb1: ProteinStructure,
) -> None:
    provider_root = Path(
        os.environ["PROTEIN_WORKBENCH_PROTEINMPNN_ROOT"]
    ).resolve()
    resources = _RunResources(tmp_path)
    adapter = LocalProteinMPNNAdapter(
        environment={
            "device": "cpu",
            "provider_root": provider_root,
        },
        resources=resources,
    )
    residue_axis = resolve_residue_axis(
        _stage_identity_edge_cases(pdb_3gb1)
    )

    score = adapter.score(
        residue_axis=residue_axis,
        sequence=ProteinSequence(
            residue_axis.sequence,
            residue_axis.layout.residue_ids,
        ),
    )

    assert residue_axis.layout.residue_ids[:3] == (
        "A:-2",
        "A:1A",
        "A:3",
    )
    assert math.isfinite(score)
    projection = resources.public_invocations[0]["invocation_provenance"][
        "provider_residue_projection"
    ]
    assert projection["entries"][:3] == [
        {
            "residue_id": "A:-2",
            "segment_index": 0,
            "provider_chain_id": "A",
            "provider_position": 1,
        },
        {
            "residue_id": "A:1A",
            "segment_index": 0,
            "provider_chain_id": "A",
            "provider_position": 2,
        },
        {
            "residue_id": "A:3",
            "segment_index": 0,
            "provider_chain_id": "A",
            "provider_position": 3,
        },
    ]
