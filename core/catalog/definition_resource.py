"""Explicit package-local YAML Definition resource admission."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from importlib import resources
from pathlib import PurePosixPath
from types import MappingProxyType
from typing import Any, Literal

import yaml

from core.parameters.model import ParameterContract

from .declarations import (
    ContractIdentity,
    ExecutionBindingDefinition,
    MethodDefinition,
    ModulePackageRegistration,
    UtilityTransformDefinition,
    _admit_parameter_declarations,
    _freeze_declaration,
    _require_identifier,
    _require_schema_version,
    _require_version,
)
from .port_contract import (
    CONTRACT_NAMESPACE,
    CatalogBuildError,
    is_valid_artifact_media_type,
)


_DEFINITION_RESOURCE_SUFFIXES = frozenset({".yaml", ".yml"})
_NON_PRODUCTION_RESOURCE_PARTS = frozenset(
    {"fixture", "fixtures", "test", "tests"}
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
    parameter_contract = _admit_parameter_declarations(
        node["node_parameters"],
        path=f"node_type:{node['node_type_id']}@{node['version']}.node_parameters",
    )
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
        parameter_contract=parameter_contract,
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
