"""Atomic Catalog construction from explicit immutable registrations."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from typing import Any

from .builtins import builtin_port_types as repository_builtin_port_types
from .declarations import (
    CatalogDefinition,
    ContractIdentity,
    ExecutionBindingDefinition,
    MetricDefinition,
    NodeTypeDefinition,
    ModulePackageRegistration,
    ObservationPropagationDefinition,
    ProducedObservationDefinition,
    UtilityTransformDefinition,
    _SCIENTIFIC_COLLECTION_PORT_TYPE_VERSIONS,
    _require_identifier,
    _require_version,
)
from .definition_resource import (
    _load_definition_resource,
)
from .model import CatalogAvailabilityProjection, CatalogContract, FrozenCatalog
from core.catalog.errors import CatalogBuildError
from core.catalog.canonical import canonical_json_bytes
from .port_contract import (
    CANDIDATE_COLLECTION_PORT_TYPE_VERSION,
    CANDIDATE_PAIRING_PORT_TYPE_VERSION,
    SCORE_COLLECTION_PORT_TYPE_VERSION,
    PortTypeDefinition,
    _require_single_active_contract_version,
)
from datatypes.exact_reference import ExactContractReference


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
    definition: CatalogDefinition,
) -> ContractIdentity:
    return definition.identity


def _utc_observation_time(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise CatalogBuildError("Catalog observation time must be timezone-aware")
    return value.astimezone(timezone.utc)


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


def _validate_binding_relationships(
    binding: ExecutionBindingDefinition,
) -> None:
    environment_names = [item.name for item in binding.environment_fields]
    if len(set(environment_names)) != len(environment_names):
        raise CatalogBuildError("Environment field names must be unique")
    randomness = binding.effective_randomness_parameters
    if len(set(randomness)) != len(randomness):
        raise CatalogBuildError("effective randomness parameters must be unique")
    if binding.effective_randomness_resolver is not None and not randomness:
        raise CatalogBuildError(
            "effective randomness resolver requires declared parameters"
        )
    route_is_complete = (
        binding.execution_route == "adapter"
        and binding.adapter_behavior is not None
    ) or (
        binding.execution_route == "direct"
        and binding.adapter_behavior is None
    )
    if not route_is_complete:
        raise CatalogBuildError(
            "execution route and Adapter behavior are inconsistent"
        )
    if binding.produced_observations and binding.observation_propagation:
        raise CatalogBuildError(
            "fixed Produced Observations and propagation are mutually exclusive"
        )
    identities = {
        (
            item.output_port,
            item.output_partition,
            item.metric.key,
            canonical_json_bytes(_template_json(item.context_profile)),
        )
        for item in binding.produced_observations
    }
    if len(identities) != len(binding.produced_observations):
        raise CatalogBuildError("duplicate Produced Observation declaration")


def _validate_produced_observation_relationships(
    observation: ProducedObservationDefinition,
) -> None:
    _require_identifier(observation.output_partition, "output_partition")
    if observation.guaranteed_multiplicity not in {
        "one",
        "one_or_more",
        "zero_or_more",
    }:
        raise CatalogBuildError("unknown Produced Observation multiplicity")
    sources = (
        (observation.reference_direction, observation.reference_port),
        (observation.pairing_direction, observation.pairing_port),
        (observation.axis_direction, observation.axis_port),
        (observation.method_direction, observation.method_port),
    )
    if any(
        (direction is None) != (port is None)
        or direction not in {None, "input", "output"}
        for direction, port in sources
    ):
        raise CatalogBuildError(
            "Produced Observation source direction and Port must be paired"
        )
    context_kind = observation.context_profile.get("kind")
    if (context_kind == "pairwise") != (
        observation.reference_port is not None
    ):
        raise CatalogBuildError(
            "Produced Observation reference contradicts its Context"
        )
    per_subject = (
        context_kind == "pairwise"
        and observation.context_profile.get("pairing_mode")
        == "per_subject_counterpart"
    )
    if per_subject != (observation.pairing_port is not None):
        raise CatalogBuildError(
            "Produced Observation pairing contradicts its Context"
        )


def _validate_propagation_relationships(
    propagation: ObservationPropagationDefinition,
) -> None:
    inputs = propagation.input_ports
    valid_count = (
        propagation.mode in {"pass_through", "filter"} and len(inputs) == 1
    ) or (propagation.mode == "union" and len(inputs) >= 2)
    if len(set(inputs)) != len(inputs) or not valid_count:
        raise CatalogBuildError(
            "Observation propagation mode requires unique input Ports"
        )
    if propagation.absent_input_policy not in {"reject", "ignore"} or (
        propagation.absent_input_policy == "ignore"
        and propagation.mode != "union"
    ):
        raise CatalogBuildError("invalid Observation propagation absence policy")
    filter_definition = propagation.filter
    if propagation.mode != "filter":
        if filter_definition is not None:
            raise CatalogBuildError("only filter propagation accepts a filter")
        return
    if not filter_definition or set(filter_definition) - {
        "source_partition",
        "metric",
        "method",
        "context_profile",
    }:
        raise CatalogBuildError("Observation propagation filter is not closed")
    source_partition = filter_definition.get("source_partition")
    if source_partition is not None:
        _require_identifier(source_partition, "filter source_partition")
    for name, contract_kind in (("metric", "metric"), ("method", "method")):
        reference = filter_definition.get(name)
        if reference is not None and (
            not isinstance(reference, ContractIdentity)
            or reference.contract_kind != contract_kind
        ):
            raise CatalogBuildError(
                f"Observation propagation filter {name} must be exact"
            )
    context = filter_definition.get("context_profile")
    if context is not None and not isinstance(context, Mapping):
        raise CatalogBuildError(
            "Observation propagation Context filter must be an object"
        )


def build_frozen_catalog(
    registrations: Sequence[ModulePackageRegistration],
    *,
    builtin_port_types: Sequence[PortTypeDefinition] | None = None,
    observed_at: datetime | None = None,
) -> FrozenCatalog:
    """Validate all registrations in temporary state, then return one Catalog."""
    registration_tuple = tuple(registrations)
    package_identities: set[tuple[str, str]] = set()
    for registration in registration_tuple:
        _require_identifier(registration.package_id, "package_id")
        _require_version(registration.package_version, "package_version")
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
        else repository_builtin_port_types()
    )
    port_type_entries: list[tuple[str, PortTypeDefinition]] = [
        ("protein-workbench.core", definition)
        for definition in port_types
    ]
    definitions: list[tuple[str, CatalogDefinition]] = []
    loaded_resources: set[tuple[str, str]] = set()
    bindings_by_key: dict[
        tuple[str, str, str],
        tuple[str, ExecutionBindingDefinition],
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

    entry_by_key: dict[
        tuple[str, str, str],
        tuple[set[str], PortTypeDefinition | CatalogDefinition],
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
        port_type.validate_runtime_contract()
        entry_by_key[key] = ({owner}, port_type)
        template_by_key[key] = fingerprint

    for owner, definition in definitions:
        identity = _definition_identity(definition)
        _require_identifier(
            identity.contract_id,
            f"{identity.contract_kind}_id",
        )
        _require_version(
            identity.contract_version,
            f"{identity.contract_kind} version",
        )
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
        if not isinstance(definition, NodeTypeDefinition):
            continue
        for output in definition.outputs:
            reference = output.port_type
            port_entry = entry_by_key.get(reference.key)
            port_type = port_entry[1] if port_entry is not None else None
            if (
                isinstance(port_type, PortTypeDefinition)
                and port_type.artifact_media_types is not None
                and output.artifact_kind is None
            ):
                raise CatalogBuildError(
                    f"Node {definition.node_type_id} artifact-capable output "
                    f"{output.name!r} requires explicit publication intent"
                )
            if output.artifact_kind is None:
                continue
            if (
                not isinstance(port_type, PortTypeDefinition)
                or port_type.artifact_media_types is None
            ):
                raise CatalogBuildError(
                    f"Node {definition.node_type_id} artifact output "
                    f"{output.name!r} requires a Port Type with an exact "
                    "generic artifact publication contract"
                )
            artifact_media_type = output.artifact_media_type
            if (
                not isinstance(artifact_media_type, str)
                or artifact_media_type
                not in port_type.artifact_media_types
            ):
                raise CatalogBuildError(
                    f"Node {definition.node_type_id} artifact output "
                    f"{output.name!r} requires one exact media type "
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
            if not isinstance(node_definition, NodeTypeDefinition):
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
            _validate_binding_relationships(binding)
            output_names = {output.name for output in node_definition.outputs}
            input_names = {input_port.name for input_port in node_definition.inputs}
            outputs_by_name = {
                output.name: output
                for output in node_definition.outputs
            }
            inputs_by_name = {
                input_port.name: input_port
                for input_port in node_definition.inputs
            }
            consumption = binding.selection_objective_consumption
            if consumption is not None:
                if (consumption.objective_id_parameter is None) == (
                    consumption.objective_ids_parameter is None
                ):
                    raise CatalogBuildError(
                        f"Binding {binding.binding_id} Selection Objective "
                        "consumption requires exactly one selector parameter"
                    )
                selector_parameter = (
                    consumption.objective_id_parameter
                    if consumption.objective_id_parameter is not None
                    else consumption.objective_ids_parameter
                )
                parameter = node_definition.parameter_contract.get(
                    selector_parameter
                )
                value_contract = (
                    parameter.value_contract if parameter is not None else {}
                )
                scalar_selector = (
                    consumption.objective_id_parameter is not None
                    and value_contract.get("type") == "string"
                )
                ordered_selector = (
                    consumption.objective_ids_parameter is not None
                    and value_contract.get("type") == "array"
                    and isinstance(
                        value_contract.get("items"),
                        Mapping,
                    )
                    and value_contract["items"].get("type") == "string"
                    and value_contract.get("minItems", 0) >= 1
                    and value_contract.get("uniqueItems") is True
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
                    reference = port.port_type if port is not None else None
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
                        or port.multiplicity != "one"
                        or port.required is not True
                    ):
                        raise CatalogBuildError(
                            f"Binding {binding.binding_id} {field_name} must "
                            f"name one required {expected_type} input Port"
                        )
                output = outputs_by_name.get(
                    consumption.candidate_output_port
                )
                output_reference = output.port_type if output is not None else None
                if (
                    not isinstance(output_reference, ContractIdentity)
                    or output_reference.key
                    != (
                        "port_type",
                        "candidate.collection",
                        CANDIDATE_COLLECTION_PORT_TYPE_VERSION,
                    )
                    or output.multiplicity != "one"
                    or output.required is not True
                ):
                    raise CatalogBuildError(
                        f"Binding {binding.binding_id} "
                        "candidate_output_port must name one required "
                        "candidate.collection output Port"
                    )
            for observation in binding.produced_observations:
                _validate_produced_observation_relationships(observation)
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
                ].port_type
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
                subject_reference = subject_declaration.port_type
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
                if not isinstance(metric_definition, MetricDefinition):
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
                        axis_declaration.port_type
                        if axis_declaration is not None
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
                        method_declaration.port_type
                        if method_declaration is not None
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
                        reference_declaration.port_type
                        if reference_declaration is not None
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
                        pairing_declaration.port_type
                        if pairing_declaration is not None
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
                _validate_propagation_relationships(propagation)
                output_declaration = outputs_by_name.get(
                    propagation.output_port
                )
                output_type = (
                    output_declaration.port_type
                    if output_declaration is not None
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
                if output_declaration.multiplicity != "one":
                    raise CatalogBuildError(
                        f"Binding {binding.binding_id} Observation "
                        "propagation output must use multiplicity one"
                    )
                for input_port in propagation.input_ports:
                    input_declaration = inputs_by_name.get(input_port)
                    input_type = (
                        input_declaration.port_type
                        if input_declaration is not None
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
                    if input_declaration.multiplicity != "one":
                        raise CatalogBuildError(
                            f"Binding {binding.binding_id} Observation "
                            "propagation inputs must use multiplicity one"
                        )
                    if (
                        propagation.absent_input_policy == "ignore"
                        and input_declaration.required is not False
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
        dependencies: dict[
            tuple[str, str, str],
            ExactContractReference,
        ] = {}

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
                exact_reference = ExactContractReference(**reference)
                if (
                    value.expected_digest is not None
                    and exact_reference.contract_digest != value.expected_digest
                ):
                    raise CatalogBuildError(
                        "contract digest conflict for "
                        f"{value.contract_kind}:{value.contract_id}@"
                        f"{value.contract_version}"
                    )
                dependencies[exact_reference.key] = exact_reference
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
            dependencies=tuple(
                dependencies[identity]
                for identity in sorted(dependencies)
            ),
            definition=definition,
        )
        resolving.pop()
        resolved[key] = contract
        return contract

    for key in sorted(entry_by_key):
        resolve(key)

    observation_time = _utc_observation_time(
        observed_at or datetime.now(timezone.utc)
    )
    availability_snapshots: list[CatalogAvailabilityProjection] = []
    for key in sorted(bindings_by_key):
        _, binding = bindings_by_key[key]
        contract = resolved[key]
        availability = binding.availability.check()
        availability_snapshots.append(
            CatalogAvailabilityProjection(
                binding=ExactContractReference(
                    contract.contract_kind,
                    contract.contract_id,
                    contract.contract_version,
                    contract.contract_digest,
                ),
                observed_at=observation_time,
                result=availability,
            )
        )
    return FrozenCatalog(
        tuple(
            entry
            for _, entry in port_type_entries
        ),
        contracts=tuple(resolved[key] for key in sorted(resolved)),
        availability=tuple(availability_snapshots),
        availability_observed_at=observation_time,
    )
