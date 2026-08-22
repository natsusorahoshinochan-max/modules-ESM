"""Public wire projections for provider-independent scientific values."""

from __future__ import annotations

from datatypes.candidate import CandidateDataReference
from datatypes.exact_reference import ExactContractReference
from datatypes.observation import (
    CalibrationObservationContext,
    IntrinsicObservationContext,
    PairwiseParticipant,
    PairwiseObservationContext,
)


def _candidate_data_reference_to_public(
    value: CandidateDataReference,
) -> dict[str, str]:
    return {
        "candidate_id": value.candidate_id,
        "data_type_id": value.data_type_id,
        "content_digest": value.content_digest,
    }


def _exact_contract_reference_to_public(
    value: ExactContractReference,
) -> dict[str, str]:
    return {
        "contract_kind": value.contract_kind,
        "contract_id": value.contract_id,
        "contract_version": value.contract_version,
        "contract_digest": value.contract_digest,
    }


def _pairwise_participant_to_public(
    value: PairwiseParticipant,
) -> dict[str, object]:
    return {
        "role": value.role,
        "candidate": _candidate_data_reference_to_public(value.candidate),
    }


def encode_observation_context(
    value: (
        IntrinsicObservationContext
        | CalibrationObservationContext
        | PairwiseObservationContext
    ),
) -> dict[str, object]:
    """Encode one admitted context for the public protocol."""
    if type(value) is IntrinsicObservationContext:
        return {"kind": value.kind}
    if type(value) is CalibrationObservationContext:
        return {
            "kind": value.kind,
            "calibration_metric": value.calibration_metric,
            "calibration_value": value.calibration_value,
            "calibration_unit": value.calibration_unit,
            "population_id": value.population_id,
        }
    result: dict[str, object] = {
        "kind": value.kind,
        "subject": _pairwise_participant_to_public(value.subject),
        "reference": _pairwise_participant_to_public(value.reference),
        "pairing_mode": value.pairing_mode,
        "normalization": value.normalization,
    }
    if value.evidence_content_digest is not None:
        result["evidence_content_digest"] = value.evidence_content_digest
    if value.evidence_method is not None:
        result["evidence_method"] = _exact_contract_reference_to_public(
            value.evidence_method
        )
    if value.subject_axis_content_digest is not None:
        result["subject_axis_content_digest"] = (
            value.subject_axis_content_digest
        )
    if value.reference_axis_content_digest is not None:
        result["reference_axis_content_digest"] = (
            value.reference_axis_content_digest
        )
    if value.normalization_length is not None:
        result["normalization_length"] = value.normalization_length
    if value.aligned_atom_count is not None:
        result["aligned_atom_count"] = value.aligned_atom_count
    return result
