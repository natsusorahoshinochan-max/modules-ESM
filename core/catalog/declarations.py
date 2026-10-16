"""Typed Module Package and stable contract declarations."""

from __future__ import annotations

from core.catalog.preview import ValuePreviewDefinition
from core.catalog.result_adoption import ResultSourceDefinition

from .ui import ModuleUiDefinition, NodeEditorDefinition, ResultViewerDefinition

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from .authoring import AuthoringCapabilityDefinition
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
)
from datatypes.identifier import validate_canonical_identifier

from core.catalog.result_actions import ResultActionDefinition
from core.catalog.authoring_actions import AuthoringActionDefinition
from core.catalog.result_reading import ResultReaderDefinition
from core.catalog.errors import CatalogBuildError
from core.catalog.observation import ProducedObservation, ObservationPropagation
from datatypes.observation import observation_context_profile_descriptor
from datatypes.i_json import validate_i_json
from .port_contract import (
    CONTRACT_NAMESPACE,
    BehaviorReference,
    PortTypeDefinition,
)


ContractKind = Literal[
    "binding",
    "method",
    "metric",
    "node_type",
    "port_type",
    "utility_transform",
]
def _require_identifier(value: str, field_name: str) -> None:
    try:
        validate_canonical_identifier(value, field_name)
    except ValueError as error:
        raise CatalogBuildError(
            f"{field_name} must be a canonical identifier"
        ) from error


