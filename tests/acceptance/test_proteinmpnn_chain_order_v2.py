"""Real ProteinMPNN acceptance for designed-first chain decoding."""

from __future__ import annotations

import math
import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from datatypes import (
    ProteinMPNNConstraints,
    ProteinStructure,
    ResidueLayout,
)
from modules.proteinmpnn.adapter import (
    LocalProteinMPNNAdapter,
)
from modules.structure_transform.implementation import normalize_csh_parent_span

from .conftest import require_ready


pytestmark = [
    pytest.mark.acceptance,
    pytest.mark.local_provider,
    pytest.mark.slow,
]


class _RunResources:
    def __init__(self, root: Path) -> None:
        self._root = root
        self.invocations: list[dict[str, object]] = []

    @contextmanager
    def temporary_directory(self, *, prefix: str) -> Iterator[Path]:
        with TemporaryDirectory(prefix=prefix, dir=self._root) as path:
            yield Path(path)

    @contextmanager
    def engine_invocation(self, **details: object) -> Iterator[None]:
        self.invocations.append(details)
        yield


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
            chain = "A"
            chain_residue_number = residue_number
        else:
            chain = "B"
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


def test_real_proteinmpnn_design_of_chain_b_restores_a_then_b_layout(
    tmp_path: Path,
    readiness: dict[str, bool],
    pdb_3gb1: ProteinStructure,
) -> None:
    require_ready("proteinmpnn", readiness)
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
        "A,B",
        56,
        [
            *(f"A:{position}" for position in range(1, 29)),
            *(f"B:{position}" for position in range(1, 29)),
        ],
    )
    result = adapter.design(
        structure=structure,
        num_sequences=1,
        temperature=0.1,
        backbone_noise=0,
        seed=1603,
        constraints=ProteinMPNNConstraints(
            layout=layout,
            designed_chains=["B"],
            fixed_chains=["A"],
        ),
        reference_sequence=None,
        engine_role="design_parent_0",
    )

    restored = result[0]

    assert restored.sequence[:28] == "MTYKLILNGKTLKGETTTEAVDAATAEK"
    assert restored.residue_ids == layout.residue_ids
    assert resources.invocations == [
        {
            "engine_role": "design_parent_0",
            "invocation_provenance": {
                "effective_randomness": {
                    "control": "exact_seed",
                    "effective_seed": 1603,
                },
                "provider_residue_projection": {
                    "position_semantics": "one_based_chain_local",
                    "workbench_chain_order": ["A", "B"],
                    "provider_chain_order": ["B", "A"],
                    "entries": [
                        *(
                            {
                                "residue_id": f"A:{position}",
                                "provider_chain_id": "A",
                                "provider_position": position,
                            }
                            for position in range(1, 29)
                        ),
                        *(
                            {
                                "residue_id": f"B:{position}",
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


def test_real_proteinmpnn_preserves_fixed_csh_parent_with_missing_backbone_atom(
    tmp_path: Path,
    readiness: dict[str, bool],
) -> None:
    require_ready("proteinmpnn", readiness)
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
        (Path(__file__).parent.parent.parent / "pdbs" / "2EMO.pdb").read_text(),
    )
    structure, _ = normalize_csh_parent_span(source)
    layout = ResidueLayout(
        "A",
        224,
        [f"A:{position}" for position in range(6, 230)],
    )
    result = adapter.design(
        structure=structure,
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
        structure=structure,
        sequence=restored,
    )

    assert restored.sequence[csh_parent_offset : csh_parent_offset + 3] == "SHG"
    assert len(restored.sequence) == layout.length
    assert restored.residue_ids == layout.residue_ids
    expected_entries = [
        {
            "residue_id": f"A:{residue_number}",
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
        "provider_chain_order": ["A"],
        "entries": expected_entries,
    }
    assert resources.invocations == [
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
                "provider_residue_projection": expected_projection,
            },
        },
    ]
    assert math.isfinite(native_score)
