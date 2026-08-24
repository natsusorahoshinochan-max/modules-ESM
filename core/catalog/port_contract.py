"""Nominal Port contracts, canonical codecs, and artifact media grammar."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
import hashlib
import re
from types import MappingProxyType
from typing import Any, Callable, cast

from core.catalog import _port_value_codec as _value_codec
from core.catalog import canonical as _canonical
from core.catalog import errors as _errors
from core.operation import EncodedOutputIdentities, ResolvedOutputIdentity
from datatypes.candidate import CandidateDataReference
from datatypes.exact_reference import (
    ExactContractReference,
    ExactPortValueReference,
    ResidueAxisReference,
)
from datatypes.identifier import validate_canonical_identifier
from datatypes.i_json import thaw_i_json
from datatypes.observation import (
    CalibrationObservationContext,
    IntrinsicObservationContext,
    PairwiseObservationContext,
    PairwiseParticipant,
)
from datatypes.residue import ResidueLayout


_MEDIA_TYPE = re.compile(r"^[^\s/]+/[^\s/]+$")


def is_valid_artifact_media_type(value: object) -> bool:
    """Return whether a value uses the public type/subtype media grammar."""
    return (
        isinstance(value, str)
        and len(value) <= 256
        and _MEDIA_TYPE.fullmatch(value) is not None
    )


def _candidate_data_reference_to_canonical(
    value: CandidateDataReference,
) -> dict[str, str]:
    return {
        "candidate_id": value.candidate_id,
        "data_type_id": value.data_type_id,
        "content_digest": value.content_digest,
    }


def _candidate_data_reference_from_canonical(
    value: object,
) -> CandidateDataReference:
    exact_fields = {
        "candidate_id",
        "data_type_id",
        "content_digest",
    }
    if not isinstance(value, Mapping) or set(value) != exact_fields:
        raise ValueError(
            "CandidateDataReference canonical value must contain exact fields"
        )
    return CandidateDataReference(
        candidate_id=cast(str, value["candidate_id"]),
        data_type_id=cast(str, value["data_type_id"]),
        content_digest=cast(str, value["content_digest"]),
    )


def _exact_contract_reference_to_canonical(
    value: ExactContractReference,
) -> dict[str, str]:
    return {
        "contract_kind": value.contract_kind,
        "contract_id": value.contract_id,
        "contract_version": value.contract_version,
        "contract_digest": value.contract_digest,
    }


def _exact_port_value_reference_to_canonical(
    value: ExactPortValueReference,
) -> dict[str, object]:
    return {
        "port_type": _exact_contract_reference_to_canonical(value.port_type),
        "content_digest": value.content_digest,
    }


def _residue_axis_reference_to_canonical(
    value: ResidueAxisReference,
) -> dict[str, object]:
    if type(value.source) is CandidateDataReference:
        source_kind = "candidate_data"
        source = _candidate_data_reference_to_canonical(value.source)
    else:
        source_kind = "port_value"
        source = _exact_port_value_reference_to_canonical(value.source)
    return {
        "axis_kind": value.axis_kind,
        "axis_contract": _exact_contract_reference_to_canonical(
            value.axis_contract
        ),
        "axis_content_digest": value.axis_content_digest,
        "source": {
            "kind": source_kind,
            "reference": source,
        },
        "layout": {
            "chain_id": value.layout.chain_id,
            "length": value.layout.length,
            "residue_ids": value.layout.residue_ids,
        },
    }


def _pairwise_participant_to_canonical(
    value: PairwiseParticipant,
) -> dict[str, object]:
    return {
        "role": value.role,
        "candidate": _candidate_data_reference_to_canonical(value.candidate),
    }


def observation_context_canonical(
    value: (
        IntrinsicObservationContext
        | CalibrationObservationContext
        | PairwiseObservationContext
    ),
) -> dict[str, object]:
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
        "subject": _pairwise_participant_to_canonical(value.subject),
        "reference": _pairwise_participant_to_canonical(value.reference),
        "pairing_mode": value.pairing_mode,
        "normalization": value.normalization,
    }
    if value.evidence_content_digest is not None:
        result["evidence_content_digest"] = value.evidence_content_digest
    if value.evidence_method is not None:
        result["evidence_method"] = _exact_contract_reference_to_canonical(
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


CONTRACT_NAMESPACE = "protein-workbench-contract/v2"
CATALOG_NAMESPACE = "protein-workbench-catalog/v2"
PORT_VALUE_NAMESPACE = "protein-workbench-port-value/v2"
PORT_TYPE_VERSION = "2.1.0"
CANDIDATE_COLLECTION_PORT_TYPE_VERSION = "4.0.0"
CANDIDATE_PAIRING_PORT_TYPE_VERSION = "4.0.0"
SCORE_COLLECTION_PORT_TYPE_VERSION = "5.0.0"
PROTEIN_SEQUENCE_PORT_TYPE_VERSION = "3.0.0"
PROTEIN_STRUCTURE_PORT_TYPE_VERSION = "4.0.0"
RESIDUE_LAYOUT_PORT_TYPE_VERSION = "3.0.0"
RESIDUE_MAP_PORT_TYPE_VERSION = "3.0.0"
_BUILTIN_PORT_TYPE_VERSIONS = {
    "candidate.collection": CANDIDATE_COLLECTION_PORT_TYPE_VERSION,
    "candidate.pairing": CANDIDATE_PAIRING_PORT_TYPE_VERSION,
    "protein.sequence": PROTEIN_SEQUENCE_PORT_TYPE_VERSION,
    "protein.structure": PROTEIN_STRUCTURE_PORT_TYPE_VERSION,
    "residue.layout": RESIDUE_LAYOUT_PORT_TYPE_VERSION,
    "residue.map": RESIDUE_MAP_PORT_TYPE_VERSION,
    "score.collection": SCORE_COLLECTION_PORT_TYPE_VERSION,
}
_SEMANTIC_VERSION = re.compile(
    r"^[0-9]+\.[0-9]+\.[0-9]+(?:-[0-9A-Za-z.-]+)?$"
)


def _require_single_active_contract_version(
    identities: Iterable[tuple[str, str, str]],
) -> None:
    active_versions: dict[tuple[str, str], str] = {}
    for contract_kind, contract_id, contract_version in identities:
        logical_identity = (contract_kind, contract_id)
        active_version = active_versions.get(logical_identity)
        if active_version is not None and active_version != contract_version:
            raise _errors.CatalogBuildError(
                "multiple active versions for contract "
                f"{contract_kind}:{contract_id}: "
                f"{active_version} and {contract_version}"
            )
        active_versions[logical_identity] = contract_version


def _validate_identifier(value: str, field_name: str) -> None:
    try:
        validate_canonical_identifier(value, field_name)
    except ValueError as error:
        raise _errors.CatalogBuildError(
            f"{field_name} must be a versioned identifier"
        ) from error


def _validate_version(value: str, field_name: str) -> None:
    if (
        not isinstance(value, str)
        or not 5 <= len(value) <= 64
        or _SEMANTIC_VERSION.fullmatch(value) is None
    ):
        raise _errors.CatalogBuildError(
            f"{field_name} must be an exact semantic version"
        )


@dataclass(frozen=True, slots=True)
class BehaviorReference:
    """Stable public identity for one private runtime behavior."""

    behavior_id: str
    behavior_version: str
    parameters: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _validate_identifier(self.behavior_id, "behavior_id")
        _validate_version(self.behavior_version, "behavior_version")
        parameters = dict(self.parameters)
        _canonical.canonical_json_bytes(parameters)
        object.__setattr__(self, "parameters", _canonical._freeze(parameters))

    def descriptor(self) -> dict[str, Any]:
        """Return the closed public declaration without a Python callable."""
        return {
            "behavior_id": self.behavior_id,
            "behavior_version": self.behavior_version,
            "parameters": thaw_i_json(self.parameters),
        }


@dataclass(frozen=True, slots=True)
class PortTypeDefinition:
    """One exact nominal Port Type and its stable behavior declarations."""

    type_id: str
    version: str
    validator: BehaviorReference
    codec: BehaviorReference
    content_identity: BehaviorReference
    runtime_validator: Callable[[Any], None] | None = field(
        default=None,
        repr=False,
        compare=False,
    )
    runtime_to_wire: Callable[[Any], Any] | None = field(
        default=None,
        repr=False,
        compare=False,
    )
    runtime_from_wire: Callable[[Any], Any] | None = field(
        default=None,
        repr=False,
        compare=False,
    )
    output_identity_materialization: BehaviorReference | None = None
    runtime_output_identity_materializer: Callable[
        [object, EncodedOutputIdentities],
        ResolvedOutputIdentity,
    ] | None = field(
        default=None,
        repr=False,
        compare=False,
    )
    output_identity_source_port_types: Mapping[
        str,
        "PortTypeDefinition",
    ] = field(
        default_factory=dict,
        repr=False,
        compare=False,
    )
    candidate_data_projection: BehaviorReference | None = None
    runtime_candidate_data_projection: Callable[
        [Any, Mapping[str, "PortTypeDefinition"]],
        tuple[CandidateDataReference, ...],
    ] | None = field(
        default=None,
        repr=False,
        compare=False,
    )
    scientific_axis_projection: BehaviorReference | None = None
    runtime_scientific_axis_projection: Callable[
        [Any], tuple[ResidueAxisReference, ...]
    ] | None = field(
        default=None,
        repr=False,
        compare=False,
    )
    observation_method_projection: BehaviorReference | None = None
    runtime_observation_method_projection: Callable[
        [Any], tuple[ExactContractReference, ...]
    ] | None = field(
        default=None,
        repr=False,
        compare=False,
    )
    _canonical_descriptor: Mapping[str, Any] = field(
        init=False,
        repr=False,
        compare=False,
    )

    def __post_init__(self) -> None:
        _validate_identifier(self.type_id, "type_id")
        _validate_version(self.version, "version")
        source_port_types = dict(self.output_identity_source_port_types)
        for source_role, source_port_type in source_port_types.items():
            _validate_identifier(source_role, "output identity source role")
            if type(source_port_type) is not PortTypeDefinition:
                raise _errors.CatalogBuildError(
                    "output identity source roles require exact Port Types"
                )
        object.__setattr__(
            self,
            "output_identity_source_port_types",
            MappingProxyType(source_port_types),
        )
        if (self.output_identity_materialization is None) != (
            self.runtime_output_identity_materializer is None
        ):
            raise _errors.CatalogBuildError(
                "output identity materialization declaration and runtime must "
                "be provided together"
            )
        if (self.output_identity_materialization is None) != (
            not source_port_types
        ):
            raise _errors.CatalogBuildError(
                "output identity materialization requires exact source Port "
                "roles"
            )
        if (
            self.output_identity_materialization is not None
            and self.validator.parameters.get(
                "output_identity_materialization"
            )
            != self.output_identity_materialization.descriptor()
        ):
            raise _errors.CatalogBuildError(
                "output identity materialization must be declared by the "
                "Port validator behavior"
            )
        if (
            self.output_identity_materialization is not None
            and self.output_identity_materialization.parameters.get(
                "source_roles"
            )
            != {
                source_role: source_port_type.reference()
                for source_role, source_port_type in source_port_types.items()
            }
        ):
            raise _errors.CatalogBuildError(
                "output identity source roles must declare exact Port references"
            )
        if (self.candidate_data_projection is None) != (
            self.runtime_candidate_data_projection is None
        ):
            raise _errors.CatalogBuildError(
                "candidate_data_projection declaration and runtime must be "
                "provided together"
            )
        if (self.scientific_axis_projection is None) != (
            self.runtime_scientific_axis_projection is None
        ):
            raise _errors.CatalogBuildError(
                "scientific_axis_projection declaration and runtime must be "
                "provided together"
            )
        if (self.observation_method_projection is None) != (
            self.runtime_observation_method_projection is None
        ):
            raise _errors.CatalogBuildError(
                "observation_method_projection declaration and runtime must "
                "be provided together"
            )
        descriptor = self._build_descriptor()
        _canonical.canonical_json_bytes(descriptor)
        object.__setattr__(
            self,
            "_canonical_descriptor",
            _canonical._freeze(descriptor),
        )

    def _build_descriptor(self) -> dict[str, Any]:
        descriptor = {
            "schema_namespace": CONTRACT_NAMESPACE,
            "contract_kind": "port_type",
            "contract_id": self.type_id,
            "contract_version": self.version,
            "validator": self.validator.descriptor(),
            "codec": self.codec.descriptor(),
            "content_identity": self.content_identity.descriptor(),
        }
        if self.candidate_data_projection is not None:
            descriptor["candidate_data_projection"] = (
                self.candidate_data_projection.descriptor()
            )
        if self.scientific_axis_projection is not None:
            descriptor["scientific_axis_projection"] = (
                self.scientific_axis_projection.descriptor()
            )
        if self.observation_method_projection is not None:
            descriptor["observation_method_projection"] = (
                self.observation_method_projection.descriptor()
            )
        return descriptor

    @property
    def canonical_descriptor(self) -> Mapping[str, Any]:
        """Return the immutable scientific descriptor owned by Catalog."""
        return self._canonical_descriptor

    def descriptor(self) -> dict[str, Any]:
        """Copy the canonical scientific descriptor into JSON containers."""
        return cast(dict[str, Any], thaw_i_json(self._canonical_descriptor))

    @property
    def artifact_media_types(self) -> tuple[str, ...] | None:
        """Return the exact media contract for generic artifact publication."""
        declaration = self.validator.parameters.get("artifact_publication")
        if declaration is None:
            return None
        return cast(tuple[str, ...], declaration["media_types"])

    @property
    def descriptor_bytes(self) -> bytes:
        """RFC 8785 canonical UTF-8 descriptor bytes."""
        return _canonical.canonical_json_bytes(self._canonical_descriptor)

    @property
    def contract_digest(self) -> str:
        """SHA-256 identity of this exact canonical descriptor."""
        return f"sha256:{hashlib.sha256(self.descriptor_bytes).hexdigest()}"

    def reference(self) -> dict[str, Any]:
        """Return the exact reference shape shared by every Catalog contract."""
        return {
            "contract_kind": "port_type",
            "contract_id": self.type_id,
            "contract_version": self.version,
            "contract_digest": self.contract_digest,
        }

    def scientific_axis_references(
        self,
        value: Any,
    ) -> tuple[ResidueAxisReference, ...]:
        """Project nested scalar axes using the nominal Port owner's codec."""
        return cast(
            Callable[[Any], tuple[ResidueAxisReference, ...]],
            self.runtime_scientific_axis_projection,
        )(value)

    def candidate_data_references(
        self,
        value: Any,
        candidate_data_port_types: Mapping[str, "PortTypeDefinition"],
    ) -> tuple[CandidateDataReference, ...]:
        """Project exact Candidate data identities using the nominal owner."""
        return cast(
            Callable[
                [Any, Mapping[str, "PortTypeDefinition"]],
                tuple[CandidateDataReference, ...],
            ],
            self.runtime_candidate_data_projection,
        )(value, candidate_data_port_types)

    def observation_method_references(
        self,
        value: Any,
    ) -> tuple[ExactContractReference, ...]:
        """Project exact provider Methods using the nominal Port owner."""
        return cast(
            Callable[[Any], tuple[ExactContractReference, ...]],
            self.runtime_observation_method_projection,
        )(value)

    def materialize_output_identity(
        self,
        relation: object,
        identities: EncodedOutputIdentities,
    ) -> ResolvedOutputIdentity:
        """Resolve one data-only fresh identity relation for this Port."""
        materializer = self.runtime_output_identity_materializer
        if materializer is None:
            raise _errors.PortValueError(
                f"Port Type {self.type_id}@{self.version} does not own output "
                "identity materialization"
            )
        return materializer(relation, identities)

    def validate_runtime_contract(self) -> None:
        """Require a complete installed runtime behind stable behavior IDs."""
        custom_behaviors = (
            self.runtime_validator,
            self.runtime_to_wire,
            self.runtime_from_wire,
        )
        if any(behavior is not None for behavior in custom_behaviors):
            if not all(behavior is not None for behavior in custom_behaviors):
                raise _errors.CatalogBuildError(
                    f"{self.type_id}@{self.version} has an incomplete runtime "
                    "validator/codec declaration"
                )
        else:
            value_kind = self.validator.parameters.get(
                "accepted_value_kind"
            )
            if (
                not isinstance(value_kind, str)
                or value_kind not in _value_codec._VALUE_TYPE_BY_KIND
            ):
                raise _errors.CatalogBuildError(
                    f"{self.type_id}@{self.version} has no installed "
                    "validator behavior"
                )

    def validate(self, value: Any) -> None:
        """Validate one complete runtime value through this nominal contract."""
        if self.runtime_validator is not None:
            try:
                self.runtime_validator(value)
            except _errors.PortValueError:
                raise
            except (TypeError, ValueError) as error:
                raise _errors.PortValueError(
                    f"{self.type_id}@{self.version} rejected its runtime value: "
                    f"{error}"
                ) from error
            return
        value_kind = cast(
            str,
            self.validator.parameters["accepted_value_kind"],
        )
        expected_type = _value_codec._VALUE_TYPE_BY_KIND[value_kind]
        if type(value) is not expected_type:
            raise _errors.PortValueError(
                f"{self.type_id}@{self.version} requires {expected_type.__name__}, "
                f"got {type(value).__name__}"
            )
        _value_codec._validate_builtin_semantics(value_kind, value)

    def to_wire(self, value: Any) -> Any:
        """Project one already-admitted value into its nested wire form."""
        if self.runtime_to_wire is not None:
            return self.runtime_to_wire(value)
        return _value_codec._value_to_wire(value)

    def encode(self, value: Any) -> bytes:
        """Validate and encode one value as canonical RFC 8785 UTF-8 bytes."""
        self.validate(value)
        wire_value = self.to_wire(value)
        try:
            return _canonical.canonical_json_bytes(
                {
                    "schema_namespace": PORT_VALUE_NAMESPACE,
                    "port_type_id": self.type_id,
                    "port_type_version": self.version,
                    "value": wire_value,
                }
            )
        except _errors.CatalogBuildError as error:
            raise _errors.PortValueError(str(error)) from error

    def from_wire(self, wire_value: Any) -> Any:
        """Admit one nested wire value through its nominal decoder."""
        if self.runtime_from_wire is not None:
            try:
                value = self.runtime_from_wire(wire_value)
            except _errors.PortValueError:
                raise
            except (KeyError, TypeError, ValueError) as error:
                raise _errors.PortValueError(
                    f"{self.type_id}@{self.version} could not decode its value: "
                    f"{error}"
                ) from error
        else:
            value = _value_codec._wire_to_value(wire_value)
        self.validate(value)
        return value

    def decode(self, encoded: bytes) -> Any:
        """Decode canonical bytes, rejecting malformed or non-canonical input."""
        payload = _value_codec._parse_canonical_json(encoded)
        if not isinstance(payload, dict) or set(payload) != {
            "schema_namespace",
            "port_type_id",
            "port_type_version",
            "value",
        }:
            raise _errors.PortValueError("canonical Port value envelope is not closed")
        if payload["schema_namespace"] != PORT_VALUE_NAMESPACE:
            raise _errors.PortValueError(
                "canonical Port value namespace does not match"
            )
        if (
            payload["port_type_id"],
            payload["port_type_version"],
        ) != (self.type_id, self.version):
            raise _errors.PortValueError(
                "canonical Port value nominal identity does not match"
            )
        return self.from_wire(payload["value"])

    def content_digest(self, value: Any) -> str:
        """Identify validated content by SHA-256 of canonical codec bytes."""
        return f"sha256:{hashlib.sha256(self.encode(value)).hexdigest()}"
