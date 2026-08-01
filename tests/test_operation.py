import pytest

from core.operation import (
    CandidateDataDigest,
    CandidatePairingIntent,
    CandidatePairingIntentEntry,
    InputContentDigests,
)
from core.port_types import PortValueError, canonical_sha256
from core.value_admission import normalize_scientific_outputs
from datatypes import (
    Candidate,
    CandidateCollection,
    PairwiseCandidateMapping,
    PairwiseCandidateMatch,
    ProteinSequence,
)


def test_input_content_digests_snapshots_caller_owned_sequences() -> None:
    value_content_digests = ["sha256:" + ("1" * 64)]
    candidate_digest = CandidateDataDigest(
        candidate_id="candidate-1",
        data_type_id="protein.sequence",
        content_digest="sha256:" + ("2" * 64),
    )
    candidate_data = [candidate_digest]

    admitted = InputContentDigests(
        port_type_id="candidate.collection",
        value_content_digests=value_content_digests,  # type: ignore[arg-type]
        candidate_data=candidate_data,  # type: ignore[arg-type]
    )

    value_content_digests.append("sha256:" + ("3" * 64))
    candidate_data.clear()

    assert admitted.value_content_digests == ("sha256:" + ("1" * 64),)
    assert admitted.candidate_data == (candidate_digest,)


def _candidate_outputs(pairing: CandidatePairingIntent) -> dict[str, object]:
    return {
        "subjects": CandidateCollection(
            "raw-subjects",
            "protein.sequence",
            [Candidate("raw-subject", ProteinSequence("AA"))],
        ),
        "references": CandidateCollection(
            "raw-references",
            "protein.sequence",
            [Candidate("raw-reference", ProteinSequence("AT"))],
        ),
        "pairing": pairing,
    }


def test_pairing_intent_projects_normalized_exact_candidate_content() -> None:
    subject_digest = "sha256:" + ("a" * 64)
    reference_digest = "sha256:" + ("b" * 64)
    normalized = normalize_scientific_outputs(
        node_id="source",
        result_identity="sha256:" + ("c" * 64),
        inputs={},
        outputs=_candidate_outputs(
            CandidatePairingIntent(
                (
                    CandidatePairingIntentEntry(
                        subject_candidate_id="raw-subject",
                        reference_candidate_id="raw-reference",
                    ),
                )
            )
        ),
        candidate_content_digest=lambda candidate: (
            subject_digest
            if candidate.candidate_id == "raw-subject"
            else reference_digest
        ),
    )

    subject = normalized["subjects"].items[0]
    reference = normalized["references"].items[0]
    pairing = normalized["pairing"]
    assert type(pairing) is PairwiseCandidateMapping
    assert pairing.entries == (
        PairwiseCandidateMatch(
            subject_candidate_id=subject.candidate_id,
            subject_content_digest=subject_digest,
            reference_candidate_id=reference.candidate_id,
            reference_content_digest=reference_digest,
        ),
    )


@pytest.mark.parametrize(
    ("entries", "message"),
    (
        (
            (
                CandidatePairingIntentEntry(
                    "unknown-subject",
                    "raw-reference",
                ),
            ),
            "unknown Candidate identity",
        ),
        (
            (
                CandidatePairingIntentEntry(
                    "raw-subject",
                    "raw-reference",
                ),
                CandidatePairingIntentEntry(
                    "raw-subject",
                    "raw-reference",
                ),
            ),
            "duplicate exact pair",
        ),
        (
            (
                CandidatePairingIntentEntry(
                    "raw-subject",
                    "raw-reference",
                ),
                CandidatePairingIntentEntry(
                    "raw-subject",
                    "raw-subject",
                ),
            ),
            "conflicting counterpart",
        ),
    ),
)
def test_pairing_intent_fails_closed_before_port_admission(
    entries: tuple[CandidatePairingIntentEntry, ...],
    message: str,
) -> None:
    with pytest.raises(PortValueError, match=message):
        normalize_scientific_outputs(
            node_id="source",
            result_identity="sha256:" + ("c" * 64),
            inputs={},
            outputs=_candidate_outputs(CandidatePairingIntent(entries)),
            candidate_content_digest=lambda candidate: (
                "sha256:" + ("a" * 64)
            ),
        )


def _lineage_digest(candidate: Candidate) -> str:
    return {
        "raw-parent": "sha256:" + ("1" * 64),
        "raw-child": "sha256:" + ("2" * 64),
    }[candidate.candidate_id]


