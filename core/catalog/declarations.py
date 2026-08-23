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
    BindingEnvironment,
    OperationContext,
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

from core.catalog.errors import CatalogBuildError
from .port_contract import (
    CANDIDATE_COLLECTION_PORT_TYPE_VERSION,
    CANDIDATE_PAIRING_PORT_TYPE_VERSION,
    CONTRACT_NAMESPACE,
    SCORE_COLLECTION_PORT_TYPE_VERSION,
    BehaviorReference,
    PortTypeDefinition,
    canonical_json_bytes,
)


DEFINITION_RESOURCE_SCHEMA_VERSION = "2.1.0"
ContractKind = Literal[
    "binding",
    "method",
    "metric",
    "node_type",
    "port_type",
    "utility_transform",
]
_SEMANTIC_VERSION = re.compile(
    r"^[0-9]+\.[0-9]+\.[0-9]+(?:-[0-9A-Za-z.-]+)?$"
)
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
    if value != DEFINITION_RESOURCE_SCHEMA_VERSION:
        raise CatalogBuildError(
            f"unsupported {resource_kind} schema_version {value!r}; "
            f"expected {DEFINITION_RESOURCE_SCHEMA_VERSION!r}"
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
        for field_name in (
            "algorithm_identity",
            "model_identity",
            "checkpoint_identity",
            "featurization_identity",
            "source_identity",
            "scale_contract",
        ):
            value = getattr(self, field_name)
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
        object.__setattr__(
            self,
            "prerequisites",
            _freeze_declaration(self.prerequisites),
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
    check: Callable[["BindingEnvironment"], "ReadinessResult"] = field(
        repr=False,
        compare=False,
    )

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "prerequisites",
            _freeze_declaration(self.prerequisites),
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
        object.__setattr__(self, "input_ports", tuple(self.input_ports))
        if self.filter is not None:
            object.__setattr__(
                self,
                "filter",
                _freeze_declaration(self.filter),
            )

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
        object.__setattr__(
            self,
            "context_profile",
            _freeze_declaration(self.context_profile),
        )

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
    deterministic: bool
    cacheable: bool
    implementation_identity: Mapping[str, Any]
    readiness: ReadinessDeclaration | None = None
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
        object.__setattr__(
            self,
            "effective_randomness_parameters",
            tuple(self.effective_randomness_parameters),
        )
        object.__setattr__(
            self,
            "environment_fields",
            tuple(self.environment_fields),
        )
        object.__setattr__(
            self,
            "binding_parameters",
            _freeze_declaration(self.binding_parameters),
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
            _freeze_declaration(self.implementation_identity),
        )
        object.__setattr__(
            self,
            "produced_observations",
            tuple(self.produced_observations),
        )

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
        if self.readiness is not None:
            descriptor["readiness_declaration"] = self.readiness.descriptor()
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
        for field_name in (
            "node_definitions",
            "metric_definitions",
            "methods",
            "bindings",
            "port_types",
            "utility_transforms",
        ):
            object.__setattr__(self, field_name, tuple(getattr(self, field_name)))
