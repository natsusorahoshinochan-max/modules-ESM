"""Canonical Candidate identifier and built-in Port generation contracts."""

from __future__ import annotations

from dataclasses import replace

import pytest

from core.catalog.builtins import (
    builtin_frozen_catalog,
)
from core.catalog.errors import (
    UnknownPortTypeError,
    PortValueError,
)
from datatypes.candidate import (
    Candidate,
    CandidateCollection,
    CandidateDataReference,
)
from datatypes.exact_reference import (
    ExactContractReference,
)
from datatypes.identifier import validate_canonical_identifier
from datatypes.observation import (
    CalibrationObservationContext,
    IntrinsicObservationContext,
    PairwiseCandidateMapping,
    PairwiseCandidateMatch,
    PairwiseObservationContext,
    PairwiseParticipant,
    ScoreCollection,
    ScoreObservation,
)
from datatypes.sequence import ProteinSequence


_DIGEST_1 = "sha256:" + ("1" * 64)
_DIGEST_2 = "sha256:" + ("2" * 64)
_DIGEST_3 = "sha256:" + ("3" * 64)


@pytest.mark.parametrize(
    "identifier",
    (
        "A",
        "candidate/a",
        "candidate:a",
        "candidate+a",
        "a" * 128,
    ),
)
def test_canonical_identifier_accepts_the_public_identifier_domain(
    identifier: str,
) -> None:
    assert validate_canonical_identifier(identifier, "candidate_id") == identifier


@pytest.mark.parametrize(
    "identifier",
    (
        "",
        "-candidate",
        "candidate id",
        "候选",
        "a" * 129,
        1,
    ),
)
def test_canonical_identifier_rejects_values_outside_the_public_domain(
    identifier: object,
) -> None:
    with pytest.raises(ValueError, match="candidate_id"):
        validate_canonical_identifier(identifier, "candidate_id")


def test_canonical_identifier_requires_an_exact_string() -> None:
    class IdentifierSubclass(str):
        pass

    with pytest.raises(ValueError, match="candidate_id"):
        validate_canonical_identifier(
            IdentifierSubclass("candidate-1"),
            "candidate_id",
        )


@pytest.mark.parametrize(
    ("field_name", "invalid_value"),
    (
        ("contract_kind", "unknown"),
        ("contract_id", "contract id"),
        ("contract_version", "version"),
        ("contract_digest", "digest"),
    ),
)
def test_exact_contract_reference_owns_its_intrinsic_identity(
    field_name: str,
    invalid_value: str,
) -> None:
    values = {
        "contract_kind": "method",
        "contract_id": "method/fixture",
        "contract_version": "1.0.0",
        "contract_digest": _DIGEST_1,
    }
    values[field_name] = invalid_value

    with pytest.raises(ValueError, match=field_name):
        ExactContractReference(**values)


def test_candidate_ports_publish_only_the_active_identifier_generation() -> None:
    catalog = builtin_frozen_catalog()

    for type_id in (
        "candidate.collection",
        "candidate.pairing",
    ):
        assert catalog.require_port_type(type_id, "4.0.0").version == "4.0.0"
        for inactive_version in ("2.1.0", "3.0.0"):
            with pytest.raises(UnknownPortTypeError):
                catalog.require_port_type(type_id, inactive_version)
    assert catalog.require_port_type(
        "score.collection", "5.0.0"
    ).version == "5.0.0"
    for inactive_version in ("2.1.0", "3.0.0", "4.0.0"):
        with pytest.raises(UnknownPortTypeError):
            catalog.require_port_type("score.collection", inactive_version)


def test_candidate_collection_v3_closes_all_candidate_identifiers() -> None:
    port_type = builtin_frozen_catalog().require_port_type(
        "candidate.collection",
        "4.0.0",
    )
    valid = CandidateCollection(
        "collection/a:b+c",
        "protein.sequence",
        (
            Candidate(
                "candidate/a:b+c",
                ProteinSequence("MA"),
                ("parent/a", "parent:b", "parent+c"),
            ),
        ),
    )

    assert port_type.decode(port_type.encode(valid)) == valid

    invalid_values = (
        replace(valid, collection_id="候选"),
        replace(
            valid,
            items=(replace(valid.items[0], candidate_id="候选"),),
        ),
        replace(
            valid,
            items=(replace(valid.items[0], parent_ids=("a" * 129,)),),
        ),
    )
    for invalid in invalid_values:
        with pytest.raises(PortValueError, match="identifier"):
            port_type.encode(invalid)

    # Candidate values may exist provisionally before a Candidate Collection
    # contract owns admission.
    assert Candidate("候选", ProteinSequence("MA")).candidate_id == "候选"


