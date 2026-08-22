"""Canonical admission and restoration of nominal Port values."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import hashlib
from typing import Any

from core.catalog.port_contract import (
    PortValueError,
    _exact_contract_reference_to_canonical,
    canonical_sha256,
)
from core.execution.output_admission.identity import _exact_port_type
from core.operation import AdmittedPort, AdmittedValue, PortMultiplicity
from datatypes.candidate import CandidateDataReference
from datatypes.exact_reference import ExactContractReference, ResidueAxisReference


@dataclass(frozen=True, slots=True)
class _FreshValueProjections:
    """Identity projections already closed during fresh output admission."""

    candidate_data: tuple[CandidateDataReference, ...] | None = None
    scientific_axes: tuple[ResidueAxisReference, ...] | None = None


def _admitted_value(
    *,
    port_type: Any,
    runtime_value: Any,
    canonical_bytes: bytes,
    candidate_data_port_types: Mapping[str, Any],
    projections: _FreshValueProjections | None = None,
) -> AdmittedValue:
    """Project exact scientific facts from one already-validated value."""
    scientific_axes = (
        projections.scientific_axes
        if projections is not None and projections.scientific_axes is not None
        else (
            port_type.scientific_axis_references(runtime_value)
            if port_type.runtime_scientific_axis_projection is not None
            else ()
        )
    )
    references = list(
        projections.candidate_data
        if projections is not None and projections.candidate_data is not None
        else (
            port_type.candidate_data_references(
                runtime_value,
                candidate_data_port_types,
            )
            if port_type.runtime_candidate_data_projection is not None
            else ()
        )
    )
    references.extend(
        axis.source
        for axis in scientific_axes
        if type(axis.source) is CandidateDataReference
    )
    candidate_references: dict[str, CandidateDataReference] = {}
    for reference in references:
        existing = candidate_references.get(reference.candidate_id)
        if existing is not None and existing != reference:
            raise PortValueError(
                "Port admission projected conflicting exact references for "
                "Candidate Data"
            )
        candidate_references[reference.candidate_id] = reference
    return AdmittedValue(
        value=runtime_value,
        canonical_bytes=canonical_bytes,
        content_digest=(
            "sha256:" + hashlib.sha256(canonical_bytes).hexdigest()
        ),
        candidate_data=tuple(candidate_references.values()),
        scientific_axes=scientific_axes,
        observation_methods=(
            port_type.observation_method_references(runtime_value)
            if port_type.runtime_observation_method_projection is not None
            else ()
        ),
    )


def _snapshot(
    *,
    port_type: ExactContractReference,
    multiplicity: PortMultiplicity,
    values: tuple[AdmittedValue, ...],
) -> AdmittedPort:
    if multiplicity == "one" and len(values) != 1:
        raise PortValueError("Port with one multiplicity requires one value")
    content_digest = (
        values[0].content_digest
        if len(values) == 1
        else canonical_sha256(
            {
                "port_type": _exact_contract_reference_to_canonical(
                    port_type
                ),
                "value_content_digests": [
                    value.content_digest for value in values
                ],
            }
        )
    )
    return AdmittedPort(
        port_type=port_type,
        multiplicity=multiplicity,
        values=values,
        content_digest=content_digest,
    )


def _admit_fresh_port(
    *,
    port_type: Any,
    multiplicity: PortMultiplicity,
    values: tuple[Any, ...],
    candidate_data_port_types: Mapping[str, Any],
    projections: tuple[_FreshValueProjections | None, ...] | None = None,
) -> AdmittedPort:
    """Encode each fresh value once and retain its original runtime value."""
    value_projections = (
        projections
        if projections is not None
        else tuple(None for _value in values)
    )
    admitted = tuple(
        _admitted_value(
            port_type=port_type,
            runtime_value=value,
            canonical_bytes=port_type.encode(value),
            candidate_data_port_types=candidate_data_port_types,
            projections=projection,
        )
        for value, projection in zip(values, value_projections, strict=True)
    )
    return _snapshot(
        port_type=_exact_port_type(port_type),
        multiplicity=multiplicity,
        values=admitted,
    )


def restore_admitted_port(
    *,
    port_type: Any,
    multiplicity: PortMultiplicity,
    canonical_values: tuple[bytes, ...],
    candidate_data_port_types: Mapping[str, Any],
) -> AdmittedPort:
    """Restore one persisted Port through its nominal decoder exactly once."""
    admitted = tuple(
        _admitted_value(
            port_type=port_type,
            runtime_value=port_type.decode(canonical_value),
            canonical_bytes=canonical_value,
            candidate_data_port_types=candidate_data_port_types,
        )
        for canonical_value in canonical_values
    )
    return _snapshot(
        port_type=_exact_port_type(port_type),
        multiplicity=multiplicity,
        values=admitted,
    )


def combine_admitted_port(
    *,
    port_type: ExactContractReference,
    multiplicity: PortMultiplicity,
    values: tuple[AdmittedValue, ...],
) -> AdmittedPort:
    """Combine already-admitted edge values without repeating admission."""
    return _snapshot(
        port_type=port_type,
        multiplicity=multiplicity,
        values=values,
    )