def test_candidate_lineage_resolution_does_not_depend_on_output_port_sort() -> None:
    outputs = {
        "a_children": CandidateCollection(
            "raw-children",
            "protein.sequence",
            [
                Candidate(
                    "raw-child",
                    ProteinSequence("AT"),
                    parent_ids=("raw-parent",),
                )
            ],
        ),
        "z_parents": CandidateCollection(
            "raw-parents",
            "protein.sequence",
            [Candidate("raw-parent", ProteinSequence("AA"))],
        ),
    }

    normalized = normalize_scientific_outputs(
        node_id="producer",
        result_identity="sha256:" + ("c" * 64),
        inputs={},
        outputs=outputs,
        candidate_content_digest=_lineage_digest,
    )

    parent = normalized["z_parents"].items[0]
    child = normalized["a_children"].items[0]
    expected_parent_id = "candidate-" + canonical_sha256(
        {
            "schema_namespace": "protein-workbench-candidate/v2",
            "producer_result_identity": "sha256:" + ("c" * 64),
            "output_port": "z_parents",
            "sample_slot": "0:0",
            "parent_candidate_identities": [],
            "content_digest": "sha256:" + ("1" * 64),
        }
    ).removeprefix("sha256:")
    expected_child_id = "candidate-" + canonical_sha256(
        {
            "schema_namespace": "protein-workbench-candidate/v2",
            "producer_result_identity": "sha256:" + ("c" * 64),
            "output_port": "a_children",
            "sample_slot": "0:0",
            "parent_candidate_identities": [expected_parent_id],
            "content_digest": "sha256:" + ("2" * 64),
        }
    ).removeprefix("sha256:")

    assert parent.candidate_id == expected_parent_id
    assert child.candidate_id == expected_child_id
    assert child.parent_ids == (parent.candidate_id,)
    assert child.metadata == {
        "producer_result_identity": "sha256:" + ("c" * 64),
        "output_port": "a_children",
        "sample_slot": "0:0",
        "content_digest": "sha256:" + ("2" * 64),
    }

    normalized_from_reverse_insertion = normalize_scientific_outputs(
        node_id="producer",
        result_identity="sha256:" + ("c" * 64),
        inputs={},
        outputs=dict(reversed(tuple(outputs.items()))),
        candidate_content_digest=_lineage_digest,
    )
    assert normalized_from_reverse_insertion == normalized


def test_candidate_lineage_rejects_unknown_parent_without_root_fallback() -> None:
    with pytest.raises(
        PortValueError,
        match="not a resolved input or output Candidate",
    ):
        normalize_scientific_outputs(
            node_id="producer",
            result_identity="sha256:" + ("c" * 64),
            inputs={},
            outputs={
                "children": CandidateCollection(
                    "raw-children",
                    "protein.sequence",
                    [
                        Candidate(
                            "raw-child",
                            ProteinSequence("AT"),
                            parent_ids=("producer",),
                        )
                    ],
                )
            },
            candidate_content_digest=_lineage_digest,
        )


def test_root_candidate_requires_empty_parent_lineage() -> None:
    normalized = normalize_scientific_outputs(
        node_id="producer",
        result_identity="sha256:" + ("c" * 64),
        inputs={},
        outputs={
            "roots": CandidateCollection(
                "raw-roots",
                "protein.sequence",
                [Candidate("raw-parent", ProteinSequence("AA"))],
            )
        },
        candidate_content_digest=_lineage_digest,
    )

    assert normalized["roots"].items[0].parent_ids == ()


def test_candidate_lineage_rejects_duplicate_output_identity() -> None:
    duplicate = Candidate("raw-parent", ProteinSequence("AA"))
    with pytest.raises(
        PortValueError,
        match="reuses one producer identity",
    ):
        normalize_scientific_outputs(
            node_id="producer",
            result_identity="sha256:" + ("c" * 64),
            inputs={},
            outputs={"parents": duplicate, "references": duplicate},
            candidate_content_digest=_lineage_digest,
        )


@pytest.mark.parametrize(
    "outputs",
    (
        {
            "children": Candidate(
                "raw-child",
                ProteinSequence("AT"),
                parent_ids=("raw-child",),
            )
        },
        {
            "children": Candidate(
                "raw-child",
                ProteinSequence("AT"),
                parent_ids=("raw-parent",),
            ),
            "parents": Candidate(
                "raw-parent",
                ProteinSequence("AA"),
                parent_ids=("raw-child",),
            ),
        },
    ),
)
def test_candidate_lineage_rejects_cycles(
    outputs: dict[str, Candidate],
) -> None:
    with pytest.raises(PortValueError, match="lineage contains a cycle"):
        normalize_scientific_outputs(
            node_id="producer",
            result_identity="sha256:" + ("c" * 64),
            inputs={},
            outputs=outputs,
            candidate_content_digest=_lineage_digest,
        )
