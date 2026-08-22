"""Typed Module Package and stable contract declarations."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
import re
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from .definition_resource import DefinitionResource

from core.operation import (
    OperationContext,
    ReadinessCheckInput,
    ReadinessResult,
    ScientificOperation,
)
from core.parameters.contract import (
    ParameterContractDefinitionError,
    admit_declarations,
)
from core.parameters.model import ParameterContract
from datatypes.exact_reference import (
    ExactContractReference,
    validate_canonical_identifier,
)

from .port_contract import (
    CANDIDATE_COLLECTION_PORT_TYPE_VERSION,
    CANDIDATE_PAIRING_PORT_TYPE_VERSION,
    CONTRACT_NAMESPACE,
    SCORE_COLLECTION_PORT_TYPE_VERSION,
    BehaviorReference,
    CatalogBuildError,
    PortTypeDefinition,
    canonical_json_bytes,
)


MODULE_PACKAGE_SCHEMA_VERSION = "2.1.0"
ContractKind = Literal[
    "binding",
    "method",
    "metric",
    "node_type",
    "port_type",
    "utility_transform",
]
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
_SEMANTIC_VERSION = re.compile(
    r"^[0-9]+\.[0-9]+\.[0-9]+(?:-[0-9A-Za-z.-]+)?$"
)
_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_SCIENTIFIC_COLLECTION_PORT_TYPE_VERSIONS = {
    "candidate.collection": CANDIDATE_COLLECTION_PORT_TYPE_VERSION,
    "score.collection": SCORE_COLLECTION_PORT_TYPE_VERSION,
}


def _require_identifier(value: str, field_name: str) -> None:
    try:
        validate_canonical_identifier(value, field_name)
    except ValueError as error:
        raise CatalogBuildError(
            f"{field_name} must be a versioned identifier"
        ) from error


def _require_version(value: str, field_name: str) -> None:
    if (
        not isinstance(value, str)
        or len(value) > 64
        or _SEMANTIC_VERSION.fullmatch(value) is None
    ):
        raise CatalogBuildError(f"{field_name} must be an exact semantic version")


def _require_schema_version(value: str, resource_kind: str) -> None:
    if value != MODULE_PACKAGE_SCHEMA_VERSION:
        raise CatalogBuildError(
            f"unsupported {resource_kind} schema_version {value!r}; "
            f"expected {MODULE_PACKAGE_SCHEMA_VERSION!r}"
        )


def _freeze_declaration(value: Any, *, path: str = "$") -> Any:
    if isinstance(value, ContractIdentity):
        return value
    if isinstance(value, Mapping):
        frozen: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise CatalogBuildError(f"{path} has a non-string object key")
            frozen[key] = _freeze_declaration(item, path=f"{path}.{key}")
        return MappingProxyType(frozen)
    if isinstance(value, (list, tuple)):
        return tuple(
            _freeze_declaration(item, path=f"{path}[{index}]")
            for index, item in enumerate(value)
        )
    canonical_json_bytes(value)
    return value


def _thaw_declaration(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _thaw_declaration(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw_declaration(item) for item in value]
    return value


def _admit_parameter_declarations(
    declarations: Mapping[str, Any],
    *,
    path: str,
) -> ParameterContract:
    try:
        return admit_declarations(declarations, path=path)
    except ParameterContractDefinitionError as error:
        raise CatalogBuildError(str(error)) from error


@dataclass(frozen=True, slots=True)
class ContractIdentity:
    """An exact unresolved reference to one Catalog contract."""

    contract_kind: ContractKind
    contract_id: str
    contract_version: str
    expected_digest: str | None = None

    def __post_init__(self) -> None:
        if self.contract_kind not in _CONTRACT_KINDS:
            raise CatalogBuildError(
                f"unknown contract kind {self.contract_kind!r}"
            )
        _require_identifier(self.contract_id, "contract_id")
        _require_version(self.contract_version, "contract_version")
        if (
            self.expected_digest is not None
            and _DIGEST.fullmatch(self.expected_digest) is None
        ):
            raise CatalogBuildError(
                "expected_digest must use sha256:<64 lowercase hex>"
            )

    @property
    def key(self) -> tuple[str, str, str]:
        return (
            self.contract_kind,
            self.contract_id,
            self.contract_version,
        )


@dataclass(frozen=True, slots=True)
class NodePortDefinition:
    """One admitted Node input or output Port."""

    name: str
    port_type: ContractIdentity
    required: bool
    multiplicity: Literal["one", "many"]
    scientific_meaning: str
    artifact_kind: Literal["standalone", "candidate"] | None = None
    artifact_media_type: str | None = None

    def descriptor_template(self) -> dict[str, Any]:
        descriptor = {
            "name": self.name,
            "port_type": self.port_type,
            "required": self.required,
            "multiplicity": self.multiplicity,
            "scientific_meaning": self.scientific_meaning,
        }
        if self.artifact_kind is not None:
            descriptor["artifact_kind"] = self.artifact_kind
        if self.artifact_media_type is not None:
            descriptor["artifact_media_type"] = self.artifact_media_type
        return descriptor


@dataclass(frozen=True, slots=True)
class NodeTypeDefinition:
    """One admitted Node Type definition resource."""

    node_type_id: str
    version: str
    title: str
    summary: str
    category: str
    inputs: tuple[NodePortDefinition, ...]
    outputs: tuple[NodePortDefinition, ...]
    input_constraints: tuple[tuple[str, ...], ...]
    parameter_groups: tuple[Any, ...]
    node_parameters: Mapping[str, Any]
    parameter_contract: ParameterContract

    @property
    def identity(self) -> ContractIdentity:
        return ContractIdentity("node_type", self.node_type_id, self.version)

    def descriptor_template(self) -> dict[str, Any]:
        descriptor = {
            "schema_namespace": CONTRACT_NAMESPACE,
            "contract_kind": "node_type",
            "contract_id": self.node_type_id,
            "contract_version": self.version,
            "title": self.title,
            "summary": self.summary,
            "category": self.category,
            "inputs": [port.descriptor_template() for port in self.inputs],
            "outputs": [port.descriptor_template() for port in self.outputs],
            "parameter_groups": self.parameter_groups,
            "node_parameters": self.node_parameters,
        }
        if self.input_constraints:
            descriptor["input_constraints"] = [
                {"kind": "exactly_one", "ports": ports}
                for ports in self.input_constraints
            ]
        return descriptor


@dataclass(frozen=True, slots=True)
class MetricDefinition:
    """One admitted Metric definition resource."""

    metric_id: str
    version: str
    title: str
    description: str
    value_shape: str
    unit: str
    direction: str
    canonical_range: Mapping[str, Any]
    granularity: str
    aggregation_semantics: Mapping[str, Any]
    observation_context_schema: Mapping[str, Any]
    validation_contract: Mapping[str, Any]

    @property
    def identity(self) -> ContractIdentity:
        return ContractIdentity("metric", self.metric_id, self.version)

    def descriptor_template(self) -> dict[str, Any]:
        return {
            "schema_namespace": CONTRACT_NAMESPACE,
            "contract_kind": "metric",
            "contract_id": self.metric_id,
            "contract_version": self.version,
            "title": self.title,
            "description": self.description,
            "value_shape": self.value_shape,
            "unit": self.unit,
            "direction": self.direction,
            "canonical_range": self.canonical_range,
            "granularity": self.granularity,
            "aggregation_semantics": self.aggregation_semantics,
            "observation_context_schema": self.observation_context_schema,
            "validation_contract": self.validation_contract,
        }

    @property
    def requires_residue_axis(self) -> bool:
        if self.value_shape in {
            "per_residue",
            "residue_vector",
            "residue_pair_matrix",
        }:
            return True
        return (
            self.value_shape == "scalar"
            and self.aggregation_semantics.get("kind") not in (None, "none")
            and type(self.aggregation_semantics.get("source_metric")) is str
            and bool(self.aggregation_semantics.get("source_metric"))
        )


@dataclass(frozen=True, slots=True)
class MethodDefinition:
    """Stable scientific Method declaration supplied by one package."""

    method_id: str
    version: str
    algorithm_identity: Mapping[str, Any]
    model_identity: Mapping[str, Any]
    checkpoint_identity: Mapping[str, Any]
    featurization_identity: Mapping[str, Any]
    source_identity: Mapping[str, Any]
    scale_contract: Mapping[str, Any]

    def __post_init__(self) -> None:
        _require_identifier(self.method_id, "method_id")
        _require_version(self.version, "method version")
        for field_name in (
            "algorithm_identity",
            "model_identity",
            "checkpoint_identity",
            "featurization_identity",
            "source_identity",
            "scale_contract",
        ):
            value = getattr(self, field_name)
            if not isinstance(value, Mapping):
                raise CatalogBuildError(f"{field_name} must be an object")
            object.__setattr__(
                self,
                field_name,
                _freeze_declaration(value, path=f"$.{field_name}"),
            )

    @property
    def identity(self) -> ContractIdentity:
        return ContractIdentity("method", self.method_id, self.version)

    def descriptor_template(self) -> dict[str, Any]:
        return {
            "schema_namespace": CONTRACT_NAMESPACE,
            "contract_kind": "method",
            "contract_id": self.method_id,
            "contract_version": self.version,
            "algorithm_identity": self.algorithm_identity,
            "model_identity": self.model_identity,
            "checkpoint_identity": self.checkpoint_identity,
            "featurization_identity": self.featurization_identity,
            "source_identity": self.source_identity,
            "scale_contract": self.scale_contract,
        }


@dataclass(frozen=True, slots=True)
class UtilityTransformDefinition:
    """Controlled versioned mapping to a dimensionless unit interval."""

    transform_id: str
    version: str
    compatible_input_contract: Mapping[str, Any]
    parameters: Mapping[str, Any]
    parameter_contract: ParameterContract = field(init=False, repr=False)
    behavior: BehaviorReference
    transform: Callable[[Any, Mapping[str, Any]], float] = field(
        repr=False,
        compare=False,
    )

    def __post_init__(self) -> None:
        _require_identifier(self.transform_id, "transform_id")
        _require_version(self.version, "Utility Transform version")
        for field_name in ("compatible_input_contract", "parameters"):
            value = getattr(self, field_name)
            if not isinstance(value, Mapping):
                raise CatalogBuildError(f"{field_name} must be an object")
            object.__setattr__(
                self,
                field_name,
                _freeze_declaration(value, path=f"$.{field_name}"),
            )
        object.__setattr__(
            self,
            "parameter_contract",
            _admit_parameter_declarations(
                self.parameters,
                path=f"utility_transform:{self.transform_id}@{self.version}.parameters",
            ),
        )

    @property
    def identity(self) -> ContractIdentity:
        return ContractIdentity(
            "utility_transform",
            self.transform_id,
            self.version,
        )

    def descriptor_template(self) -> dict[str, Any]:
        return {
            "schema_namespace": CONTRACT_NAMESPACE,
            "contract_kind": "utility_transform",
            "contract_id": self.transform_id,
            "contract_version": self.version,
            "compatible_input_contract": self.compatible_input_contract,
            "parameters": self.parameters,
            "behavior": self.behavior.descriptor(),
            "output_contract": {"minimum": 0, "maximum": 1},
        }


@dataclass(frozen=True, slots=True)
class ScientificOperationFactory:
    """Lazy constructor for one typed canonical Scientific Operation."""

    behavior: BehaviorReference
    build: Callable[[OperationContext], ScientificOperation] = field(
        repr=False,
        compare=False,
    )


@dataclass(frozen=True, slots=True)
class EffectiveRandomnessResolver:
    """Private pre-Cache resolver paired with a stable behavior identity."""

    behavior: BehaviorReference
    resolve: Callable[..., Mapping[str, Any]] = field(
        repr=False,
        compare=False,
    )


@dataclass(frozen=True, slots=True)
class AvailabilityResult:
    """One structured startup Availability conclusion."""

    is_available: bool
    code: str | None = None
    message: str | None = None
    retryable: bool | None = None

    @classmethod
    def available(cls) -> AvailabilityResult:
        return cls(True)

    @classmethod
    def unavailable(
        cls,
        code: str,
        message: str,
        *,
        retryable: bool,
    ) -> AvailabilityResult:
        return cls(False, code=code, message=message, retryable=retryable)


@dataclass(frozen=True, slots=True)
class AvailabilityDeclaration:
    """Stable Availability probe declaration and private startup checker."""

    behavior: BehaviorReference
    prerequisites: Mapping[str, Any]
    check: Callable[[], AvailabilityResult] = field(
        repr=False,
        compare=False,
    )

    def __post_init__(self) -> None:
        if not isinstance(self.prerequisites, Mapping):
            raise CatalogBuildError("Availability prerequisites must be an object")
        object.__setattr__(
            self,
            "prerequisites",
            _freeze_declaration(
                self.prerequisites,
                path="$.availability.prerequisites",
            ),
        )

    def descriptor(self) -> dict[str, Any]:
        return {
            "behavior": self.behavior.descriptor(),
            "prerequisites": self.prerequisites,
        }


@dataclass(frozen=True, slots=True)
class ReadinessDeclaration:
    """Stable run-scoped Readiness declaration and private checker."""

    behavior: BehaviorReference
    prerequisites: Mapping[str, Any]
    check: Callable[["ReadinessCheckInput"], "ReadinessResult"] = field(
        repr=False,
        compare=False,
    )

    def __post_init__(self) -> None:
        if not isinstance(self.prerequisites, Mapping):
            raise CatalogBuildError("Readiness prerequisites must be an object")
        object.__setattr__(
            self,
            "prerequisites",
            _freeze_declaration(
                self.prerequisites,
                path="$.readiness.prerequisites",
            ),
        )

    def descriptor(self) -> dict[str, Any]:
        return {
            "behavior": self.behavior.descriptor(),
            "prerequisites": self.prerequisites,
        }


@dataclass(frozen=True, slots=True)
class EnvironmentFieldDeclaration:
    """One admitted configuration field for an exact Binding."""

    name: str
    value_category: Literal[
        "json_value",
        "filesystem_path",
        "credential_handle",
    ]
    required: bool = True

    def __post_init__(self) -> None:
        _require_identifier(self.name, "Environment field name")
        if self.name in {"provider_client", "client_factory"}:
            raise CatalogBuildError(
                "Environment declarations cannot contain caller-owned objects"
            )
        if self.value_category not in {
            "json_value",
            "filesystem_path",
            "credential_handle",
        }:
            raise CatalogBuildError(
                "Environment field value_category is unknown"
            )

    def descriptor(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "value_category": self.value_category,
            "required": self.required,
        }


@dataclass(frozen=True, slots=True)
class ObservationPropagationDefinition:
    """One controlled Score Collection capability propagation operation."""

    mode: Literal["pass_through", "union", "filter"]
    output_port: str
    input_ports: tuple[str, ...]
    filter: Mapping[str, Any] | None = None
    absent_input_policy: Literal["reject", "ignore"] = "reject"
    schema_version: str = "2.1.0"

    def __post_init__(self) -> None:
        _require_schema_version(
            self.schema_version,
            "Observation propagation",
        )
        if self.mode not in {"pass_through", "union", "filter"}:
            raise CatalogBuildError(
                "unknown Observation propagation mode"
            )
        _require_identifier(self.output_port, "output_port")
        input_ports = tuple(self.input_ports)
        if (
            not input_ports
            or any(not isinstance(name, str) for name in input_ports)
            or len(input_ports) != len(set(input_ports))
        ):
            raise CatalogBuildError(
                "Observation propagation input Ports must be unique"
            )
        for input_port in input_ports:
            _require_identifier(input_port, "input_port")
        if (
            self.mode in {"pass_through", "filter"}
            and len(input_ports) != 1
        ):
            raise CatalogBuildError(
                f"{self.mode} Observation propagation requires one input Port"
            )
        if self.mode == "union" and len(input_ports) < 2:
            raise CatalogBuildError(
                "union Observation propagation requires at least two input Ports"
            )
        if self.absent_input_policy not in {"reject", "ignore"}:
            raise CatalogBuildError(
                "unknown Observation propagation absent input policy"
            )
        if (
            self.absent_input_policy == "ignore"
            and self.mode != "union"
        ):
            raise CatalogBuildError(
                "only union Observation propagation may ignore absent inputs"
            )
        if self.mode == "filter":
            if not isinstance(self.filter, Mapping) or not self.filter:
                raise CatalogBuildError(
                    "filter Observation propagation requires an exact filter"
                )
            unknown = set(self.filter) - {
                "source_partition",
                "metric",
                "method",
                "context_profile",
            }
            if unknown:
                raise CatalogBuildError(
                    "Observation propagation filter contains unknown fields"
                )
            source_partition = self.filter.get("source_partition")
            if source_partition is not None:
                _require_identifier(
                    source_partition,
                    "filter source_partition",
                )
            for name, contract_kind in (
                ("metric", "metric"),
                ("method", "method"),
            ):
                reference = self.filter.get(name)
                if (
                    reference is not None
                    and (
                        not isinstance(reference, ContractIdentity)
                        or reference.contract_kind != contract_kind
                    )
                ):
                    raise CatalogBuildError(
                        f"Observation propagation filter {name} must be an "
                        f"exact {contract_kind} contract reference"
                    )
            context_profile = self.filter.get("context_profile")
            if (
                context_profile is not None
                and not isinstance(context_profile, Mapping)
            ):
                raise CatalogBuildError(
                    "Observation propagation filter context_profile must be "
                    "an object"
                )
            frozen_filter = _freeze_declaration(
                self.filter,
                path="$.observation_propagation.filter",
            )
        elif self.filter is not None:
            raise CatalogBuildError(
                "only filter Observation propagation accepts a filter"
            )
        else:
            frozen_filter = None
        object.__setattr__(self, "input_ports", input_ports)
        object.__setattr__(self, "filter", frozen_filter)

    def descriptor_template(self) -> dict[str, Any]:
        descriptor = {
            "schema_version": self.schema_version,
            "mode": self.mode,
            "output_port": self.output_port,
            "input_ports": self.input_ports,
            "filter": self.filter,
        }
        if self.absent_input_policy != "reject":
            descriptor["absent_input_policy"] = self.absent_input_policy
        return descriptor


@dataclass(frozen=True, slots=True)
class SelectionObjectiveConsumptionDefinition:
    """Closed declaration binding a Node to Workflow-owned objectives."""

    candidate_input_port: str
    score_collection_input_port: str
    candidate_output_port: str
    objective_id_parameter: str | None = None
    objective_ids_parameter: str | None = None
    schema_version: str = "2.1.0"

    def __post_init__(self) -> None:
        _require_schema_version(
            self.schema_version,
            "Selection Objective consumption",
        )
        if (self.objective_id_parameter is None) == (
            self.objective_ids_parameter is None
        ):
            raise CatalogBuildError(
                "Selection Objective consumption requires exactly one scalar "
                "or ordered-list selector parameter"
            )
        for field_name in (
            "candidate_input_port",
            "score_collection_input_port",
            "candidate_output_port",
        ):
            _require_identifier(getattr(self, field_name), field_name)
        selector_name = (
            self.objective_id_parameter
            if self.objective_id_parameter is not None
            else self.objective_ids_parameter
        )
        _require_identifier(selector_name, "objective selector parameter")

    def descriptor_template(self) -> dict[str, str]:
        descriptor = {
            "schema_version": self.schema_version,
            "candidate_input_port": self.candidate_input_port,
            "score_collection_input_port": self.score_collection_input_port,
            "candidate_output_port": self.candidate_output_port,
        }
        if self.objective_id_parameter is not None:
            descriptor["objective_id_parameter"] = self.objective_id_parameter
        else:
            descriptor["objective_ids_parameter"] = self.objective_ids_parameter
        return descriptor


@dataclass(frozen=True, slots=True)
class ObservationSelectorConsumptionDefinition:
    """Closed declaration binding a Node to one raw Observation selector."""

    candidate_input_port: str
    score_collection_input_port: str
    candidate_output_port: str
    selector_id_parameter: str
    schema_version: str = "2.1.0"

    def __post_init__(self) -> None:
        _require_schema_version(
            self.schema_version,
            "Observation Selector consumption",
        )
        for field_name in (
            "candidate_input_port",
            "score_collection_input_port",
            "candidate_output_port",
            "selector_id_parameter",
        ):
            _require_identifier(getattr(self, field_name), field_name)

    def descriptor_template(self) -> dict[str, str]:
        return {
            "schema_version": self.schema_version,
            "candidate_input_port": self.candidate_input_port,
            "score_collection_input_port": self.score_collection_input_port,
            "candidate_output_port": self.candidate_output_port,
            "selector_id_parameter": self.selector_id_parameter,
        }


@dataclass(frozen=True, slots=True)
class ProducedObservationDefinition:
    """One closed guaranteed observation emitted by a Binding output."""

    output_port: str
    output_partition: str
    metric: ContractIdentity
    context_profile: Mapping[str, Any]
    subject_grain: str
    source_role: str
    subject_direction: Literal["input", "output"]
    subject_port: str
    guaranteed_multiplicity: Literal[
        "one",
        "one_or_more",
        "zero_or_more",
    ]
    reference_direction: Literal["input", "output"] | None = None
    reference_port: str | None = None
    pairing_direction: Literal["input", "output"] | None = None
    pairing_port: str | None = None
    axis_direction: Literal["input", "output"] | None = None
    axis_port: str | None = None
    method_direction: Literal["input", "output"] | None = None
    method_port: str | None = None

    def __post_init__(self) -> None:
        _require_identifier(self.output_port, "output_port")
        if self.metric.contract_kind != "metric":
            raise CatalogBuildError("Produced Observation must reference a Metric")
        if not isinstance(self.context_profile, Mapping):
            raise CatalogBuildError("context_profile must be an object")
        object.__setattr__(
            self,
            "context_profile",
            _freeze_declaration(
                self.context_profile,
                path="$.produced_observation.context_profile",
            ),
        )
        _require_identifier(self.subject_grain, "subject_grain")
        _require_identifier(self.source_role, "source_role")
        if self.subject_direction not in {"input", "output"}:
            raise CatalogBuildError(
                "Produced Observation subject_direction must be input or output"
            )
        _require_identifier(self.subject_port, "subject_port")
        if self.guaranteed_multiplicity not in {
            "one",
            "one_or_more",
            "zero_or_more",
        }:
            raise CatalogBuildError(
                "unknown Produced Observation guaranteed multiplicity"
            )
        _require_identifier(self.output_partition, "output_partition")
        if (self.reference_direction is None) != (
            self.reference_port is None
        ):
            raise CatalogBuildError(
                "Produced Observation must declare both reference direction "
                "and reference Port"
            )
        if self.reference_direction is not None:
            if self.reference_direction not in {"input", "output"}:
                raise CatalogBuildError(
                    "Produced Observation reference_direction must be input "
                    "or output"
                )
            _require_identifier(self.reference_port, "reference_port")
        context_kind = self.context_profile.get("kind")
        if context_kind == "pairwise" and self.reference_port is None:
            raise CatalogBuildError(
                "pairwise Produced Observation requires an exact reference "
                "Candidate source"
            )
        if context_kind != "pairwise" and self.reference_port is not None:
            raise CatalogBuildError(
                "only pairwise Produced Observations declare a reference source"
            )
        if (self.pairing_direction is None) != (self.pairing_port is None):
            raise CatalogBuildError(
                "Produced Observation must declare both pairing direction and "
                "pairing Port"
            )
        if self.pairing_direction is not None:
            if self.pairing_direction not in {"input", "output"}:
                raise CatalogBuildError(
                    "Produced Observation pairing_direction must be input or "
                    "output"
                )
            _require_identifier(self.pairing_port, "pairing_port")
        pairing_mode = self.context_profile.get("pairing_mode")
        if (
            context_kind == "pairwise"
            and pairing_mode == "per_subject_counterpart"
            and self.pairing_port is None
        ):
            raise CatalogBuildError(
                "per-subject Produced Observation requires an explicit "
                "Candidate pairing source"
            )
        if (
            pairing_mode != "per_subject_counterpart"
            and self.pairing_port is not None
        ):
            raise CatalogBuildError(
                "only per-subject Produced Observations declare a pairing source"
            )
        if (self.axis_direction is None) != (self.axis_port is None):
            raise CatalogBuildError(
                "Produced Observation must declare both axis direction and "
                "axis Port"
            )
        if self.axis_direction is not None:
            if self.axis_direction not in {"input", "output"}:
                raise CatalogBuildError(
                    "Produced Observation axis_direction must be input or output"
                )
            _require_identifier(self.axis_port, "axis_port")
        if (self.method_direction is None) != (self.method_port is None):
            raise CatalogBuildError(
                "Produced Observation must declare both Method direction and "
                "Method Port"
            )
        if self.method_direction is not None:
            if self.method_direction not in {"input", "output"}:
                raise CatalogBuildError(
                    "Produced Observation method_direction must be input or output"
                )
            _require_identifier(self.method_port, "method_port")

    def descriptor_template(self) -> dict[str, Any]:
        return {
            "output_port": self.output_port,
            "output_partition": self.output_partition,
            "metric": self.metric,
            "context_profile": self.context_profile,
            "subject_grain": self.subject_grain,
            "source_role": self.source_role,
            "subject_direction": self.subject_direction,
            "subject_port": self.subject_port,
            "reference_direction": self.reference_direction,
            "reference_port": self.reference_port,
            "pairing_direction": self.pairing_direction,
            "pairing_port": self.pairing_port,
            "axis_direction": self.axis_direction,
            "axis_port": self.axis_port,
            "method_direction": self.method_direction,
            "method_port": self.method_port,
            "guaranteed_multiplicity": self.guaranteed_multiplicity,
        }


@dataclass(frozen=True, slots=True)
class ExecutionBindingDefinition:
    """Executable association between one Node Type and one Method."""

    binding_id: str
    version: str
    node_type: ContractIdentity
    method: ContractIdentity
    binding_parameters: Mapping[str, Any]
    parameter_contract: ParameterContract = field(init=False, repr=False)
    execution_route: Literal["adapter", "direct"]
    factory: ScientificOperationFactory
    availability: AvailabilityDeclaration
    readiness: ReadinessDeclaration
    deterministic: bool
    cacheable: bool
    implementation_identity: Mapping[str, Any]
    produced_observations: tuple[ProducedObservationDefinition, ...] = ()
    adapter_behavior: BehaviorReference | None = None
    observation_propagation: ObservationPropagationDefinition | None = None
    selection_objective_consumption: (
        SelectionObjectiveConsumptionDefinition | None
    ) = None
    observation_selector_consumption: (
        ObservationSelectorConsumptionDefinition | None
    ) = None
    effective_randomness_parameters: tuple[str, ...] = ()
    effective_randomness_resolver: EffectiveRandomnessResolver | None = field(
        default=None,
        repr=False,
        compare=False,
    )
    environment_fields: tuple[EnvironmentFieldDeclaration, ...] = ()

    def __post_init__(self) -> None:
        _require_identifier(self.binding_id, "binding_id")
        _require_version(self.version, "Binding version")
        if self.node_type.contract_kind != "node_type":
            raise CatalogBuildError("Binding node_type must reference a Node Type")
        if self.method.contract_kind != "method":
            raise CatalogBuildError("Binding method must reference a Method")
        if not isinstance(self.binding_parameters, Mapping):
            raise CatalogBuildError("binding_parameters must be an object")
        if self.execution_route not in {"adapter", "direct"}:
            raise CatalogBuildError("execution_route must be adapter or direct")
        if self.execution_route == "adapter" and self.adapter_behavior is None:
            raise CatalogBuildError(
                "adapter route requires an explicit Adapter behavior"
            )
        if self.execution_route == "direct" and self.adapter_behavior is not None:
            raise CatalogBuildError(
                "direct route must not declare an Adapter behavior"
            )
        if not isinstance(self.implementation_identity, Mapping):
            raise CatalogBuildError("implementation_identity must be an object")
        environment_fields = tuple(self.environment_fields)
        if (
            any(
                type(declaration) is not EnvironmentFieldDeclaration
                for declaration in environment_fields
            )
            or len({declaration.name for declaration in environment_fields})
            != len(environment_fields)
        ):
            raise CatalogBuildError(
                "environment_fields must contain unique typed declarations"
            )
        randomness_parameters = tuple(self.effective_randomness_parameters)
        if any(
            not isinstance(parameter, str) or not parameter
            for parameter in randomness_parameters
        ) or len(set(randomness_parameters)) != len(randomness_parameters):
            raise CatalogBuildError(
                "effective_randomness_parameters must contain unique names"
            )
        for parameter in randomness_parameters:
            _require_identifier(
                parameter,
                "effective randomness parameter",
            )
        if (
            self.effective_randomness_resolver is not None
            and not randomness_parameters
        ):
            raise CatalogBuildError(
                "effective randomness resolver requires declared parameters"
            )
        object.__setattr__(
            self,
            "effective_randomness_parameters",
            randomness_parameters,
        )
        object.__setattr__(
            self,
            "environment_fields",
            environment_fields,
        )
        object.__setattr__(
            self,
            "binding_parameters",
            _freeze_declaration(
                self.binding_parameters,
                path="$.binding_parameters",
            ),
        )
        object.__setattr__(
            self,
            "parameter_contract",
            _admit_parameter_declarations(
                self.binding_parameters,
                path=f"binding:{self.binding_id}@{self.version}.binding_parameters",
            ),
        )
        object.__setattr__(
            self,
            "implementation_identity",
            _freeze_declaration(
                self.implementation_identity,
                path="$.implementation_identity",
            ),
        )
        observations = tuple(self.produced_observations)
        if (
            observations
            and self.observation_propagation is not None
        ):
            raise CatalogBuildError(
                "Binding must declare fixed Produced Observations or controlled "
                "Observation propagation, not both"
            )
        if len(
            {
                (
                    observation.output_port,
                    observation.output_partition,
                    observation.metric.key,
                    canonical_json_bytes(
                        _thaw_declaration(observation.context_profile)
                    ),
                )
                for observation in observations
            }
        ) != len(observations):
            raise CatalogBuildError("duplicate Produced Observation declaration")
        object.__setattr__(self, "produced_observations", observations)

    @property
    def identity(self) -> ContractIdentity:
        return ContractIdentity("binding", self.binding_id, self.version)

    def descriptor_template(self) -> dict[str, Any]:
        implementation_identity = {
            key: value
            for key, value in self.implementation_identity.items()
        }
        implementation_identity["factory"] = self.factory.behavior.descriptor()
        if self.adapter_behavior is not None:
            implementation_identity["adapter"] = (
                self.adapter_behavior.descriptor()
            )
        if self.effective_randomness_resolver is not None:
            implementation_identity["effective_randomness_resolver"] = (
                self.effective_randomness_resolver.behavior.descriptor()
            )
        descriptor = {
            "schema_namespace": CONTRACT_NAMESPACE,
            "contract_kind": "binding",
            "contract_id": self.binding_id,
            "contract_version": self.version,
            "node_type": self.node_type,
            "method": self.method,
            "binding_parameters": self.binding_parameters,
            "execution_route": self.execution_route,
            "route_behavior": (
                self.adapter_behavior.descriptor()
                if self.adapter_behavior is not None
                else self.factory.behavior.descriptor()
            ),
            "availability_declaration": self.availability.descriptor(),
            "readiness_declaration": self.readiness.descriptor(),
            "deterministic": self.deterministic,
            "cacheable": self.cacheable,
            "implementation_identity": implementation_identity,
            "produced_observations": [
                observation.descriptor_template()
                for observation in self.produced_observations
            ],
            "observation_propagation": (
                self.observation_propagation.descriptor_template()
                if self.observation_propagation is not None
                else None
            ),
        }
        if self.selection_objective_consumption is not None:
            descriptor["selection_objective_consumption"] = (
                self.selection_objective_consumption.descriptor_template()
            )
        if self.observation_selector_consumption is not None:
            descriptor["observation_selector_consumption"] = (
                self.observation_selector_consumption.descriptor_template()
            )
        if self.effective_randomness_parameters:
            descriptor["effective_randomness_parameters"] = list(
                self.effective_randomness_parameters
            )
        if self.environment_fields:
            descriptor["environment_fields"] = [
                declaration.descriptor()
                for declaration in self.environment_fields
            ]
        return descriptor


CatalogDefinition = (
    NodeTypeDefinition
    | MetricDefinition
    | MethodDefinition
    | UtilityTransformDefinition
    | ExecutionBindingDefinition
)


@dataclass(frozen=True, slots=True)
class ModulePackageRegistration:
    """The one immutable production registration exported by a package."""

    schema_version: str
    package_id: str
    package_version: str
    package_module: str
    node_definitions: tuple[DefinitionResource, ...] = ()
    metric_definitions: tuple[DefinitionResource, ...] = ()
    methods: tuple[MethodDefinition, ...] = ()
    bindings: tuple[ExecutionBindingDefinition, ...] = ()
    port_types: tuple[PortTypeDefinition, ...] = ()
    utility_transforms: tuple[UtilityTransformDefinition, ...] = ()

    def __post_init__(self) -> None:
        _require_schema_version(self.schema_version, "Module Package")
        _require_identifier(self.package_id, "package_id")
        _require_version(self.package_version, "package_version")
        if (
            not isinstance(self.package_module, str)
            or not self.package_module
            or self.package_module.startswith(".")
        ):
            raise CatalogBuildError(
                "package_module must name the registration's import package"
            )
        for field_name in (
            "node_definitions",
            "metric_definitions",
            "methods",
            "bindings",
            "port_types",
            "utility_transforms",
        ):
            object.__setattr__(self, field_name, tuple(getattr(self, field_name)))