def test_candidate_pairing_v3_closes_both_participant_identifiers() -> None:
    port_type = builtin_frozen_catalog().require_port_type(
        "candidate.pairing",
        "4.0.0",
    )
    valid_match = PairwiseCandidateMatch(
        subject=CandidateDataReference(
            candidate_id="subject/a:b+c",
            data_type_id="protein.sequence",
            content_digest=_DIGEST_1,
        ),
        reference=CandidateDataReference(
            candidate_id="reference/a:b+c",
            data_type_id="protein.structure",
            content_digest=_DIGEST_2,
        ),
    )
    valid = PairwiseCandidateMapping((valid_match,))

    encoded = port_type.encode(valid)

    assert port_type.decode(encoded) == valid
    assert b'"subject"' in encoded
    assert b'"reference"' in encoded
    assert b'"data_type_id":"protein.sequence"' in encoded
    assert b'"data_type_id":"protein.structure"' in encoded
    assert b'"subject_candidate_id"' not in encoded

    for invalid_candidate_id in (
        "候选",
        "a" * 129,
    ):
        with pytest.raises(ValueError, match="candidate_id"):
            CandidateDataReference(
                candidate_id=invalid_candidate_id,
                data_type_id="protein.sequence",
                content_digest=_DIGEST_1,
            )

    association_contract = port_type.descriptor()["validator"][
        "parameters"
    ]["association_contract"]
    assert association_contract == {
        "entry_fields": ["subject", "reference"],
        "participant": "CandidateDataReference",
        "participant_fields": [
            "candidate_id",
            "data_type_id",
            "content_digest",
        ],
        "cardinality": "one-to-one",
    }


def _reference(kind: str, contract_id: str) -> ExactContractReference:
    return ExactContractReference(
        contract_kind=kind,
        contract_id=contract_id,
        contract_version="3.0.0",
        contract_digest=_DIGEST_3,
    )


def _score(
    *,
    candidate_id: str = "candidate/a:b+c",
    metric_id: str = "metric/a:b+c",
    method_id: str = "method/a:b+c",
    context: object | None = None,
    source_partition: str = "partition/a:b+c",
) -> ScoreObservation:
    observation_context = context or IntrinsicObservationContext()
    subject_digest = (
        observation_context.subject.content_digest
        if isinstance(observation_context, PairwiseObservationContext)
        else _DIGEST_1
    )
    return ScoreObservation(
        subject=CandidateDataReference(
            candidate_id,
            "protein.sequence",
            subject_digest,
        ),
        metric=_reference("metric", metric_id),
        method=_reference("method", method_id),
        context=observation_context,  # type: ignore[arg-type]
        value=0.5,
        source_partition=source_partition,
    )


def test_score_collection_v4_closes_every_public_generic_identifier() -> None:
    port_type = builtin_frozen_catalog().require_port_type(
        "score.collection",
        "5.0.0",
    )
    pairwise_context = PairwiseObservationContext(
        subject=PairwiseParticipant(
            "subject",
            CandidateDataReference(
                "candidate/a", "protein.sequence", _DIGEST_1
            ),
        ),
        reference=PairwiseParticipant(
            "reference",
            CandidateDataReference(
                "reference:b", "protein.sequence", _DIGEST_2
            ),
        ),
        pairing_mode="fixed_reference",
        normalization="reference+length",
        evidence_content_digest=_DIGEST_3,
        evidence_method=_reference("method", "alignment/method"),
        normalization_length=2,
        aligned_atom_count=2,
    )
    valid = ScoreCollection(
        "scores/a:b+c",
        (
            _score(),
            _score(
                candidate_id="candidate/a",
                context=pairwise_context,
                source_partition="pairwise/a",
            ),
        ),
    )

    assert port_type.decode(port_type.encode(valid)) == valid

    invalid_values = (
        replace(valid, collection_id="候选"),
        ScoreCollection(
            "scores",
            (_score(source_partition="partition value"),),
        ),
        ScoreCollection(
            "scores",
            (
                _score(
                    context=CalibrationObservationContext(
                        calibration_metric="metric/ok",
                        calibration_value=0.5,
                        calibration_unit="unit ok",
                        population_id="population/ok",
                    )
                ),
            ),
        ),
    )
    for invalid in invalid_values:
        with pytest.raises(PortValueError, match="identifier"):
            port_type.encode(invalid)

    with pytest.raises(ValueError, match="candidate_id"):
        _score(candidate_id="候选")


def test_score_observation_rejects_non_reference_subject_at_construction() -> None:
    with pytest.raises(TypeError, match="CandidateDataReference"):
        ScoreObservation(
            subject="candidate-1",  # type: ignore[arg-type]
            metric=_reference("metric", "quality"),
            method=_reference("method", "fixture"),
            context=IntrinsicObservationContext(),
            source_partition="default",
            value=0.5,
        )


def test_pairwise_evidence_provenance_is_atomic() -> None:
    context = PairwiseObservationContext(
        subject=PairwiseParticipant(
            "subject",
            CandidateDataReference(
                "subject", "protein.sequence", _DIGEST_1
            ),
        ),
        reference=PairwiseParticipant(
            "reference",
            CandidateDataReference(
                "reference", "protein.sequence", _DIGEST_2
            ),
        ),
        pairing_mode="fixed_reference",
        normalization="reference-length",
        evidence_content_digest=_DIGEST_3,
        evidence_method=_reference("method", "alignment"),
        normalization_length=2,
        aligned_atom_count=2,
    )

    for field_name in (
        "evidence_content_digest",
        "evidence_method",
        "normalization_length",
        "aligned_atom_count",
    ):
        with pytest.raises(ValueError, match="complete exact evidence"):
            replace(context, **{field_name: None})
