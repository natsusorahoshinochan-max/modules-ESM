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
from typing import Any, Literal

import yaml

from core.port_types import (
    CONTRACT_NAMESPACE,
    BehaviorReference,
    CatalogBuildError,
    FrozenCatalog,
    PortTypeDefinition,
    builtin_frozen_catalog,
    canonical_json_bytes,
)


MODULE_PACKAGE_SCHEMA_VERSION = "2.0.0"
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
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:/+-]{0,127}$")
_SEMANTIC_VERSION = re.compile(
    r"^[0-9]+\.[0-9]+\.[0-9]+(?:-[0-9A-Za-z.-]+)?$"
)
_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_DEFINITION_RESOURCE_SUFFIXES = frozenset({".yaml", ".yml"})
_NON_PRODUCTION_RESOURCE_PARTS = frozenset(
    {"fixture", "fixtures", "test", "tests"}
)


class ModulePackageDiscoveryError(CatalogBuildError):
    """A first-level Module Package did not expose one valid registration."""


def _require_identifier(value: str, field_name: str) -> None:
    if not isinstance(value, str) or _IDENTIFIER.fullmatch(value) is None:
        raise CatalogBuildError(f"{field_name} must be a versioned identifier")


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
class LazyImplementationFactory:
    """Private lazy constructor paired with a stable public behavior identity."""

    behavior: BehaviorReference
    build: Callable[..., Any] = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if not callable(self.build):
            raise CatalogBuildError("lazy implementation factory must be callable")


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
    check: Callable[[Mapping[str, Any]], Any] = field(
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

    def descriptor_template(self) -> dict[str, Any]:
        return {
            "output_port": self.output_port,
            "metric": self.metric,
            "context_profile": self.context_profile,
            "subject_grain": self.subject_grain,
            "source_role": self.source_role,
            "subject_direction": self.subject_direction,
            "subject_port": self.subject_port,
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
    factory: LazyImplementationFactory
    availability: AvailabilityDeclaration
    readiness: ReadinessDeclaration
    deterministic: bool
    cacheable: bool
    implementation_identity: Mapping[str, Any]
    produced_observations: tuple[ProducedObservationDefinition, ...] = ()
    adapter_behavior: BehaviorReference | None = None
    observation_propagation: BehaviorReference | None = None

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
        if len(
            {
                (
                    observation.output_port,
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
        if self.observation_propagation is not None:
            implementation_identity["observation_propagation"] = (
                self.observation_propagation.descriptor()
            )
        return {
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
        }


@dataclass(frozen=True, slots=True)
class _NodeDefinition:
    node_type_id: str
    version: str
    title: str
    summary: str
    category: str
    inputs: tuple[Mapping[str, Any], ...]
    outputs: tuple[Mapping[str, Any], ...]
    parameter_groups: tuple[Any, ...]
    node_parameters: Mapping[str, Any]

    @property
    def identity(self) -> ContractIdentity:
        return ContractIdentity("node_type", self.node_type_id, self.version)

    def descriptor_template(self) -> dict[str, Any]:
        return {
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
    if artifact_kind is not None and (
        not allow_artifact_publication
        or artifact_kind != "standalone"
        or reference.contract_id
        not in {"file.path", "file.path.collection"}
    ):
        raise CatalogBuildError(
            f"{resource_name}.artifact_kind requires a standalone file output"
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
        allowed=required,
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
            for observation in binding.produced_observations:
                if observation.output_port not in output_names:
                    raise CatalogBuildError(
                        f"Binding {binding.binding_id} Produced Observation "
                        f"references unknown Node output Port "
                        f"{observation.output_port!r}"
                    )
                output_reference = outputs_by_name[
                    observation.output_port
                ]["port_type"]
                if (
                    not isinstance(output_reference, ContractIdentity)
                    or output_reference.key
                    != ("port_type", "score.collection", "2.0.0")
                ):
                    raise CatalogBuildError(
                        f"Binding {binding.binding_id} Produced Observation "
                        "output must use exact score.collection@2.0.0"
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
                    != ("port_type", "candidate.collection", "2.0.0")
                ):
                    raise CatalogBuildError(
                        f"Binding {binding.binding_id} Produced Observation "
                        "subject must use exact candidate.collection@2.0.0 "
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
        LazyImplementationFactory,
    ] = {}
    readiness: dict[
        tuple[str, str],
        ReadinessDeclaration,
    ] = {}
    for key in sorted(bindings_by_key):
        _, binding = bindings_by_key[key]
        contract = resolved[key]
        try:
            availability = binding.availability.check()
        except ModuleNotFoundError as error:
            availability = AvailabilityResult.unavailable(
                "optional_dependency_missing",
                (
                    f"Optional dependency {error.name or 'unknown'} "
                    "is not installed"
                ),
                retryable=False,
            )
        except Exception as error:
            availability = AvailabilityResult.unavailable(
                "availability_check_failed",
                f"Availability check failed safely: {type(error).__name__}",
                retryable=True,
            )
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
