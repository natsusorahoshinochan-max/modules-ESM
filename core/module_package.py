"""Atomic v2 Module Package registration and Catalog construction."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
import importlib
from importlib import resources
from pathlib import Path, PurePosixPath
import re
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from core.run_execution_v2 import ReadinessCheckInput, ReadinessResult

import yaml

from core.artifacts import is_valid_artifact_media_type
from core.operation import OperationContext, ScientificOperation
from core.parameter_contract import parameter_value_contract
from core.port_types import (
    CANDIDATE_COLLECTION_PORT_TYPE_VERSION,
    CANDIDATE_PAIRING_PORT_TYPE_VERSION,
    CONTRACT_NAMESPACE,
    SCORE_COLLECTION_PORT_TYPE_VERSION,
    BehaviorReference,
    CatalogBuildError,
    FrozenCatalog,
    PortTypeDefinition,
    _require_single_active_contract_version,
    builtin_frozen_catalog,
    canonical_json_bytes,
)
from datatypes import validate_canonical_identifier


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
_DEFINITION_RESOURCE_SUFFIXES = frozenset({".yaml", ".yml"})
_NON_PRODUCTION_RESOURCE_PARTS = frozenset(
    {"fixture", "fixtures", "test", "tests"}
)
_SCIENTIFIC_COLLECTION_PORT_TYPE_VERSIONS = {
    "candidate.collection": CANDIDATE_COLLECTION_PORT_TYPE_VERSION,
    "score.collection": SCORE_COLLECTION_PORT_TYPE_VERSION,
}


class ModulePackageDiscoveryError(CatalogBuildError):
    """A first-level Module Package did not expose one valid registration."""


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
class DefinitionResource:
    """One explicitly named package-local YAML Definition resource."""

    resource: str

    def __post_init__(self) -> None:
        path = PurePosixPath(self.resource)
        if (
            not self.resource
            or path.is_absolute()
            or ".." in path.parts
            or "." in path.parts
            or path.suffix not in _DEFINITION_RESOURCE_SUFFIXES
        ):
            raise CatalogBuildError(
                "Definition resource must be one relative package-local YAML path"
            )
        if _NON_PRODUCTION_RESOURCE_PARTS.intersection(path.parts):
            raise CatalogBuildError(
                "package-local tests and fixtures cannot enter production "
                "registration"
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
        if not callable(self.transform):
            raise CatalogBuildError("Utility Transform runtime must be callable")

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

    def __post_init__(self) -> None:
        if not callable(self.build):
            raise CatalogBuildError(
                "Scientific Operation factory must be callable"
            )


@dataclass(frozen=True, slots=True)
class EffectiveRandomnessResolver:
    """Private pre-Cache resolver paired with a stable behavior identity."""

    behavior: BehaviorReference
    resolve: Callable[..., Mapping[str, Any]] = field(
        repr=False,
        compare=False,
    )

    def __post_init__(self) -> None:
        if not callable(self.resolve):
            raise CatalogBuildError(
                "effective randomness resolver must be callable"
            )


@dataclass(frozen=True, slots=True)
class AvailabilityResult:
    """One structured startup Availability conclusion."""

    is_available: bool
    code: str | None = None
    message: str | None = None
    retryable: bool | None = None

    def __post_init__(self) -> None:
        if self.is_available:
            if any(
                value is not None
                for value in (self.code, self.message, self.retryable)
            ):
                raise CatalogBuildError(
                    "available result must not contain an unavailable reason"
                )
            return
        if (
            self.code is None
            or self.message is None
            or self.retryable is None
        ):
            raise CatalogBuildError(
                "unavailable result requires code, message, and retryable"
            )
        _require_identifier(self.code, "Availability reason code")
        if not isinstance(self.message, str) or not 1 <= len(self.message) <= 1024:
            raise CatalogBuildError(
                "Availability reason message must contain 1 to 1024 characters"
            )
        if not isinstance(self.retryable, bool):
            raise CatalogBuildError("Availability retryable must be boolean")

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

    def reason(self) -> dict[str, Any] | None:
        if self.is_available:
            return None
        return {
            "code": self.code,
            "message": self.message,
            "retryable": self.retryable,
        }


class ExpectedOptionalDependencyMissing(ModuleNotFoundError):
    """One checker-declared absent optional dependency."""

    def __init__(self, dependency_id: str) -> None:
        _require_identifier(
            dependency_id,
            "Optional dependency identifier",
        )
        self.dependency_id = dependency_id
        super().__init__(
            f"Optional dependency {dependency_id} is not installed",
            name=dependency_id,
        )


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
        if not callable(self.check):
            raise CatalogBuildError("Availability checker must be callable")

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
        if not callable(self.check):
            raise CatalogBuildError("Readiness checker must be callable")

    def descriptor(self) -> dict[str, Any]:
        return {
            "behavior": self.behavior.descriptor(),
            "prerequisites": self.prerequisites,
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
    output_partition: str = "default"
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
        if type(self.deterministic) is not bool or type(self.cacheable) is not bool:
            raise CatalogBuildError(
                "Binding deterministic and cacheable declarations must be boolean"
            )
        if not isinstance(self.implementation_identity, Mapping):
            raise CatalogBuildError("implementation_identity must be an object")
        randomness_parameters = tuple(self.effective_randomness_parameters)
        if any(
            not isinstance(parameter, str) or not parameter
            for parameter in randomness_parameters
        ) or len(set(randomness_parameters)) != len(randomness_parameters):
            raise CatalogBuildError(
                "effective_randomness_parameters must contain unique names"
            )
        if len(randomness_parameters) > 256:
            raise CatalogBuildError(
                "effective_randomness_parameters must contain at most 256 names"
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
            "binding_parameters",
            _freeze_declaration(
                self.binding_parameters,
                path="$.binding_parameters",
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
                        _template_json(observation.context_profile)
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
        return descriptor


@dataclass(frozen=True, slots=True)
class _NodeDefinition:
    node_type_id: str
    version: str
    title: str
    summary: str
    category: str
    inputs: tuple[Mapping[str, Any], ...]
    outputs: tuple[Mapping[str, Any], ...]
    input_constraints: tuple[Mapping[str, Any], ...]
    parameter_groups: tuple[Any, ...]
    node_parameters: Mapping[str, Any]

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
            "inputs": self.inputs,
            "outputs": self.outputs,
            "parameter_groups": self.parameter_groups,
            "node_parameters": self.node_parameters,
        }
        if self.input_constraints:
            descriptor["input_constraints"] = self.input_constraints
        return descriptor


@dataclass(frozen=True, slots=True)
class _MetricDefinition:
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


DeclarativeDefinition = (
    _NodeDefinition
    | _MetricDefinition
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


@dataclass(frozen=True, slots=True)
class CatalogContract:
    """One resolved immutable public Catalog contract."""

    contract_kind: ContractKind
    contract_id: str
    contract_version: str
    descriptor: Mapping[str, Any]

    def __post_init__(self) -> None:
        descriptor = _thaw_declaration(self.descriptor)
        canonical_json_bytes(descriptor)
        object.__setattr__(
            self,
            "descriptor",
            _freeze_declaration(descriptor),
        )

    @property
    def descriptor_bytes(self) -> bytes:
        return canonical_json_bytes(_thaw_declaration(self.descriptor))

    @property
    def contract_digest(self) -> str:
        import hashlib

        return f"sha256:{hashlib.sha256(self.descriptor_bytes).hexdigest()}"

    def reference(self) -> dict[str, Any]:
        return {
            "contract_kind": self.contract_kind,
            "contract_id": self.contract_id,
            "contract_version": self.contract_version,
            "contract_digest": self.contract_digest,
        }

    def public_contract(self) -> dict[str, Any]:
        return {
            "reference": self.reference(),
            "descriptor": _thaw_declaration(self.descriptor),
        }


class _UniqueKeySafeLoader(yaml.SafeLoader):
    pass


def _construct_unique_mapping(
    loader: _UniqueKeySafeLoader,
    node: yaml.MappingNode,
    deep: bool = False,
) -> dict[Any, Any]:
    pairs = loader.construct_pairs(node, deep=deep)
    result: dict[Any, Any] = {}
    for key, value in pairs:
        try:
            duplicate = key in result
        except TypeError as error:
            raise CatalogBuildError(
                "YAML object keys must be scalar and hashable"
            ) from error
        if duplicate:
            raise CatalogBuildError(f"duplicate YAML object key {key!r}")
        try:
            result[key] = value
        except TypeError as error:
            raise CatalogBuildError(
                "YAML object keys must be scalar and hashable"
            ) from error
    return result


_UniqueKeySafeLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_unique_mapping,
)


def _closed_object(
    raw: Any,
    *,
    resource_name: str,
    required: set[str],
    allowed: set[str],
) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise CatalogBuildError(f"{resource_name} must contain one YAML object")
    unknown = set(raw) - allowed
    missing = required - set(raw)
    if unknown:
        raise CatalogBuildError(
            f"{resource_name} contains unknown fields: {sorted(unknown)}"
        )
    if missing:
        raise CatalogBuildError(
            f"{resource_name} is missing required fields: {sorted(missing)}"
        )
    return raw


def _parse_port(
    raw: Any,
    *,
    resource_name: str,
    allow_artifact_publication: bool = False,
) -> Mapping[str, Any]:
    port = _closed_object(
        raw,
        resource_name=resource_name,
        required={
            "name",
            "port_type_id",
            "port_type_version",
            "required",
            "multiplicity",
            "scientific_meaning",
        },
        allowed={
            "name",
            "port_type_id",
            "port_type_version",
            "port_type_digest",
            "required",
            "multiplicity",
            "scientific_meaning",
            "artifact_kind",
            "artifact_media_type",
        },
    )
    _require_identifier(port["name"], f"{resource_name}.name")
    reference = ContractIdentity(
        "port_type",
        port["port_type_id"],
        port["port_type_version"],
        port.get("port_type_digest"),
    )
    if type(port["required"]) is not bool:
        raise CatalogBuildError(f"{resource_name}.required must be boolean")
    if port["multiplicity"] not in {"one", "many"}:
        raise CatalogBuildError(
            f"{resource_name}.multiplicity must be one or many"
        )
    meaning = port["scientific_meaning"]
    if not isinstance(meaning, str) or not 1 <= len(meaning) <= 2048:
        raise CatalogBuildError(
            f"{resource_name}.scientific_meaning must be non-empty"
        )
    artifact_kind = port.get("artifact_kind")
    artifact_media_type = port.get("artifact_media_type")
    if artifact_kind is not None and (
        not allow_artifact_publication
        or artifact_kind not in {"standalone", "candidate"}
    ):
        raise CatalogBuildError(
            f"{resource_name}.artifact_kind is not a valid artifact output"
        )
    if artifact_media_type is not None and (
        artifact_kind is None
        or not is_valid_artifact_media_type(artifact_media_type)
    ):
        raise CatalogBuildError(
            f"{resource_name}.artifact_media_type is invalid"
        )
    descriptor = {
        "name": port["name"],
        "port_type": reference,
        "required": port["required"],
        "multiplicity": port["multiplicity"],
        "scientific_meaning": meaning,
    }
    if artifact_kind is not None:
        descriptor["artifact_kind"] = artifact_kind
    if artifact_media_type is not None:
        descriptor["artifact_media_type"] = artifact_media_type
    return MappingProxyType(descriptor)


def _parse_node_definition(raw: Any, resource_name: str) -> _NodeDefinition:
    required = {
        "schema_version",
        "node_type_id",
        "version",
        "title",
        "summary",
        "category",
        "inputs",
        "outputs",
        "parameter_groups",
        "node_parameters",
    }
    node = _closed_object(
        raw,
        resource_name=resource_name,
        required=required,
        allowed={*required, "input_constraints"},
    )
    _require_schema_version(node["schema_version"], "Node Definition")
    _require_identifier(node["node_type_id"], "node_type_id")
    _require_version(node["version"], "Node Type version")
    for field_name, limit in (("title", 256), ("summary", 4096)):
        value = node[field_name]
        if not isinstance(value, str) or not 1 <= len(value) <= limit:
            raise CatalogBuildError(
                f"Node Definition {field_name} must be non-empty"
            )
    _require_identifier(node["category"], "Node Type category")
    if not isinstance(node["inputs"], list) or not isinstance(
        node["outputs"],
        list,
    ):
        raise CatalogBuildError("Node Definition inputs/outputs must be arrays")
    inputs = tuple(
        _parse_port(item, resource_name=f"{resource_name}.inputs[{index}]")
        for index, item in enumerate(node["inputs"])
    )
    outputs = tuple(
        _parse_port(
            item,
            resource_name=f"{resource_name}.outputs[{index}]",
            allow_artifact_publication=True,
        )
        for index, item in enumerate(node["outputs"])
    )
    for label, ports in (("input", inputs), ("output", outputs)):
        names = [port["name"] for port in ports]
        if len(set(names)) != len(names):
            raise CatalogBuildError(f"duplicate Node {label} Port name")
    input_names = {port["name"] for port in inputs}
    raw_input_constraints = node.get("input_constraints", [])
    if not isinstance(raw_input_constraints, list):
        raise CatalogBuildError("input_constraints must be an array")
    input_constraints: list[Mapping[str, Any]] = []
    constrained_ports: set[str] = set()
    for index, raw_constraint in enumerate(raw_input_constraints):
        constraint = _closed_object(
            raw_constraint,
            resource_name=f"{resource_name}.input_constraints[{index}]",
            required={"kind", "ports"},
            allowed={"kind", "ports"},
        )
        ports = constraint["ports"]
        if (
            constraint["kind"] != "exactly_one"
            or not isinstance(ports, list)
            or len(ports) < 2
            or any(not isinstance(port, str) for port in ports)
            or len(set(ports)) != len(ports)
            or not set(ports) <= input_names
            or constrained_ports.intersection(ports)
        ):
            raise CatalogBuildError(
                "input_constraints must contain disjoint exactly_one "
                "groups of declared input Ports"
            )
        constrained_ports.update(ports)
        input_constraints.append(
            MappingProxyType(
                {
                    "kind": "exactly_one",
                    "ports": tuple(ports),
                }
            )
        )
    if not isinstance(node["parameter_groups"], list):
        raise CatalogBuildError("parameter_groups must be an array")
    if not all(
        isinstance(group, dict)
        for group in node["parameter_groups"]
    ):
        raise CatalogBuildError(
            "each parameter_groups item must be an object"
        )
    if not isinstance(node["node_parameters"], dict):
        raise CatalogBuildError("node_parameters must be an object")
    return _NodeDefinition(
        node_type_id=node["node_type_id"],
        version=node["version"],
        title=node["title"],
        summary=node["summary"],
        category=node["category"],
        inputs=inputs,
        outputs=outputs,
        input_constraints=tuple(input_constraints),
        parameter_groups=_freeze_declaration(node["parameter_groups"]),
        node_parameters=_freeze_declaration(node["node_parameters"]),
    )


def _parse_metric_definition(raw: Any, resource_name: str) -> _MetricDefinition:
    required = {
        "schema_version",
        "metric_id",
        "version",
        "title",
        "description",
        "value_shape",
        "unit",
        "direction",
        "canonical_range",
        "granularity",
        "aggregation_semantics",
        "observation_context_schema",
        "validation_contract",
    }
    metric = _closed_object(
        raw,
        resource_name=resource_name,
        required=required,
        allowed=required,
    )
    _require_schema_version(metric["schema_version"], "Metric Definition")
    _require_identifier(metric["metric_id"], "metric_id")
    _require_version(metric["version"], "Metric version")
    for field_name, limit in (
        ("title", 256),
        ("description", 4096),
        ("unit", 128),
    ):
        value = metric[field_name]
        if not isinstance(value, str) or not 1 <= len(value) <= limit:
            raise CatalogBuildError(
                f"Metric Definition {field_name} must be non-empty"
            )
    _require_identifier(metric["value_shape"], "value_shape")
    _require_identifier(metric["granularity"], "granularity")
    if metric["direction"] not in {
        "higher_is_better",
        "lower_is_better",
        "none",
        "target",
    }:
        raise CatalogBuildError("Metric Definition direction is unknown")
    mapping_fields = (
        "canonical_range",
        "aggregation_semantics",
        "observation_context_schema",
        "validation_contract",
    )
    for field_name in mapping_fields:
        if not isinstance(metric[field_name], dict):
            raise CatalogBuildError(
                f"Metric Definition {field_name} must be an object"
            )
    return _MetricDefinition(
        metric_id=metric["metric_id"],
        version=metric["version"],
        title=metric["title"],
        description=metric["description"],
        value_shape=metric["value_shape"],
        unit=metric["unit"],
        direction=metric["direction"],
        canonical_range=_freeze_declaration(metric["canonical_range"]),
        granularity=metric["granularity"],
        aggregation_semantics=_freeze_declaration(
            metric["aggregation_semantics"]
        ),
        observation_context_schema=_freeze_declaration(
            metric["observation_context_schema"]
        ),
        validation_contract=_freeze_declaration(
            metric["validation_contract"]
        ),
    )


def _load_definition_resource(
    registration: ModulePackageRegistration,
    resource_reference: DefinitionResource,
    *,
    kind: Literal["metric", "node_type"],
) -> DeclarativeDefinition:
    try:
        package_root = resources.files(registration.package_module)
        target = package_root.joinpath(resource_reference.resource)
        if not target.is_file():
            raise FileNotFoundError(resource_reference.resource)
        content = target.read_text(encoding="utf-8")
    except (FileNotFoundError, ModuleNotFoundError, OSError) as error:
        raise CatalogBuildError(
            f"{registration.package_id} cannot load explicit Definition "
            f"resource {resource_reference.resource!r}"
        ) from error
    try:
        raw = yaml.load(content, Loader=_UniqueKeySafeLoader)
    except yaml.YAMLError as error:
        raise CatalogBuildError(
            f"{registration.package_id}:{resource_reference.resource} "
            "contains malformed YAML"
        ) from error
    resource_name = (
        f"{registration.package_id}:{resource_reference.resource}"
    )
    if kind == "node_type":
        return _parse_node_definition(raw, resource_name)
    return _parse_metric_definition(raw, resource_name)


def _template_json(value: Any) -> Any:
    if isinstance(value, ContractIdentity):
        return {
            "$contract_reference": {
                "contract_kind": value.contract_kind,
                "contract_id": value.contract_id,
                "contract_version": value.contract_version,
                "expected_digest": value.expected_digest,
            }
        }
    if isinstance(value, Mapping):
        return {key: _template_json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_template_json(item) for item in value]
    return value


def _definition_identity(
    definition: DeclarativeDefinition,
) -> ContractIdentity:
    return definition.identity


def _utc_timestamp(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise CatalogBuildError("Catalog observation time must be timezone-aware")
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _matches_context_constraint(value: Any, constraint: Any) -> bool:
    if isinstance(constraint, Mapping):
        if "const" in constraint:
            return value == constraint["const"]
        if "enum" in constraint:
            enum = constraint["enum"]
            return isinstance(enum, (list, tuple)) and value in enum
        if "type" in constraint:
            expected_type = constraint["type"]
            return (
                (expected_type == "string" and isinstance(value, str))
                or (
                    expected_type == "number"
                    and type(value) in {int, float}
                )
                or (expected_type == "integer" and type(value) is int)
                or (expected_type == "boolean" and type(value) is bool)
                or (expected_type == "object" and isinstance(value, Mapping))
                or (expected_type == "array" and isinstance(value, (list, tuple)))
                or (expected_type == "null" and value is None)
            )
        if not isinstance(value, Mapping) or set(value) != set(constraint):
            return False
        return all(
            _matches_context_constraint(value[key], item)
            for key, item in constraint.items()
        )
    if isinstance(constraint, tuple):
        return isinstance(value, (list, tuple)) and tuple(value) == constraint
    return value == constraint


def _validate_observation_context_profile(
    profile: Mapping[str, Any],
    schema: Mapping[str, Any],
    *,
    binding_id: str,
) -> None:
    if (
        schema.get("type") == "object"
        and isinstance(schema.get("properties"), Mapping)
    ):
        properties = schema["properties"]
        required = schema.get("required", ())
        if not isinstance(required, (list, tuple)) or not all(
            isinstance(name, str)
            for name in required
        ):
            raise CatalogBuildError(
                "Metric observation_context_schema required must be an array "
                "of property names"
            )
        if schema.get("additionalProperties") is not False:
            raise CatalogBuildError(
                "Metric observation_context_schema must be closed"
            )
        valid = (
            set(required) <= set(profile)
            and set(profile) <= set(properties)
            and all(
                _matches_context_constraint(profile[name], properties[name])
                for name in profile
            )
        )
    else:
        valid = set(profile) == set(schema) and all(
            _matches_context_constraint(profile[name], schema[name])
            for name in profile
        )
    if not valid:
        raise CatalogBuildError(
            f"Binding {binding_id} Produced Observation context_profile "
            "does not satisfy Metric observation_context_schema"
        )


def discover_module_packages(
    modules_package: str = "modules",
) -> tuple[ModulePackageRegistration, ...]:
    """Read only first-level ``package.py:MODULE_PACKAGE`` registrations."""
    try:
        root = importlib.import_module(modules_package)
        package_paths = tuple(Path(path) for path in root.__path__)
    except (AttributeError, ImportError, OSError) as error:
        raise ModulePackageDiscoveryError(
            f"Cannot import Module Package root {modules_package!r}"
        ) from error
    if len(package_paths) != 1:
        raise ModulePackageDiscoveryError(
            "Module Package root must resolve to one deterministic location"
        )
    package_path = package_paths[0]
    registrations: list[ModulePackageRegistration] = []
    seen_package_ids: set[tuple[str, str]] = set()
    try:
        children = sorted(
            (
                child
                for child in package_path.iterdir()
                if child.is_dir()
                and not child.is_symlink()
                and (child / "package.py").is_file()
            ),
            key=lambda child: child.name,
        )
    except OSError as error:
        raise ModulePackageDiscoveryError(
            f"Cannot enumerate Module Package root {modules_package!r}"
        ) from error
    for child in children:
        qualified_package = f"{modules_package}.{child.name}"
        registration_module = f"{qualified_package}.package"
        try:
            package_py = importlib.import_module(registration_module)
            registration = getattr(package_py, "MODULE_PACKAGE")
        except Exception as error:
            raise ModulePackageDiscoveryError(
                f"Failed to import explicit Module Package registration "
                f"{registration_module}: {error}"
            ) from error
        if not isinstance(registration, ModulePackageRegistration):
            raise ModulePackageDiscoveryError(
                f"{registration_module}:MODULE_PACKAGE must be one "
                "ModulePackageRegistration"
            )
        if registration.package_module != qualified_package:
            raise ModulePackageDiscoveryError(
                f"{registration_module} registered resources from "
                f"{registration.package_module!r}, expected "
                f"{qualified_package!r}"
            )
        package_identity = (
            registration.package_id,
            registration.package_version,
        )
        if package_identity in seen_package_ids:
            raise ModulePackageDiscoveryError(
                "duplicate Module Package identity "
                f"{registration.package_id}@{registration.package_version}"
            )
        seen_package_ids.add(package_identity)
        registrations.append(registration)
    return tuple(registrations)


def build_frozen_catalog(
    registrations: Sequence[ModulePackageRegistration],
    *,
    builtin_port_types: Sequence[PortTypeDefinition] | None = None,
    observed_at: datetime | None = None,
) -> FrozenCatalog:
    """Validate all registrations in temporary state, then return one Catalog."""
    registration_tuple = tuple(registrations)
    if any(
        not isinstance(registration, ModulePackageRegistration)
        for registration in registration_tuple
    ):
        raise CatalogBuildError(
            "Catalog builder accepts only ModulePackageRegistration values"
        )
    package_identities: set[tuple[str, str]] = set()
    for registration in registration_tuple:
        package_identity = (
            registration.package_id,
            registration.package_version,
        )
        if package_identity in package_identities:
            raise CatalogBuildError(
                "duplicate Module Package identity "
                f"{registration.package_id}@{registration.package_version}"
            )
        package_identities.add(package_identity)

    port_types = tuple(
        builtin_port_types
        if builtin_port_types is not None
        else builtin_frozen_catalog().port_types
    )
    port_type_entries: list[tuple[str, PortTypeDefinition]] = [
        ("protein-workbench.core", definition)
        for definition in port_types
    ]
    definitions: list[tuple[str, DeclarativeDefinition]] = []
    loaded_resources: set[tuple[str, str]] = set()
    bindings_by_key: dict[
        tuple[str, str, str],
        tuple[str, ExecutionBindingDefinition],
    ] = {}
    utility_runtime: dict[
        tuple[str, str],
        Callable[[Any, Mapping[str, Any]], float],
    ] = {}

    for registration in registration_tuple:
        for kind, resource_references in (
            ("node_type", registration.node_definitions),
            ("metric", registration.metric_definitions),
        ):
            for resource_reference in resource_references:
                resource_key = (
                    registration.package_module,
                    resource_reference.resource,
                )
                if resource_key in loaded_resources:
                    raise CatalogBuildError(
                        "Definition resource is registered more than once: "
                        f"{registration.package_id}:"
                        f"{resource_reference.resource}"
                    )
                loaded_resources.add(resource_key)
                definition = _load_definition_resource(
                    registration,
                    resource_reference,
                    kind=kind,
                )
                definitions.append((registration.package_id, definition))
        definitions.extend(
            (registration.package_id, definition)
            for definition in registration.methods
        )
        definitions.extend(
            (registration.package_id, definition)
            for definition in registration.utility_transforms
        )
        for binding in registration.bindings:
            definitions.append((registration.package_id, binding))
            bindings_by_key[binding.identity.key] = (
                registration.package_id,
                binding,
            )
        port_type_entries.extend(
            (registration.package_id, definition)
            for definition in registration.port_types
        )
        utility_runtime.update(
            {
                (definition.transform_id, definition.version): (
                    definition.transform
                )
                for definition in registration.utility_transforms
            }
        )

    entry_by_key: dict[
        tuple[str, str, str],
        tuple[set[str], PortTypeDefinition | DeclarativeDefinition],
    ] = {}
    template_by_key: dict[tuple[str, str, str], bytes] = {}
    for owner, port_type in port_type_entries:
        key = ("port_type", port_type.type_id, port_type.version)
        fingerprint = port_type.descriptor_bytes
        if key in entry_by_key:
            if template_by_key[key] != fingerprint:
                raise CatalogBuildError(
                    "conflicting contract identity "
                    f"port_type:{port_type.type_id}@{port_type.version}"
                )
            raise CatalogBuildError(
                "duplicate contract identity "
                f"port_type:{port_type.type_id}@{port_type.version}"
            )
        entry_by_key[key] = ({owner}, port_type)
        template_by_key[key] = fingerprint

    for owner, definition in definitions:
        identity = _definition_identity(definition)
        key = identity.key
        fingerprint = canonical_json_bytes(
            _template_json(definition.descriptor_template())
        )
        existing = entry_by_key.get(key)
        if existing is not None:
            if template_by_key[key] != fingerprint:
                raise CatalogBuildError(
                    "conflicting contract identity "
                    f"{identity.contract_kind}:{identity.contract_id}@"
                    f"{identity.contract_version}"
                )
            existing_owners, _ = existing
            if identity.contract_kind == "metric" and owner not in existing_owners:
                existing_owners.add(owner)
                continue
            raise CatalogBuildError(
                "duplicate contract identity "
                f"{identity.contract_kind}:{identity.contract_id}@"
                f"{identity.contract_version}"
            )
        entry_by_key[key] = ({owner}, definition)
        template_by_key[key] = fingerprint

    _require_single_active_contract_version(sorted(entry_by_key))

    for _, definition in definitions:
        if not isinstance(definition, _NodeDefinition):
            continue
        for output in definition.outputs:
            reference = output["port_type"]
            port_entry = entry_by_key.get(reference.key)
            port_type = port_entry[1] if port_entry is not None else None
            if (
                isinstance(port_type, PortTypeDefinition)
                and port_type.artifact_media_types is not None
                and output.get("artifact_kind") is None
            ):
                raise CatalogBuildError(
                    f"Node {definition.node_type_id} artifact-capable output "
                    f"{output['name']!r} requires explicit publication intent"
                )
            if output.get("artifact_kind") is None:
                continue
            if (
                not isinstance(port_type, PortTypeDefinition)
                or port_type.artifact_media_types is None
            ):
                raise CatalogBuildError(
                    f"Node {definition.node_type_id} artifact output "
                    f"{output['name']!r} requires a Port Type with an exact "
                    "generic artifact publication contract"
                )
            artifact_media_type = output.get("artifact_media_type")
            if (
                not isinstance(artifact_media_type, str)
                or artifact_media_type
                not in port_type.artifact_media_types
            ):
                raise CatalogBuildError(
                    f"Node {definition.node_type_id} artifact output "
                    f"{output['name']!r} requires one exact media type "
                    "accepted by its nominal Port Type"
                )

    for registration in registration_tuple:
        owned = {
            key
            for key, (owners, _) in entry_by_key.items()
            if registration.package_id in owners
        }
        for binding in registration.bindings:
            if binding.node_type.key not in owned:
                raise CatalogBuildError(
                    f"Binding {binding.binding_id} references a Node Type not "
                    f"owned by package {registration.package_id}"
                )
            if binding.method.key not in owned:
                raise CatalogBuildError(
                    f"Binding {binding.binding_id} references a Method not "
                    f"owned by package {registration.package_id}"
                )
            _, node_definition = entry_by_key[binding.node_type.key]
            if not isinstance(node_definition, _NodeDefinition):
                raise CatalogBuildError(
                    f"Binding {binding.binding_id} does not reference a "
                    "Node Definition"
                )
            declared_parameters = {
                *node_definition.node_parameters,
                *binding.binding_parameters,
            }
            unknown_randomness = (
                set(binding.effective_randomness_parameters)
                - declared_parameters
            )
            if unknown_randomness:
                raise CatalogBuildError(
                    f"Binding {binding.binding_id} effective randomness "
                    "references undeclared parameters"
                )
            ambiguous_randomness = (
                set(binding.effective_randomness_parameters)
                & set(node_definition.node_parameters)
                & set(binding.binding_parameters)
            )
            if ambiguous_randomness:
                raise CatalogBuildError(
                    f"Binding {binding.binding_id} effective randomness must "
                    "resolve from exactly one parameter scope"
                )
            output_names = {
                output["name"]
                for output in node_definition.outputs
            }
            input_names = {
                input_port["name"]
                for input_port in node_definition.inputs
            }
            outputs_by_name = {
                output["name"]: output
                for output in node_definition.outputs
            }
            inputs_by_name = {
                input_port["name"]: input_port
                for input_port in node_definition.inputs
            }
            consumption = binding.selection_objective_consumption
            if consumption is not None:
                selector_parameter = (
                    consumption.objective_id_parameter
                    if consumption.objective_id_parameter is not None
                    else consumption.objective_ids_parameter
                )
                parameter = node_definition.node_parameters.get(
                    selector_parameter
                )
                parameter_contract = (
                    parameter_value_contract(parameter)
                    if isinstance(parameter, Mapping)
                    else {}
                )
                scalar_selector = (
                    consumption.objective_id_parameter is not None
                    and parameter_contract.get("type") == "string"
                )
                ordered_selector = (
                    consumption.objective_ids_parameter is not None
                    and parameter_contract.get("type") == "array"
                    and isinstance(
                        parameter_contract.get("items"),
                        Mapping,
                    )
                    and parameter_contract["items"].get("type") == "string"
                    and parameter_contract.get("minItems", 0) >= 1
                    and parameter_contract.get("uniqueItems") is True
                )
                if not scalar_selector and not ordered_selector:
                    raise CatalogBuildError(
                        f"Binding {binding.binding_id} Selection Objective "
                        "consumption requires one declared string selector or "
                        "one non-empty unique ordered string-list selector"
                    )
                for field_name, port_name, expected_type in (
                    (
                        "candidate_input_port",
                        consumption.candidate_input_port,
                        "candidate.collection",
                    ),
                    (
                        "score_collection_input_port",
                        consumption.score_collection_input_port,
                        "score.collection",
                    ),
                ):
                    port = inputs_by_name.get(port_name)
                    reference = (
                        port.get("port_type")
                        if isinstance(port, Mapping)
                        else None
                    )
                    if (
                        not isinstance(reference, ContractIdentity)
                        or reference.key
                        != (
                            "port_type",
                            expected_type,
                            _SCIENTIFIC_COLLECTION_PORT_TYPE_VERSIONS[
                                expected_type
                            ],
                        )
                        or port.get("multiplicity") != "one"
                        or port.get("required") is not True
                    ):
                        raise CatalogBuildError(
                            f"Binding {binding.binding_id} {field_name} must "
                            f"name one required {expected_type} input Port"
                        )
                output = outputs_by_name.get(
                    consumption.candidate_output_port
                )
                output_reference = (
                    output.get("port_type")
                    if isinstance(output, Mapping)
                    else None
                )
                if (
                    not isinstance(output_reference, ContractIdentity)
                    or output_reference.key
                    != (
                        "port_type",
                        "candidate.collection",
                        CANDIDATE_COLLECTION_PORT_TYPE_VERSION,
                    )
                    or output.get("multiplicity") != "one"
                    or output.get("required") is not True
                ):
                    raise CatalogBuildError(
                        f"Binding {binding.binding_id} "
                        "candidate_output_port must name one required "
                        "candidate.collection output Port"
                    )
            for observation in binding.produced_observations:
                if observation.output_port not in output_names:
                    raise CatalogBuildError(
                        f"Binding {binding.binding_id} Produced Observation "
                        f"references unknown Node output Port "
                        f"{observation.output_port!r}"
                    )
                if observation.subject_direction != "input":
                    raise CatalogBuildError(
                        f"Binding {binding.binding_id} Produced Observation "
                        "must use an admitted input Candidate source"
                    )
                output_reference = outputs_by_name[
                    observation.output_port
                ]["port_type"]
                if (
                    not isinstance(output_reference, ContractIdentity)
                    or output_reference.key
                    != (
                        "port_type",
                        "score.collection",
                        SCORE_COLLECTION_PORT_TYPE_VERSION,
                    )
                ):
                    raise CatalogBuildError(
                        f"Binding {binding.binding_id} Produced Observation "
                        "output must use exact score.collection@"
                        f"{SCORE_COLLECTION_PORT_TYPE_VERSION}"
                    )
                subject_ports = (
                    input_names
                    if observation.subject_direction == "input"
                    else output_names
                )
                if observation.subject_port not in subject_ports:
                    raise CatalogBuildError(
                        f"Binding {binding.binding_id} Produced Observation "
                        f"references unknown subject {observation.subject_direction} "
                        f"Port {observation.subject_port!r}"
                    )
                subject_declaration = (
                    inputs_by_name
                    if observation.subject_direction == "input"
                    else outputs_by_name
                )[observation.subject_port]
                subject_reference = subject_declaration["port_type"]
                if (
                    observation.subject_grain != "candidate"
                    or observation.source_role != "subject"
                    or not isinstance(subject_reference, ContractIdentity)
                    or subject_reference.key
                    != (
                        "port_type",
                        "candidate.collection",
                        CANDIDATE_COLLECTION_PORT_TYPE_VERSION,
                    )
                ):
                    raise CatalogBuildError(
                        f"Binding {binding.binding_id} Produced Observation "
                        "subject must use exact candidate.collection@"
                        f"{CANDIDATE_COLLECTION_PORT_TYPE_VERSION} "
                        "with candidate subject grain"
                    )
                metric_entry = entry_by_key.get(observation.metric.key)
                if metric_entry is None:
                    continue
                _, metric_definition = metric_entry
                if not isinstance(metric_definition, _MetricDefinition):
                    raise CatalogBuildError(
                        f"Binding {binding.binding_id} Produced Observation "
                        "does not reference a Metric Definition"
                    )
                _validate_observation_context_profile(
                    observation.context_profile,
                    metric_definition.observation_context_schema,
                    binding_id=binding.binding_id,
                )
                has_axis_source = observation.axis_port is not None
                if metric_definition.requires_residue_axis != has_axis_source:
                    requirement = (
                        "requires"
                        if metric_definition.requires_residue_axis
                        else "forbids"
                    )
                    raise CatalogBuildError(
                        f"Binding {binding.binding_id} Metric "
                        f"{metric_definition.metric_id} {requirement} an exact "
                        "Produced Observation axis source"
                    )
                if observation.axis_port is not None:
                    axis_ports = (
                        inputs_by_name
                        if observation.axis_direction == "input"
                        else outputs_by_name
                    )
                    axis_declaration = axis_ports.get(observation.axis_port)
                    axis_type = (
                        axis_declaration.get("port_type")
                        if isinstance(axis_declaration, Mapping)
                        else None
                    )
                    axis_entry = (
                        entry_by_key.get(axis_type.key)
                        if isinstance(axis_type, ContractIdentity)
                        else None
                    )
                    axis_definition = (
                        axis_entry[1] if axis_entry is not None else None
                    )
                    if (
                        not isinstance(axis_type, ContractIdentity)
                        or axis_type.contract_kind != "port_type"
                        or not isinstance(axis_definition, PortTypeDefinition)
                        or axis_definition.scientific_axis_projection is None
                        or axis_definition.runtime_scientific_axis_projection
                        is None
                    ):
                        raise CatalogBuildError(
                            f"Binding {binding.binding_id} Produced Observation "
                            "axis source must use one exact scientific axis Port"
                        )
                if observation.method_port is not None:
                    method_ports = (
                        inputs_by_name
                        if observation.method_direction == "input"
                        else outputs_by_name
                    )
                    method_declaration = method_ports.get(
                        observation.method_port
                    )
                    method_type = (
                        method_declaration.get("port_type")
                        if isinstance(method_declaration, Mapping)
                        else None
                    )
                    method_entry = (
                        entry_by_key.get(method_type.key)
                        if isinstance(method_type, ContractIdentity)
                        else None
                    )
                    method_definition = (
                        method_entry[1] if method_entry is not None else None
                    )
                    if (
                        not isinstance(method_type, ContractIdentity)
                        or method_type.contract_kind != "port_type"
                        or not isinstance(
                            method_definition, PortTypeDefinition
                        )
                        or method_definition.observation_method_projection
                        is None
                        or method_definition.runtime_observation_method_projection
                        is None
                    ):
                        raise CatalogBuildError(
                            f"Binding {binding.binding_id} Produced Observation "
                            "Method source must use one exact Method-projecting "
                            "Port"
                        )
                if observation.reference_port is not None:
                    reference_ports = (
                        inputs_by_name
                        if observation.reference_direction == "input"
                        else outputs_by_name
                    )
                    reference_declaration = reference_ports.get(
                        observation.reference_port
                    )
                    reference_type = (
                        reference_declaration.get("port_type")
                        if isinstance(reference_declaration, Mapping)
                        else None
                    )
                    if (
                        not isinstance(reference_type, ContractIdentity)
                        or reference_type.key
                        != (
                            "port_type",
                            "candidate.collection",
                            CANDIDATE_COLLECTION_PORT_TYPE_VERSION,
                        )
                    ):
                        raise CatalogBuildError(
                            f"Binding {binding.binding_id} Produced "
                            "Observation reference source must use exact "
                            "candidate.collection@"
                            f"{CANDIDATE_COLLECTION_PORT_TYPE_VERSION}"
                        )
                if observation.pairing_port is not None:
                    pairing_ports = (
                        inputs_by_name
                        if observation.pairing_direction == "input"
                        else outputs_by_name
                    )
                    pairing_declaration = pairing_ports.get(
                        observation.pairing_port
                    )
                    pairing_type = (
                        pairing_declaration.get("port_type")
                        if isinstance(pairing_declaration, Mapping)
                        else None
                    )
                    if (
                        not isinstance(pairing_type, ContractIdentity)
                        or pairing_type.key
                        != (
                            "port_type",
                            "candidate.pairing",
                            CANDIDATE_PAIRING_PORT_TYPE_VERSION,
                        )
                    ):
                        raise CatalogBuildError(
                            f"Binding {binding.binding_id} Produced "
                            "Observation pairing source must use exact "
                            "candidate.pairing@"
                            f"{CANDIDATE_PAIRING_PORT_TYPE_VERSION}"
                        )
            propagation = binding.observation_propagation
            if propagation is not None:
                output_declaration = outputs_by_name.get(
                    propagation.output_port
                )
                output_type = (
                    output_declaration.get("port_type")
                    if isinstance(output_declaration, Mapping)
                    else None
                )
                if (
                    not isinstance(output_type, ContractIdentity)
                    or output_type.key
                    != (
                        "port_type",
                        "score.collection",
                        SCORE_COLLECTION_PORT_TYPE_VERSION,
                    )
                ):
                    raise CatalogBuildError(
                        f"Binding {binding.binding_id} Observation "
                        "propagation output must use exact "
                        "score.collection@"
                        f"{SCORE_COLLECTION_PORT_TYPE_VERSION}"
                    )
                if output_declaration.get("multiplicity") != "one":
                    raise CatalogBuildError(
                        f"Binding {binding.binding_id} Observation "
                        "propagation output must use multiplicity one"
                    )
                for input_port in propagation.input_ports:
                    input_declaration = inputs_by_name.get(input_port)
                    input_type = (
                        input_declaration.get("port_type")
                        if isinstance(input_declaration, Mapping)
                        else None
                    )
                    if (
                        not isinstance(input_type, ContractIdentity)
                        or input_type.key
                        != (
                            "port_type",
                            "score.collection",
                            SCORE_COLLECTION_PORT_TYPE_VERSION,
                        )
                    ):
                        raise CatalogBuildError(
                            f"Binding {binding.binding_id} Observation "
                            "propagation inputs must use exact "
                            "score.collection@"
                            f"{SCORE_COLLECTION_PORT_TYPE_VERSION}"
                        )
                    if input_declaration.get("multiplicity") != "one":
                        raise CatalogBuildError(
                            f"Binding {binding.binding_id} Observation "
                            "propagation inputs must use multiplicity one"
                        )
                    if (
                        propagation.absent_input_policy == "ignore"
                        and input_declaration.get("required") is not False
                    ):
                        raise CatalogBuildError(
                            f"Binding {binding.binding_id} Observation "
                            "propagation may ignore only optional inputs"
                        )

    resolved: dict[tuple[str, str, str], CatalogContract] = {}
    resolving: list[tuple[str, str, str]] = []

    def resolve(key: tuple[str, str, str]) -> PortTypeDefinition | CatalogContract:
        if key in resolved:
            return resolved[key]
        entry = entry_by_key.get(key)
        if entry is None:
            raise CatalogBuildError(
                "dangling contract reference "
                f"{key[0]}:{key[1]}@{key[2]}"
            )
        _, definition = entry
        if isinstance(definition, PortTypeDefinition):
            return definition
        if key in resolving:
            cycle = resolving[resolving.index(key):] + [key]
            rendered = " -> ".join(
                f"{kind}:{contract_id}@{version}"
                for kind, contract_id, version in cycle
            )
            raise CatalogBuildError(
                f"cyclic contract reference graph: {rendered}"
            )
        resolving.append(key)

        def resolve_value(value: Any) -> Any:
            if isinstance(value, ContractIdentity):
                target = resolve(value.key)
                reference = (
                    target.reference()
                    if isinstance(target, CatalogContract)
                    else {
                        "contract_kind": "port_type",
                        "contract_id": target.type_id,
                        "contract_version": target.version,
                        "contract_digest": target.contract_digest,
                    }
                )
                if (
                    value.expected_digest is not None
                    and reference["contract_digest"] != value.expected_digest
                ):
                    raise CatalogBuildError(
                        "contract digest conflict for "
                        f"{value.contract_kind}:{value.contract_id}@"
                        f"{value.contract_version}"
                    )
                return reference
            if isinstance(value, Mapping):
                return {
                    name: resolve_value(item)
                    for name, item in value.items()
                }
            if isinstance(value, (list, tuple)):
                return [resolve_value(item) for item in value]
            return value

        descriptor = resolve_value(definition.descriptor_template())
        contract = CatalogContract(
            contract_kind=key[0],  # type: ignore[arg-type]
            contract_id=key[1],
            contract_version=key[2],
            descriptor=descriptor,
        )
        resolving.pop()
        resolved[key] = contract
        return contract

    for key in sorted(entry_by_key):
        resolve(key)

    observation_time = observed_at or datetime.now(timezone.utc)
    observed_at_text = _utc_timestamp(observation_time)
    availability_snapshots: list[dict[str, Any]] = []
    factories: dict[
        tuple[str, str],
        ScientificOperationFactory,
    ] = {}
    readiness: dict[
        tuple[str, str],
        ReadinessDeclaration,
    ] = {}
    effective_randomness_resolvers: dict[
        tuple[str, str],
        EffectiveRandomnessResolver,
    ] = {}
    for key in sorted(bindings_by_key):
        _, binding = bindings_by_key[key]
        contract = resolved[key]
        try:
            availability = binding.availability.check()
        except ExpectedOptionalDependencyMissing as error:
            availability = AvailabilityResult.unavailable(
                "optional_dependency_missing",
                (
                    f"Optional dependency {error.dependency_id} "
                    "is not installed"
                ),
                retryable=False,
            )
        except Exception as error:
            raise CatalogBuildError(
                f"Availability checker for {binding.binding_id} failed"
            ) from error
        if not isinstance(availability, AvailabilityResult):
            raise CatalogBuildError(
                f"Availability checker for {binding.binding_id} returned "
                "an invalid conclusion"
            )
        snapshot = {
            "binding": contract.reference(),
            "observed_at": observed_at_text,
            "available": availability.is_available,
        }
        reason = availability.reason()
        if reason is not None:
            snapshot["reason"] = reason
        availability_snapshots.append(snapshot)
        runtime_key = (binding.binding_id, binding.version)
        factories[runtime_key] = binding.factory
        readiness[runtime_key] = binding.readiness
        if binding.effective_randomness_resolver is not None:
            effective_randomness_resolvers[runtime_key] = (
                binding.effective_randomness_resolver
            )

    owners = {
        key: frozenset(owner_set)
        for key, (owner_set, _) in entry_by_key.items()
    }
    return FrozenCatalog(
        tuple(
            entry
            for _, entry in port_type_entries
        ),
        contracts=tuple(resolved[key] for key in sorted(resolved)),
        availability=tuple(availability_snapshots),
        availability_observed_at=observation_time,
        factories=factories,
        readiness_declarations=readiness,
        effective_randomness_resolvers=effective_randomness_resolvers,
        utility_transforms=utility_runtime,
        owners=owners,
    )


def build_discovered_frozen_catalog(
    modules_package: str = "modules",
    *,
    observed_at: datetime | None = None,
) -> FrozenCatalog:
    """Discover first-level registrations and atomically resolve one Catalog."""
    return build_frozen_catalog(
        discover_module_packages(modules_package),
        observed_at=observed_at,
    )