def _admit_declaration(value: Any, *, path: str = "$") -> Any:
    if isinstance(value, ExactContractReference):
        return value
    if isinstance(value, Mapping):
        frozen: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise CatalogBuildError(f"{path} has a non-string object key")
            try:
                validate_i_json(key, path=f"{path}.<key>")
            except ValueError as error:
                raise CatalogBuildError(str(error)) from error
            frozen[key] = _admit_declaration(item, path=f"{path}.{key}")
        return MappingProxyType(frozen)
    if isinstance(value, (list, tuple)):
        return tuple(
            _admit_declaration(item, path=f"{path}[{index}]")
            for index, item in enumerate(value)
        )
    try:
        validate_i_json(value, path=path)
    except ValueError as error:
        raise CatalogBuildError(str(error)) from error
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
class NodePortDefinition:
    """One admitted Node input or output Port."""

    name: str
    port_type: ExactContractReference
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
    title: str
    summary: str
    category: str
    inputs: tuple[NodePortDefinition, ...]
    outputs: tuple[NodePortDefinition, ...]
    input_constraints: tuple[tuple[str, ...], ...]
    parameter_groups: tuple[Any, ...]
    node_parameters: Mapping[str, Any]
    parameter_contract: ParameterContract
    restored_output_port: str | None = None

    @property
    def identity(self) -> ExactContractReference:
        return ExactContractReference("node_type", self.node_type_id)

    def descriptor_template(self) -> dict[str, Any]:
        descriptor = {
            "schema_namespace": CONTRACT_NAMESPACE,
            "contract_kind": "node_type",
            "contract_id": self.node_type_id,
            "title": self.title,
            "summary": self.summary,
            "category": self.category,
            "inputs": [port.descriptor_template() for port in self.inputs],
            "outputs": [port.descriptor_template() for port in self.outputs],
            "parameter_groups": self.parameter_groups,
            "node_parameters": self.node_parameters,
        }
        if self.restored_output_port is not None:
            descriptor["restored_output_port"] = self.restored_output_port
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
    def identity(self) -> ExactContractReference:
        return ExactContractReference("metric", self.metric_id)

    def descriptor_template(self) -> dict[str, Any]:
        return {
            "schema_namespace": CONTRACT_NAMESPACE,
            "contract_kind": "metric",
            "contract_id": self.metric_id,
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
    algorithm_identity: Mapping[str, Any]
    model_identity: Mapping[str, Any]
    featurization_identity: Mapping[str, Any]
    scale_contract: Mapping[str, Any]

    def __post_init__(self) -> None:
        for field_name in (
            "algorithm_identity",
            "model_identity",
            "featurization_identity",
            "scale_contract",
        ):
            value = getattr(self, field_name)
            object.__setattr__(
                self,
                field_name,
                _admit_declaration(value, path=f"$.{field_name}"),
            )

    @property
    def identity(self) -> ExactContractReference:
        return ExactContractReference("method", self.method_id)

    def descriptor_template(self) -> dict[str, Any]:
        return {
            "schema_namespace": CONTRACT_NAMESPACE,
            "contract_kind": "method",
            "contract_id": self.method_id,
            "algorithm_identity": self.algorithm_identity,
            "model_identity": self.model_identity,
            "featurization_identity": self.featurization_identity,
            "scale_contract": self.scale_contract,
        }


@dataclass(frozen=True, slots=True)
class UtilityTransformDefinition:
    """Controlled mapping to a dimensionless unit interval."""

    transform_id: str
    title: str
    meaning: str
    applicability: str
    limitations: tuple[str, ...]
    compatible_input_contract: Mapping[str, Any]
    parameters: Mapping[str, Any]
    parameter_contract: ParameterContract = field(init=False, repr=False)
    behavior: BehaviorReference
    transform: Callable[[Any, Mapping[str, Any]], float] = field(
        repr=False,
        compare=False,
    )

    def __post_init__(self) -> None:
        for name in ("title", "meaning", "applicability"):
            if not isinstance(getattr(self, name), str) or not getattr(self, name).strip():
                raise CatalogBuildError(f"Utility Transform {name} must be nonempty text")
        if not self.limitations or any(not isinstance(item, str) or not item.strip() for item in self.limitations):
            raise CatalogBuildError("Utility Transform limitations must contain nonempty text")
        object.__setattr__(self, "limitations", tuple(self.limitations))
        for field_name in ("compatible_input_contract", "parameters"):
            value = getattr(self, field_name)
            if not isinstance(value, Mapping):
                raise CatalogBuildError(f"{field_name} must be an object")
            object.__setattr__(
                self,
                field_name,
                _admit_declaration(value, path=f"$.{field_name}"),
            )
        object.__setattr__(
            self,
            "parameter_contract",
            _admit_parameter_declarations(
                self.parameters,
                path=f"utility_transform:{self.transform_id}.parameters",
            ),
        )

    @property
    def identity(self) -> ExactContractReference:
        return ExactContractReference(
            "utility_transform",
            self.transform_id,
        )

    def descriptor_template(self) -> dict[str, Any]:
        return {
            "schema_namespace": CONTRACT_NAMESPACE,
            "contract_kind": "utility_transform",
            "contract_id": self.transform_id,
            "title": self.title,
            "meaning": self.meaning,
            "applicability": self.applicability,
            "limitations": self.limitations,
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
            _admit_declaration(self.prerequisites),
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
            _admit_declaration(self.prerequisites),
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
        "string",
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
class SelectionObjectiveConsumptionDefinition:
    """Closed declaration binding a Node to Workflow-owned objectives."""

    candidate_input_port: str
    score_collection_input_port: str
    candidate_output_port: str
    objective_id_parameter: str | None = None
    objective_ids_parameter: str | None = None

    def descriptor_template(self) -> dict[str, str]:
        descriptor = {
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
class CandidateSelectionConsumptionDefinition:
    """A Candidate-only selection with no Score dependency."""

    candidate_input_port: str
    candidate_output_port: str

    def descriptor_template(self) -> dict[str, str]:
        return {
            "candidate_input_port": self.candidate_input_port,
            "candidate_output_port": self.candidate_output_port,
        }


@dataclass(frozen=True, slots=True)
class ObservationSelectorConsumptionDefinition:
    """Closed declaration binding a Node to ordered raw Observation selectors."""

    candidate_input_port: str
    score_collection_input_port: str
    candidate_output_port: str
    selector_ids_parameter: str

    def descriptor_template(self) -> dict[str, str]:
        return {
            "candidate_input_port": self.candidate_input_port,
            "score_collection_input_port": self.score_collection_input_port,
            "candidate_output_port": self.candidate_output_port,
            "selector_ids_parameter": self.selector_ids_parameter,
        }


@dataclass(frozen=True, slots=True)
class ParameterDependencies:
    """Actual definition and connected-slot dependencies selected by parameters."""

    contracts: tuple[ExactContractReference, ...] = ()
    input_slots: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "contracts", tuple(self.contracts))
        object.__setattr__(self, "input_slots", tuple(tuple(item) for item in self.input_slots))


@dataclass(frozen=True, slots=True)
class ParameterDependencyDeclaration:
    """Module-owned interpretation of canonical Node and Binding parameters."""

    behavior: BehaviorReference
    resolve: Callable[[Mapping[str, Any], Mapping[str, Any]], ParameterDependencies] = field(repr=False, compare=False)


@dataclass(frozen=True, slots=True)
class ExecutionBindingDefinition:
    """Executable association between one Node Type and one Method."""

    binding_id: str
    node_type: ExactContractReference
    method: ExactContractReference
    binding_parameters: Mapping[str, Any]
    parameter_contract: ParameterContract = field(init=False, repr=False)
    execution_route: Literal["adapter", "direct"]
    factory: ScientificOperationFactory
    availability: AvailabilityDeclaration
    deterministic: bool
    cacheable: bool
    readiness: ReadinessDeclaration | None = None
    produced_observations: tuple[ProducedObservation, ...] = ()
    adapter_behavior: BehaviorReference | None = None
    observation_propagation: ObservationPropagation | None = None
    selection_objective_consumption: (
        SelectionObjectiveConsumptionDefinition | None
    ) = None
    observation_selector_consumption: (
        ObservationSelectorConsumptionDefinition | None
    ) = None
    candidate_selection_consumption: (
        CandidateSelectionConsumptionDefinition | None
    ) = None
    effective_randomness_parameters: tuple[str, ...] = ()
    effective_randomness_resolver: EffectiveRandomnessResolver | None = field(
        default=None,
        repr=False,
        compare=False,
    )
    environment_fields: tuple[EnvironmentFieldDeclaration, ...] = ()
    parameter_dependencies: ParameterDependencyDeclaration | None = None

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
            _admit_declaration(self.binding_parameters),
        )
        object.__setattr__(
            self,
            "parameter_contract",
            _admit_parameter_declarations(
                self.binding_parameters,
                path=f"binding:{self.binding_id}.binding_parameters",
            ),
        )
        object.__setattr__(
            self,
            "produced_observations",
            tuple(self.produced_observations),
        )

    @property
    def identity(self) -> ExactContractReference:
        return ExactContractReference("binding", self.binding_id)

    def descriptor_template(self) -> dict[str, Any]:
        descriptor = {
            "schema_namespace": CONTRACT_NAMESPACE,
            "contract_kind": "binding",
            "contract_id": self.binding_id,
            "node_type": self.node_type,
            "method": self.method,
            "binding_parameters": self.binding_parameters,
            "execution_route": self.execution_route,
            "factory_behavior": self.factory.behavior.descriptor(),
            "route_behavior": (
                self.adapter_behavior.descriptor()
                if self.adapter_behavior is not None
                else self.factory.behavior.descriptor()
            ),
            "availability_declaration": self.availability.descriptor(),
            "deterministic": self.deterministic,
            "cacheable": self.cacheable,
            "produced_observations": [
                _produced_observation_descriptor(observation)
                for observation in self.produced_observations
            ],
            "observation_propagation": (
                _observation_propagation_descriptor(self.observation_propagation)
                if self.observation_propagation is not None
                else None
            ),
        }
        if self.readiness is not None:
            descriptor["readiness_declaration"] = self.readiness.descriptor()
        if self.parameter_dependencies is not None:
            descriptor["parameter_dependencies"] = self.parameter_dependencies.behavior.descriptor()
        if self.selection_objective_consumption is not None:
            descriptor["selection_objective_consumption"] = (
                self.selection_objective_consumption.descriptor_template()
            )
        if self.observation_selector_consumption is not None:
            descriptor["observation_selector_consumption"] = (
                self.observation_selector_consumption.descriptor_template()
            )
        if self.candidate_selection_consumption is not None:
            descriptor["candidate_selection_consumption"] = (
                self.candidate_selection_consumption.descriptor_template()
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
    package_module: str
    value_previews: tuple[ValuePreviewDefinition, ...] = ()
    ui_extensions: tuple[ModuleUiDefinition, ...] = ()
    node_definitions: tuple[DefinitionResource, ...] = ()
    metric_definitions: tuple[DefinitionResource, ...] = ()
    methods: tuple[MethodDefinition, ...] = ()
    bindings: tuple[ExecutionBindingDefinition, ...] = ()
    port_types: tuple[PortTypeDefinition, ...] = ()
    utility_transforms: tuple[UtilityTransformDefinition, ...] = ()
    authoring_capabilities: tuple[AuthoringCapabilityDefinition, ...] = ()
    authoring_actions: tuple[AuthoringActionDefinition, ...] = ()
    result_actions: tuple[ResultActionDefinition, ...] = ()
    result_readers: tuple[ResultReaderDefinition, ...] = ()
    result_sources: tuple[ResultSourceDefinition, ...] = ()

    def __post_init__(self) -> None:
        for field_name in (
            "node_definitions",
            "metric_definitions",
            "methods",
            "bindings",
            "port_types",
            "utility_transforms",
            "authoring_capabilities",
            "ui_extensions",
            "value_previews",
            "result_actions",
            "authoring_actions",
            "result_readers",
            "result_sources",
        ):
            object.__setattr__(self, field_name, tuple(getattr(self, field_name)))


def _produced_observation_descriptor(value: ProducedObservation) -> dict[str, Any]:
    """Keep the scientific descriptor independent of internal type layout."""
    result = {
        "output_port": value.output_port,
        "output_partition": value.output_partition,
        "metric": value.metric,
        "context_profile": observation_context_profile_descriptor(value.context_profile),
        "subject_grain": "candidate",
        "source_role": "subject",
        "subject_direction": "input",
        "subject_port": value.subject_input,
        "guaranteed_multiplicity": value.guaranteed_multiplicity,
    }
    for name in ("reference", "pairing", "axis", "method"):
        source = getattr(value, f"{name}_source")
        result[f"{name}_direction"] = source.direction if source is not None else None
        result[f"{name}_port"] = source.port if source is not None else None
    return result


def _observation_propagation_descriptor(value: ObservationPropagation) -> dict[str, Any]:
    filter_value = value.filter
    filtered: dict[str, Any] | None = None
    if filter_value is not None:
        filtered = {}
        for name in ("source_partition", "metric", "method"):
            field_value = getattr(filter_value, name)
            if field_value is not None:
                filtered[name] = field_value
        if filter_value.context_profile is not None:
            filtered["context_profile"] = observation_context_profile_descriptor(filter_value.context_profile)
    result = {
        "mode": value.mode,
        "output_port": value.output_port,
        "input_ports": value.input_ports,
        "filter": filtered,
    }
    if value.absent_input_policy != "reject":
        result["absent_input_policy"] = value.absent_input_policy
    return result
