"""Real ProteinMPNN acceptance for designed-first chain decoding."""

from __future__ import annotations

import math
import os
from pathlib import Path

import pytest

from datatypes import (
    ProteinMPNNConstraints,
    ProteinStructure,
    ResidueLayout,
)
from modules.proteinmpnn.v2_adapter import (
    prepare_design_request,
    prepare_scoring_request,
    provider_for_environment,
    validate_design_result,
    validate_scoring_result,
)
from modules.structure_transform.implementation import normalize_csh_parent_span

from .conftest import require_ready


pytestmark = [
    pytest.mark.acceptance,
    pytest.mark.local_provider,
    pytest.mark.slow,
]


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
        source="3GB1-split-A28-B28",
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
    provider = provider_for_environment(
        {
            "device": "cpu",
            "provider_root": provider_root,
        },
        staging_directory=tmp_path,
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
    request = prepare_design_request(
        provider=provider,
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
    )

    raw_result = provider.design(request)
    raw_sequences, _ = raw_result
    restored, scores = validate_design_result(raw_result, request=request)
    chain_a = request.pdb_dict_list[0]["seq_chain_A"]

    assert request.structure_chain_order == ("A", "B")
    assert request.provider_chain_order == ("B", "A")
    assert raw_sequences[0].sequence[28:] == chain_a
    assert restored[0].sequence[:28] == chain_a
    assert restored[0].residue_ids == layout.residue_ids
    assert scores is not None and len(scores) == 1


def test_real_proteinmpnn_preserves_fixed_csh_parent_with_missing_backbone_atom(
    tmp_path: Path,
    readiness: dict[str, bool],
) -> None:
    require_ready("proteinmpnn", readiness)
    provider_root = Path(
        os.environ["PROTEIN_WORKBENCH_PROTEINMPNN_ROOT"]
    ).resolve()
    provider = provider_for_environment(
        {
            "device": "cpu",
            "provider_root": provider_root,
        },
        staging_directory=tmp_path,
    )
    source = ProteinStructure(
        (Path(__file__).parent.parent.parent / "pdbs" / "2EMO.pdb").read_text(),
        source="pdbs/2EMO.pdb",
    )
    structure, _ = normalize_csh_parent_span(source)
    layout = ResidueLayout(
        "A",
        224,
        [f"A:{position}" for position in range(6, 230)],
    )
    request = prepare_design_request(
        provider=provider,
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
    )

    raw_result = provider.design(request)
    restored, scores = validate_design_result(raw_result, request=request)
    csh_parent_offset = layout.residue_ids.index("A:65")
    scoring_request = prepare_scoring_request(
        provider=provider,
        structure=structure,
        sequence=restored[0],
    )
    native_score = validate_scoring_result(
        provider.score(scoring_request, restored[0])
    )

    assert request.fixed_position_dict == {
        request.pdb_dict_list[0]["name"]: {"A": [60, 61, 62]}
    }
    assert restored[0].sequence[csh_parent_offset : csh_parent_offset + 3] == "SHG"
    assert len(restored[0].sequence) == layout.length
    assert restored[0].residue_ids == layout.residue_ids
    assert scores is not None and len(scores) == 1
    assert scoring_request.target_layout == layout
    assert math.isfinite(native_score)
