"""Focused constructors for exercising Output Admission internals in tests."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from core.execution.output_admission.candidate_identity import (
    _candidate_values,
    _normalize_candidate_outputs,
)
from core.execution.output_admission.port_values import _admit_fresh_port
from core.operation import AdmittedPort, PortMultiplicity
from core.scoring.observation_plan import (
    CalibrationContextProfile,
    IntrinsicContextProfile,
    ObservationContextProfile,
    ObservationPropagationPlan,
    PairwiseContextProfile,
)
from datatypes.candidate import Candidate


def resolved_context_profile_fixture(
    profile: Mapping[str, Any],
) -> ObservationContextProfile:
    """Translate a Catalog descriptor for fixtures that stand in for Compiler."""
    kind = profile["kind"]
    if kind == "intrinsic":
        return IntrinsicContextProfile()
    if kind == "calibration":
        return CalibrationContextProfile(
            calibration_metric=profile["calibration_metric"],
            calibration_value=profile["calibration_value"],
            calibration_unit=profile["calibration_unit"],
            population_id=profile["population_id"],
        )
    return PairwiseContextProfile(
        subject_role=profile["subject_role"],
        reference_role=profile["reference_role"],
        pairing_mode=profile["pairing_mode"],
        normalization=profile["normalization"],
    )


def admit_fixture_port(
    *,
    port_type: Any,
    multiplicity: PortMultiplicity,
    values: tuple[Any, ...],
    candidate_data_port_types: Mapping[str, Any],
) -> AdmittedPort:
    """Build one real fresh Port admission for a focused fixture."""
    return _admit_fresh_port(
        port_type=port_type,
        multiplicity=multiplicity,
        values=values,
        candidate_data_port_types=candidate_data_port_types,
    )


def normalize_fixture_outputs(
    *,
    node_id: str,
    result_identity: str,
    inputs: Mapping[str, AdmittedPort],
    outputs: Mapping[str, Any],
    candidate_content_digest: Callable[[Candidate], str],
    observation_propagation: ObservationPropagationPlan | None = None,
) -> Mapping[str, Any]:
    """Exercise the identity partition without inventing a production seam."""
    del node_id

    class _FixtureEncodedIdentity:
        def __init__(self, content_digest: str) -> None:
            self.content_digest = content_digest

    candidates_by_data_id = {
        id(candidate.data): candidate
        for output in outputs.values()
        for candidate in _candidate_values(output)
    }

    class _FixtureIdentityEncoder:
        def encode_value(self, *, port_type: object, value: object):
            del port_type
            return _FixtureEncodedIdentity(
                candidate_content_digest(candidates_by_data_id[id(value)])
            )

    normalized = _normalize_candidate_outputs(
        result_identity=result_identity,
        inputs=inputs,
        outputs={
            output_port: (
                tuple(value)
                if isinstance(value, (list, tuple))
                else (value,)
            )
            for output_port, value in outputs.items()
        },
        candidate_data_port_types={
            "protein.sequence": object(),
            "protein.structure": object(),
        },
        identity_encoder=_FixtureIdentityEncoder(),
        observation_propagation=observation_propagation,
    )
    return {
        output_port: (
            list(normalized.values[output_port])
            if isinstance(value, list)
            else normalized.values[output_port]
            if isinstance(value, tuple)
            else normalized.values[output_port][0]
        )
        for output_port, value in outputs.items()
    }
