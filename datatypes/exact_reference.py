"""Exact provider-independent scientific contract and value references."""

from __future__ import annotations

from dataclasses import dataclass
import re

from datatypes.candidate import CandidateDataReference
from datatypes.identifier import validate_canonical_identifier
from datatypes.residue import ResidueLayout


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

    def __post_init__(self) -> None:
        if (
            type(self.contract_kind) is not str
            or self.contract_kind not in _CONTRACT_KINDS
        ):
            raise ValueError("contract_kind is not a contract kind")
        validate_canonical_identifier(self.contract_id, "contract_id")

    @property
    def key(self) -> tuple[str, str]:
        return (self.contract_kind, self.contract_id)


@dataclass(frozen=True, slots=True)
class ExactPortValueReference:
    """Exact nominal Port contract and content identity of one input value."""

    port_type: ExactContractReference
    content_digest: str

    def __post_init__(self) -> None:
        if (
            type(self.port_type) is not ExactContractReference
            or self.port_type.contract_kind != "port_type"
        ):
            raise TypeError("port_type must be an exact Port Type reference")
        if (
            type(self.content_digest) is not str
            or re.fullmatch(r"sha256:[0-9a-f]{64}", self.content_digest)
            is None
        ):
            raise ValueError(
                "content_digest must be a canonical sha256 digest"
            )

@dataclass(frozen=True, slots=True)
class ResidueAxisReference:
    """Exact scientific residue axis and the input value that owns it."""

    axis_kind: str
    axis_contract: ExactContractReference
    axis_content_digest: str
    source: CandidateDataReference | ExactPortValueReference
    layout: ResidueLayout

    def __post_init__(self) -> None:
        if self.axis_kind not in {"resolved_structure", "prediction_input"}:
            raise ValueError("axis_kind is not a closed scientific axis kind")
        if (
            type(self.axis_contract) is not ExactContractReference
            or self.axis_contract.contract_kind != "port_type"
        ):
            raise TypeError(
                "axis_contract must be an exact Port Type reference"
            )
        if (
            type(self.axis_content_digest) is not str
            or re.fullmatch(
                r"sha256:[0-9a-f]{64}", self.axis_content_digest
            )
            is None
        ):
            raise ValueError(
                "axis_content_digest must be a canonical sha256 digest"
            )
        if type(self.layout) is not ResidueLayout:
            raise TypeError("layout must be an exact ResidueLayout")
        if self.axis_kind == "resolved_structure":
            if (
                type(self.source) is not CandidateDataReference
                or self.source.data_type_id != "protein.structure"
            ):
                raise TypeError(
                    "resolved_structure axis source must be an exact "
                    "structure CandidateDataReference"
                )
        elif type(self.source) not in {
            CandidateDataReference,
            ExactPortValueReference,
        }:
            raise TypeError(
                "prediction_input axis source must be an exact Candidate "
                "or input Port value reference"
            )
