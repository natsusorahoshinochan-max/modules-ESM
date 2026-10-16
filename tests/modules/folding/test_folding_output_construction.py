"""Shared provider-independent folding output construction contracts."""

from __future__ import annotations

from core.catalog.builder import build_frozen_catalog
from core.operation import OutputIdentityIntent

import pytest

from datatypes.candidate import (
    Candidate,
    CandidateCollection,
    CandidateDataReference,
)
from datatypes.exact_reference import ExactContractReference
from datatypes.prediction import PendingConfidenceFactCollection
from datatypes.sequence import ProteinSequence
from datatypes.structure import ProteinStructure
from modules.folding._output_construction import (
    CompletedFoldingSample,
    FoldingOutputConstruction,
)
from tests.fixtures.scientific_operation import (
    admitted_port_fixture,
    operation_call,
)


_METHOD = ExactContractReference(
    contract_kind="method",
    contract_id="folding.fold.fixture")


def _structure() -> ProteinStructure:
    return ProteinStructure(
        "\n".join(
            (
                "ATOM      1  N   ALA A   1       0.000   0.000   0.000  1.00 70.00           N  ",
                "ATOM      2  CA  ALA A   1       1.000   0.000   0.000  1.00 70.00           C  ",
                "ATOM      3  C   ALA A   1       2.000   0.000   0.000  1.00 70.00           C  ",
                "ATOM      4  N   GLY A   2       3.000   0.000   0.000  1.00 80.00           N  ",
                "ATOM      5  CA  GLY A   2       4.000   0.000   0.000  1.00 80.00           C  ",
                "ATOM      6  C   GLY A   2       5.000   0.000   0.000  1.00 80.00           C  ",
                "TER",
                "END",
                "",
            )
        )
    )


def _parents(
    *sequences: ProteinSequence,
) -> tuple[CandidateCollection, tuple[CandidateDataReference, ...]]:
    candidates = tuple(
        Candidate(f"parent-{index}", sequence)
        for index, sequence in enumerate(sequences)
    )
    references = tuple(
        CandidateDataReference(
            candidate_id=candidate.candidate_id,
            data_type_id="protein.sequence",
            content_digest="sha256:" + str(index + 1) * 64,
        )
        for index, candidate in enumerate(candidates)
    )
    return (
        CandidateCollection("parents", "protein.sequence", candidates),
        references,
    )


def _construction(
    *sequences: ProteinSequence,
) -> FoldingOutputConstruction:
    collection, references = _parents(*sequences)
    return FoldingOutputConstruction(
        parent_record=admitted_port_fixture(
            collection,
            port_type_id="candidate.collection",
            value_content_digests=("sha256:" + ("e" * 64),),
            candidate_data=references,
        ),
        observation_method=_METHOD,
    )


def _sample(parent_slot: int, sample_slot: int) -> CompletedFoldingSample:
    value = float(70 + 10 * parent_slot + sample_slot)
    return CompletedFoldingSample(
        parent_slot=parent_slot,
        sample_slot=sample_slot,
        structure=_structure(),
        per_residue_plddt=(value, value + 1.0),
        ptm=0.75,
        pae=((0.0, 1.0), (1.0, 0.0)),
        effective_call_seed=100 + parent_slot,
        num_steps=10,
    )


def test_shared_output_construction_publishes_one_population(
) -> None:
    construction = _construction(
        ProteinSequence("AG", ("Q:-2A", "Q:10")),
        ProteinSequence("AG"),
    )

    outputs = construction.construct(
        (
            _sample(0, 0),
            _sample(0, 1),
            _sample(1, 0),
            _sample(1, 1),
        )
    )

    structures = outputs["structure_candidates"]
    assert [
        (item.metadata["parent_index"], item.metadata["sample_index"])
        for item in structures.items
    ] == [(0, 0), (0, 1), (1, 0), (1, 1)]
    assert [item.parent_ids for item in structures.items] == [
        ("parent-0",),
        ("parent-0",),
        ("parent-1",),
        ("parent-1",),
    ]
    assert all(
        set(item.metadata)
        == {
            "parent_index",
            "sample_index",
            "effective_call_seed",
            "num_steps",
        }
        for item in structures.items
    )

    intent = outputs["confidence_facts"]
    assert type(intent) is OutputIdentityIntent
    assert type(intent.relation) is PendingConfidenceFactCollection
    assert intent.relation.observation_method == _METHOD
    assert len(intent.relation.entries) == 4
    assert len(intent.identity_sources) == 8
    assert not hasattr(intent, "resolve_identities")
    assert all(
        not hasattr(source, "port_type")
        for source in intent.identity_sources
    )
    assert {source.source_role for source in intent.identity_sources} == {
        "structure",
        "prediction-axis",
    }
    for pending in intent.relation.entries:
        parent_slot = int(pending.candidate_id.split("-")[2])
        assert pending.prediction_axis.source.candidate_id == (
            f"parent-{parent_slot}"
        )
        assert pending.prediction_axis.sequence.residue_ids == (
            ("Q:-2A", "Q:10")
            if parent_slot == 0
            else ("A:1", "A:2")
        )
        assert pending.plddt_per_residue == (
            float(70 + 10 * parent_slot + pending.output_slot % 2),
            float(71 + 10 * parent_slot + pending.output_slot % 2),
        )


@pytest.mark.parametrize(
    "sequence",
    (
        ProteinSequence("AX", ("A:1", "A:2")),
        ProteinSequence("AG", ("A:1", "B:1")),
    ),
)
def test_shared_parent_intake_checks_folding_specific_sequence_science(
    sequence: ProteinSequence,
) -> None:
    with pytest.raises(ValueError, match="folding requires"):
        _construction(sequence)


def test_shared_parent_intake_rejects_an_empty_collection() -> None:
    collection, references = _parents()

    with pytest.raises(ValueError, match="non-empty"):
        FoldingOutputConstruction(
            parent_record=admitted_port_fixture(
                collection,
                port_type_id="candidate.collection",
                value_content_digests=("sha256:" + ("e" * 64),),
                candidate_data=references,
            ),
            observation_method=_METHOD,
        )


def test_shared_parent_intake_rejects_an_admitted_structure_collection(
) -> None:
    from core.catalog.builder import (
        build_frozen_catalog,
    )
    from modules.folding.package import MODULE_PACKAGE as FOLDING_PACKAGE
    from modules.structure_prediction.package import (
        MODULE_PACKAGE as STRUCTURE_PREDICTION_PACKAGE,
    )
    from modules.structure_transform.package import (
        MODULE_PACKAGE as STRUCTURE_TRANSFORM_PACKAGE,
    )

    catalog = build_frozen_catalog(
        (
            FOLDING_PACKAGE,
            STRUCTURE_PREDICTION_PACKAGE,
            STRUCTURE_TRANSFORM_PACKAGE,
        )
    )
    call = operation_call(
        catalog=catalog,
        binding_id="folding.fold.esmfold2_remote",
        inputs={
            "sequence_candidates": CandidateCollection(
                "structure-parents",
                "protein.structure",
                (Candidate("structure-parent", _structure()),),
            )
        },
        node_parameters={"effective_seed": 1603, "num_samples": 1},
    )
    parent_record = call.inputs["sequence_candidates"]
    assert parent_record.value.item_type == "protein.structure"
    assert parent_record.candidate_data[0].data_type_id == "protein.structure"

    with pytest.raises(
        ValueError,
        match="folding requires non-empty protein sequence Candidates",
    ):
        FoldingOutputConstruction(
            parent_record=parent_record,
            observation_method=_METHOD,
        )
