"""Shared provider-independent folding output construction contracts."""

from __future__ import annotations

import pytest

from datatypes import (
    Candidate,
    CandidateCollection,
    CandidateDataReference,
    ExactContractReference,
    ProteinSequence,
    ProteinStructure,
)
from modules.folding._output_construction import (
    CompletedFoldingSample,
    CompletedFoldingSampleBatch,
    FoldingOutputConstruction,
)
from tests.fixtures.scientific_operation import admitted_port_fixture


_METHOD = ExactContractReference(
    contract_kind="method",
    contract_id="folding.fold.fixture",
    contract_version="1.0.0",
    contract_digest="sha256:" + ("f" * 64),
)


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
    sample_count: int = 2,
) -> FoldingOutputConstruction:
    collection, references = _parents(*sequences)
    return FoldingOutputConstruction(
        parent_record=admitted_port_fixture(
            collection,
            port_type_id="candidate.collection",
            value_content_digests=("sha256:" + ("e" * 64),),
            candidate_data=references,
        ),
        sample_count=sample_count,
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


def test_shared_output_construction_closes_and_canonicalizes_one_population(
) -> None:
    construction = _construction(
        ProteinSequence("AG", ("Q:-2A", "Q:10")),
        ProteinSequence("AG"),
    )

    outputs = construction.construct(
        CompletedFoldingSampleBatch(
            (
                _sample(1, 1),
                _sample(0, 1),
                _sample(1, 0),
                _sample(0, 0),
            )
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
            "prediction_key",
            "effective_call_seed",
            "num_steps",
        }
        for item in structures.items
    )

    facts = outputs["confidence_facts"]
    facts_by_key = {fact.prediction_key: fact for fact in facts.entries}
    assert facts.observation_method == _METHOD
    assert set(facts_by_key) == {
        item.metadata["prediction_key"] for item in structures.items
    }
    for item in structures.items:
        fact = facts_by_key[item.metadata["prediction_key"]]
        parent_slot = item.metadata["parent_index"]
        assert fact.prediction_axis.source.candidate_id == (
            f"parent-{parent_slot}"
        )
        assert fact.prediction_axis.sequence.residue_ids == (
            ("Q:-2A", "Q:10")
            if parent_slot == 0
            else ("A:1", "A:2")
        )
        assert fact.structure_content_digest.startswith("sha256:")
        assert fact.plddt_per_residue == (
            float(70 + 10 * parent_slot + item.metadata["sample_index"]),
            float(71 + 10 * parent_slot + item.metadata["sample_index"]),
        )


@pytest.mark.parametrize(
    "samples",
    (
        (_sample(0, 0),),
        (_sample(0, 0), _sample(0, 0), _sample(0, 1)),
        (_sample(0, 0), _sample(0, 1), _sample(1, 0)),
    ),
    ids=("missing", "duplicate", "extra"),
)
def test_shared_output_construction_rejects_non_closed_sample_batches(
    samples: tuple[CompletedFoldingSample, ...],
) -> None:
    construction = _construction(ProteinSequence("AG"))

    with pytest.raises(ValueError, match="parent/sample slot"):
        construction.construct(CompletedFoldingSampleBatch(samples))


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
            sample_count=1,
            observation_method=_METHOD,
        )
