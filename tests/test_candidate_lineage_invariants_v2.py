"""Canonical Candidate parent-lineage admission and normalization tests."""

from __future__ import annotations

import pytest

from core import PortValueError, builtin_frozen_catalog, canonical_sha256
from core.value_admission import admitted_port_values, normalize_scientific_outputs
from datatypes import Candidate, CandidateCollection, ProteinSequence


_RESULT_IDENTITY = "sha256:" + ("c" * 64)
_BUILTINS = builtin_frozen_catalog()
_SEQUENCE_PORT_TYPE = _BUILTINS.require_port_type(
    "protein.sequence", "3.0.0"
)
_PARENT_DIGEST = _SEQUENCE_PORT_TYPE.content_digest(ProteinSequence("AA"))
_CHILD_DIGEST = _SEQUENCE_PORT_TYPE.content_digest(ProteinSequence("AT"))


def _candidate_digest(candidate: Candidate) -> str:
    return {
        "raw-parent": _PARENT_DIGEST,
        "raw-child": _CHILD_DIGEST,
    }[candidate.candidate_id]


@pytest.mark.parametrize(
    "parent_ids",
    (
        ("candidate parent",),
        ("candidate-parent", "candidate-parent"),
    ),
)
def test_candidate_collection_rejects_noncanonical_or_duplicate_parent_ids(
    parent_ids: tuple[str, ...],
) -> None:
    port_type = builtin_frozen_catalog().require_port_type(
        "candidate.collection",
        "4.0.0",
    )
    value = CandidateCollection(
        "collection",
        "protein.sequence",
        (
            Candidate(
                "candidate-child",
                ProteinSequence("MA"),
                parent_ids,
            ),
        ),
    )

    with pytest.raises(PortValueError, match="parent_ids|parent identit"):
        port_type.encode(value)


@pytest.mark.parametrize(
    "replacements",
    (
        ((b'"parent-aaaa"', b'"parent aaaa"'),),
        ((b'"parent-bbbb"', b'"parent-aaaa"'),),
    ),
)
def test_candidate_collection_codec_rejects_invalid_parent_ids(
    replacements: tuple[tuple[bytes, bytes], ...],
) -> None:
    port_type = builtin_frozen_catalog().require_port_type(
        "candidate.collection",
        "4.0.0",
    )
    canonical = port_type.encode(
        CandidateCollection(
            "collection",
            "protein.sequence",
            (
                Candidate(
                    "candidate-a",
                    ProteinSequence("MA"),
                    ("parent-aaaa", "parent-bbbb"),
                ),
            ),
        )
    )
    malformed = canonical
    for old, new in replacements:
        malformed = malformed.replace(old, new)

    with pytest.raises(PortValueError, match="parent_ids|parent identit"):
        port_type.decode(malformed)


@pytest.mark.parametrize(
    "items",
    (
        (
            Candidate(
                "candidate-a",
                ProteinSequence("MA"),
                ("candidate-a",),
            ),
        ),
        (
            Candidate(
                "candidate-a",
                ProteinSequence("MA"),
                ("candidate-b",),
            ),
            Candidate(
                "candidate-b",
                ProteinSequence("MG"),
                ("candidate-a",),
            ),
        ),
    ),
)
def test_candidate_collection_rejects_internal_lineage_cycles_on_encode(
    items: tuple[Candidate, ...],
) -> None:
    port_type = builtin_frozen_catalog().require_port_type(
        "candidate.collection",
        "4.0.0",
    )

    with pytest.raises(PortValueError, match="self-parent|contains a cycle"):
        port_type.encode(
            CandidateCollection("collection", "protein.sequence", items)
        )


@pytest.mark.parametrize(
    "replacements",
    (
        ((b'"parent-xxxx"', b'"candidate-a"'),),
        (
            (b'"parent-xxxx"', b'"candidate-b"'),
            (b'"parent-yyyy"', b'"candidate-a"'),
        ),
    ),
)
def test_candidate_collection_codec_rejects_internal_lineage_cycles(
    replacements: tuple[tuple[bytes, bytes], ...],
) -> None:
    port_type = builtin_frozen_catalog().require_port_type(
        "candidate.collection",
        "4.0.0",
    )
    canonical = port_type.encode(
        CandidateCollection(
            "collection",
            "protein.sequence",
            (
                Candidate(
                    "candidate-a",
                    ProteinSequence("MA"),
                    ("parent-xxxx",),
                ),
                Candidate(
                    "candidate-b",
                    ProteinSequence("MG"),
                    ("parent-yyyy",),
                ),
            ),
        )
    )
    malformed = canonical
    for old, new in replacements:
        malformed = malformed.replace(old, new)

    with pytest.raises(PortValueError, match="self-parent|contains a cycle"):
        port_type.decode(malformed)


def test_candidate_normalization_rejects_duplicate_raw_parent_ids() -> None:
    with pytest.raises(PortValueError, match="duplicate parent identities"):
        normalize_scientific_outputs(
            node_id="producer",
            result_identity=_RESULT_IDENTITY,
            inputs={},
            outputs={
                "parents": CandidateCollection(
                    "raw-parents",
                    "protein.sequence",
                    (Candidate("raw-parent", ProteinSequence("AA")),),
                ),
                "children": CandidateCollection(
                    "raw-children",
                    "protein.sequence",
                    (
                        Candidate(
                            "raw-child",
                            ProteinSequence("AT"),
                            ("raw-parent", "raw-parent"),
                        ),
                    ),
                ),
            },
            candidate_content_digest=_candidate_digest,
        )


def test_candidate_normalization_rejects_parent_ids_that_converge() -> None:
    normalized_parent_id = "candidate-" + canonical_sha256(
        {
            "schema_namespace": "protein-workbench-candidate/v2",
            "producer_result_identity": _RESULT_IDENTITY,
            "output_port": "parents",
            "sample_slot": "0:0",
            "parent_candidate_identities": [],
            "content_digest": _PARENT_DIGEST,
        }
    ).removeprefix("sha256:")
    admitted_parent = Candidate(
        normalized_parent_id,
        ProteinSequence("AA"),
    )

    with pytest.raises(
        PortValueError,
        match="normalize to one duplicate parent identity",
    ):
        normalize_scientific_outputs(
            node_id="producer",
            result_identity=_RESULT_IDENTITY,
            inputs={
                "admitted_parents": admitted_port_values(
                    port_type=_BUILTINS.require_port_type(
                        "candidate.collection", "4.0.0"
                    ),
                    multiplicity="one",
                    values=(
                        CandidateCollection(
                            "admitted-parents",
                            "protein.sequence",
                            (admitted_parent,),
                        ),
                    ),
                    candidate_data_port_types={
                        "protein.sequence": _SEQUENCE_PORT_TYPE,
                    },
                ),
            },
            outputs={
                "parents": CandidateCollection(
                    "raw-parents",
                    "protein.sequence",
                    (Candidate("raw-parent", ProteinSequence("AA")),),
                ),
                "children": CandidateCollection(
                    "raw-children",
                    "protein.sequence",
                    (
                        Candidate(
                            "raw-child",
                            ProteinSequence("AT"),
                            ("raw-parent", normalized_parent_id),
                        ),
                    ),
                ),
            },
            candidate_content_digest=_candidate_digest,
        )
