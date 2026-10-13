"""Exact provider-independent scientific contract and value references."""

from __future__ import annotations

from dataclasses import dataclass
import re

from datatypes.candidate import CandidateDataReference, validate_candidate_data_reference
from datatypes.identifier import validate_canonical_identifier
from datatypes.residue import ResidueLayout, validate_residue_layout


_CONTRACT_KINDS = frozenset(
    {
        "binding",
        "method",
        "metric",
        "node_type",
        "port_type",
        "utility_transform",
    }
)
@dataclass(frozen=True, slots=True)
class ExactContractReference:
    """Stable scientific contract identity carried by typed values."""

    contract_kind: str
    contract_id: str


    @property
    def key(self) -> tuple[str, str]:
        return (self.contract_kind, self.contract_id)


@dataclass(frozen=True, slots=True)
class ExactPortValueReference:
    """Exact nominal Port contract and content identity of one input value."""

    port_type: ExactContractReference
    content_digest: str


@dataclass(frozen=True, slots=True)
class ResidueAxisReference:
    """Exact scientific residue axis and the input value that owns it."""

    axis_kind: str
    axis_contract: ExactContractReference
    axis_content_digest: str
    source: CandidateDataReference | ExactPortValueReference
    layout: ResidueLayout



def validate_exact_contract_reference(value: object) -> None:
    """Admit an exact reference at its containing scientific owner."""
    if type(value) is not ExactContractReference:
        raise TypeError("value must be an exact ExactContractReference")
    if (
        type(value.contract_kind) is not str
        or value.contract_kind not in _CONTRACT_KINDS
    ):
        raise ValueError("contract_kind is not a contract kind")
    validate_canonical_identifier(value.contract_id, "contract_id")

def validate_exact_port_value_reference(value: object) -> None:
    """Admit an exact reference at its containing scientific owner."""
    if type(value) is not ExactPortValueReference:
        raise TypeError("value must be an exact ExactPortValueReference")
    if (
        type(value.port_type) is not ExactContractReference
        or value.port_type.contract_kind != "port_type"
    ):
        raise TypeError("port_type must be an exact Port Type reference")
    validate_exact_contract_reference(value.port_type)
    if (
        type(value.content_digest) is not str
        or re.fullmatch(r"sha256:[0-9a-f]{64}", value.content_digest)
        is None
    ):
        raise ValueError(
            "content_digest must be a canonical sha256 digest"
        )

def validate_residue_axis_reference(value: object) -> None:
    """Admit an exact reference at its containing scientific owner."""
    if type(value) is not ResidueAxisReference:
        raise TypeError("value must be an exact ResidueAxisReference")
    if value.axis_kind not in {"resolved_structure", "prediction_input"}:
        raise ValueError("axis_kind is not a closed scientific axis kind")
    if (
        type(value.axis_contract) is not ExactContractReference
        or value.axis_contract.contract_kind != "port_type"
    ):
        raise TypeError(
            "axis_contract must be an exact Port Type reference"
        )
    if (
        type(value.axis_content_digest) is not str
        or re.fullmatch(
            r"sha256:[0-9a-f]{64}", value.axis_content_digest
        )
        is None
    ):
        raise ValueError(
            "axis_content_digest must be a canonical sha256 digest"
        )
    if type(value.layout) is not ResidueLayout:
        raise TypeError("layout must be an exact ResidueLayout")
    validate_exact_contract_reference(value.axis_contract)
    validate_residue_layout(value.layout)
    if type(value.source) is CandidateDataReference:
        validate_candidate_data_reference(value.source)
    else:
        validate_exact_port_value_reference(value.source)
    if value.axis_kind == "resolved_structure":
        if (
            type(value.source) is not CandidateDataReference
            or value.source.data_type_id != "protein.structure"
        ):
            raise TypeError(
                "resolved_structure axis source must be an exact "
                "structure CandidateDataReference"
            )
    elif type(value.source) not in {
        CandidateDataReference,
        ExactPortValueReference,
    }:
        raise TypeError(
            "prediction_input axis source must be an exact Candidate "
            "or input Port value reference"
        )
