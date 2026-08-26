"""Explicit package-local YAML Definition resource admission."""

from __future__ import annotations

from dataclasses import dataclass
from importlib import resources
from typing import Any, Literal

import yaml

from .declarations import (
    CatalogDefinition,
    ContractIdentity,
    MethodDefinition,
    MetricDefinition,
    ModulePackageRegistration,
    NodePortDefinition,
    NodeTypeDefinition,
    _admit_parameter_declarations,
    _freeze_declaration,
    _require_identifier,
)
from core.catalog.errors import CatalogBuildError
from .port_contract import is_valid_artifact_media_type


_METRIC_VALUE_SHAPES = {
    "scalar",
    "per_residue",
    "residue_vector",
    "residue_pair_matrix",
}
_ALIGNMENT_CONTEXT_FIELDS = (
    "evidence_content_digest",
    "evidence_method",
    "subject_axis_content_digest",
    "reference_axis_content_digest",
    "normalization_length",
    "aligned_atom_count",
)


@dataclass(frozen=True, slots=True)
class DefinitionResource:
    """One explicitly named package-local YAML Definition resource."""

    resource: str


def load_method_definitions(
    package_module: str,
    resource: str,
) -> tuple[MethodDefinition, ...]:
    """Load repository-owned Method declarations from one package resource."""
    content = resources.files(package_module).joinpath(resource).read_text(
        encoding="utf-8"
    )
    return tuple(
        MethodDefinition(**item)
        for item in yaml.safe_load(content)
    )


def _required_object(
    raw: Any,
    *,
    resource_name: str,
    required: set[str],
) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise CatalogBuildError(f"{resource_name} must contain one YAML object")
    missing = required - set(raw)
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
) -> NodePortDefinition:
    port = _required_object(
        raw,
        resource_name=resource_name,
        required={
            "name",
            "port_type_id",
            "required",
            "multiplicity",
            "scientific_meaning",
        },
    )
    _require_identifier(port["name"], f"{resource_name}.name")
    reference = ContractIdentity(
        "port_type",
        port["port_type_id"],
    )
    if type(port["required"]) is not bool:
        raise CatalogBuildError(f"{resource_name}.required must be boolean")
    if port["multiplicity"] not in {"one", "many"}:
        raise CatalogBuildError(
            f"{resource_name}.multiplicity must be one or many"
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
    return NodePortDefinition(
        name=port["name"],
        port_type=reference,
        required=port["required"],
        multiplicity=port["multiplicity"],
        scientific_meaning=port["scientific_meaning"],
        artifact_kind=artifact_kind,
        artifact_media_type=artifact_media_type,
    )


def _parse_node_definition(raw: Any, resource_name: str) -> NodeTypeDefinition:
    required = {
        "node_type_id",
        "title",
        "summary",
        "category",
        "inputs",
        "outputs",
        "parameter_groups",
        "node_parameters",
    }
    node = _required_object(
        raw,
        resource_name=resource_name,
        required=required,
    )
    _require_identifier(node["node_type_id"], "node_type_id")
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
        names = [port.name for port in ports]
        if len(set(names)) != len(names):
            raise CatalogBuildError(f"duplicate Node {label} Port name")
    input_names = {port.name for port in inputs}
    raw_input_constraints = node.get("input_constraints", [])
    if not isinstance(raw_input_constraints, list):
        raise CatalogBuildError("input_constraints must be an array")
    input_constraints: list[tuple[str, ...]] = []
    constrained_ports: set[str] = set()
    for index, raw_constraint in enumerate(raw_input_constraints):
        constraint = _required_object(
            raw_constraint,
            resource_name=f"{resource_name}.input_constraints[{index}]",
            required={"kind", "ports"},
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
        input_constraints.append(tuple(ports))
    parameter_contract = _admit_parameter_declarations(
        node["node_parameters"],
        path=f"node_type:{node['node_type_id']}.node_parameters",
    )
    return NodeTypeDefinition(
        node_type_id=node["node_type_id"],
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


def _parse_metric_definition(raw: Any, resource_name: str) -> MetricDefinition:
    required = {
        "metric_id",
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
    metric = _required_object(
        raw,
        resource_name=resource_name,
        required=required,
    )
    _require_identifier(metric["metric_id"], "metric_id")
    if not isinstance(metric["unit"], str) or not metric["unit"]:
        raise CatalogBuildError("Metric Definition unit must be non-empty")
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
    if metric["value_shape"] not in _METRIC_VALUE_SHAPES:
        raise CatalogBuildError("Metric Definition value_shape is unsupported")
    canonical_range = metric["canonical_range"]
    if any(
        type(canonical_range.get(bound)) not in {int, float}
        for bound in ("minimum", "maximum")
    ):
        raise CatalogBuildError("Metric canonical_range requires numeric bounds")
    validation = metric["validation_contract"]
    alignment = validation.get("structure_alignment_evidence")
    if alignment is not None and (
        not isinstance(alignment, dict)
        or set(alignment)
        != {
            "source_direction",
            "source_port",
            "normalization_length_source",
            "required_context_fields",
        }
        or alignment["source_direction"] != "input"
        or type(alignment["source_port"]) is not str
        or not alignment["source_port"]
        or alignment["normalization_length_source"]
        not in {"aligned_atom_count", "reference_axis_residue_count"}
        or not isinstance(
            alignment["required_context_fields"],
            (list, tuple),
        )
        or tuple(alignment["required_context_fields"])
        != _ALIGNMENT_CONTEXT_FIELDS
    ):
        raise CatalogBuildError(
            "Metric structure_alignment_evidence contract is invalid"
        )
    if validation.get("masking") is not None and not isinstance(
        validation["masking"],
        dict,
    ):
        raise CatalogBuildError("Metric masking contract must be an object")
    return MetricDefinition(
        metric_id=metric["metric_id"],
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
) -> CatalogDefinition:
    content = (
        resources.files(registration.package_module)
        .joinpath(resource_reference.resource)
        .read_text(encoding="utf-8")
    )
    try:
        raw = yaml.safe_load(content)
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
