"""Public contract tests for canonical Candidate data identities."""

from dataclasses import FrozenInstanceError

import pytest

from core.operation import InputContentDigests
from datatypes import CandidateDataReference


def test_candidate_data_reference_is_immutable_and_round_trips_exact_fields(
) -> None:
    reference = CandidateDataReference(
        candidate_id="candidate-1",
        data_type_id="protein.sequence",
        content_digest="sha256:" + ("a" * 64),
    )

    public = {
        "candidate_id": "candidate-1",
        "data_type_id": "protein.sequence",
        "content_digest": "sha256:" + ("a" * 64),
    }
    assert reference.to_public() == public
    assert CandidateDataReference.from_public(public) == reference

    with pytest.raises(FrozenInstanceError):
        reference.candidate_id = "candidate-2"  # type: ignore[misc]


@pytest.mark.parametrize(
    ("field_name", "invalid_value"),
    (
        ("candidate_id", ""),
        ("candidate_id", " candidate-1"),
        ("candidate_id", "-candidate-1"),
        ("candidate_id", "候选"),
        ("candidate_id", "a" * 129),
        ("candidate_id", 1),
        ("data_type_id", ""),
        ("data_type_id", "protein sequence"),
        ("data_type_id", "a" * 129),
        ("data_type_id", 1),
        ("content_digest", "a" * 64),
        ("content_digest", "sha256:" + ("A" * 64)),
        ("content_digest", "sha256:" + ("a" * 63)),
        ("content_digest", 1),
    ),
)
def test_candidate_data_reference_rejects_noncanonical_fields(
    field_name: str,
    invalid_value: object,
) -> None:
    fields: dict[str, object] = {
        "candidate_id": "candidate-1",
        "data_type_id": "protein.sequence",
        "content_digest": "sha256:" + ("a" * 64),
    }
    fields[field_name] = invalid_value

    with pytest.raises(ValueError, match=field_name):
        CandidateDataReference(**fields)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "public",
    (
        [],
        {
            "candidate_id": "candidate-1",
            "data_type_id": "protein.sequence",
        },
        {
            "candidate_id": "candidate-1",
            "data_type_id": "protein.sequence",
            "content_digest": "sha256:" + ("a" * 64),
            "extra": "not part of the contract",
        },
    ),
)
def test_candidate_data_reference_from_public_requires_exact_fields(
    public: object,
) -> None:
    with pytest.raises(ValueError, match="exact fields"):
        CandidateDataReference.from_public(public)


def test_input_content_digests_admits_only_candidate_data_references() -> None:
    with pytest.raises(TypeError, match="CandidateDataReference"):
        InputContentDigests(
            port_type_id="candidate.collection",
            value_content_digests=("sha256:" + ("1" * 64),),
            candidate_data=(
                {
                    "candidate_id": "candidate-1",
                    "data_type_id": "protein.sequence",
                    "content_digest": "sha256:" + ("2" * 64),
                },
            ),  # type: ignore[arg-type]
        )


def test_candidate_data_reference_has_one_datatype_import_path() -> None:
    import core

    assert not hasattr(core, "CandidateDataReference")
