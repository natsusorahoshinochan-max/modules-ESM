"""Test fixture adapter for explicit resolved Catalog dependencies."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import is_dataclass, replace
from datetime import datetime
from types import SimpleNamespace
from typing import Any

from core.catalog.declarations import (
    AvailabilityResult,
    ContractIdentity,
    EffectiveRandomnessResolver,
    EnvironmentFieldDeclaration,
    ReadinessDeclaration,
    ScientificOperationFactory,
)
from core.catalog.model import CatalogAvailabilityProjection, CatalogContract
from core.catalog.port_contract import BehaviorReference
from core.operation import ReadinessResult
from core.parameters.contract import admit_declarations
from datatypes.exact_reference import ExactContractReference


_REFERENCE_FIELDS = {
    "contract_kind",
    "contract_id",
    "contract_version",
    "contract_digest",
}
_AVAILABLE = AvailabilityResult.available()


def _identity(value: Mapping[str, Any]) -> ContractIdentity:
    return ContractIdentity(
        value["contract_kind"],
        value["contract_id"],
        value["contract_version"],
        value.get("contract_digest"),
    )


def _port(value: Mapping[str, Any]) -> SimpleNamespace:
    fields = dict(value)
    fields["port_type"] = _identity(value["port_type"])
    fields.setdefault("required", False)
    fields.setdefault("scientific_meaning", "test value")
    fields.setdefault("artifact_kind", None)
    fields.setdefault("artifact_media_type", None)
    return SimpleNamespace(**fields)


def _factory(contract_id: str) -> ScientificOperationFactory:
    def unconfigured(_context: Any) -> Any:
        raise AssertionError(f"{contract_id} test runtime is not configured")

    return ScientificOperationFactory(
        BehaviorReference(f"test/{contract_id}/factory", "1.0.0", {}),
        unconfigured,
    )


def _readiness(contract_id: str) -> ReadinessDeclaration:
    return ReadinessDeclaration(
        BehaviorReference(f"test/{contract_id}/readiness", "1.0.0", {}),
        {},
        lambda _input: ReadinessResult(True),
    )


def _namespace(value: Mapping[str, Any] | None) -> SimpleNamespace | None:
    if value is None:
        return None
    fields = dict(value)
    fields.setdefault("objective_id_parameter", None)
    fields.setdefault("objective_ids_parameter", None)
    return SimpleNamespace(**fields)


def _updated(value: Any, **changes: Any) -> Any:
    if is_dataclass(value):
        return replace(value, **changes)
    return SimpleNamespace(**{**vars(value), **changes})


def _produced_observation(
    value: Mapping[str, Any],
) -> SimpleNamespace:
    fields = dict(value)
    fields["metric"] = _identity(value["metric"])
    for name in (
        "reference_direction", "reference_port", "pairing_direction",
        "pairing_port", "axis_direction", "axis_port",
        "method_direction", "method_port",
    ):
        fields.setdefault(name, None)
    return SimpleNamespace(**fields)


def _propagation(
    value: Mapping[str, Any] | None,
) -> SimpleNamespace | None:
    if value is None:
        return None
    filter_value = value.get("filter")
    return SimpleNamespace(
        mode=value["mode"],
        output_port=value["output_port"],
        input_ports=tuple(value["input_ports"]),
        filter=(
            None
            if filter_value is None
            else {
                **filter_value,
                **{
                    name: _identity(filter_value[name])
                    for name in ("metric", "method")
                    if filter_value.get(name) is not None
                },
            }
        ),
        absent_input_policy=value.get("absent_input_policy", "reject"),
    )


def catalog_contract(
    contract_kind: str,
    contract_id: str,
    contract_version: str,
    descriptor: Mapping[str, Any],
    *,
    environment_fields: tuple[EnvironmentFieldDeclaration, ...] = (),
) -> CatalogContract:
    """Build one test-owned typed definition from an admitted descriptor."""
    parameter_field = {
        "node_type": "node_parameters",
        "binding": "binding_parameters",
        "utility_transform": "parameters",
    }.get(contract_kind)
    parameter_contract = admit_declarations(
        descriptor.get(parameter_field, {}) if parameter_field else {},
        path=f"test:{contract_kind}:{contract_id}.{parameter_field or 'none'}",
    )
    if contract_kind == "node_type":
        definition = SimpleNamespace(
            identity=ContractIdentity(
                "node_type",
                contract_id,
                contract_version,
            ),
            inputs=tuple(_port(value) for value in descriptor.get("inputs", ())),
            outputs=tuple(_port(value) for value in descriptor.get("outputs", ())),
            input_constraints=tuple(
                tuple(value["ports"])
                for value in descriptor.get("input_constraints", ())
            ),
            parameter_contract=parameter_contract,
        )
    elif contract_kind == "metric":
        aggregation = descriptor.get("aggregation_semantics", {"kind": "none"})
        shape = descriptor["value_shape"]
        definition = SimpleNamespace(
            value_shape=shape,
            canonical_range=descriptor["canonical_range"],
            aggregation_semantics=aggregation,
            validation_contract=descriptor.get(
                "validation_contract",
                {"finite": True},
            ),
            requires_residue_axis=(
                shape in {"per_residue", "residue_vector", "residue_pair_matrix"}
                or (
                    shape == "scalar"
                    and aggregation.get("kind") not in (None, "none")
                    and bool(aggregation.get("source_metric"))
                )
            ),
        )
    elif contract_kind == "method":
        definition = SimpleNamespace()
    elif contract_kind == "utility_transform":
        compatible = dict(descriptor["compatible_input_contract"])
        for name in ("metric", "method"):
            if compatible.get(name) is not None:
                compatible[name] = _identity(compatible[name])
        definition = SimpleNamespace(
            compatible_input_contract=compatible,
            parameter_contract=parameter_contract,
            transform=lambda value, _parameters: float(value),
        )
    else:
        fields = dict(descriptor)
        fields.update(
            node_type=_identity(descriptor["node_type"]),
            method=_identity(descriptor["method"]),
            parameter_contract=parameter_contract,
            execution_route=descriptor.get("execution_route", "direct"),
            cacheable=descriptor.get("cacheable", False),
            deterministic=descriptor.get("deterministic", True),
            factory=_factory(contract_id), readiness=_readiness(contract_id),
            effective_randomness_resolver=None,
            effective_randomness_parameters=tuple(
                descriptor.get("effective_randomness_parameters", ())
            ),
            produced_observations=tuple(
                _produced_observation(value)
                for value in descriptor.get("produced_observations", ())
            ),
            observation_propagation=_propagation(
                descriptor.get("observation_propagation")
            ),
            selection_objective_consumption=_namespace(
                descriptor.get("selection_objective_consumption")
            ),
            observation_selector_consumption=_namespace(
                descriptor.get("observation_selector_consumption")
            ),
            environment_fields=environment_fields,
        )
        definition = SimpleNamespace(**fields)
    return CatalogContract(
        contract_kind=contract_kind,
        contract_id=contract_id,
        contract_version=contract_version,
        descriptor=descriptor,
        dependencies=resolved_dependencies(descriptor),
        definition=definition,  # type: ignore[arg-type]
    )


def install_runtime(
    contracts: tuple[CatalogContract, ...],
    *,
    factories: Mapping[
        tuple[str, str], ScientificOperationFactory
    ] | None = None,
    readiness: Mapping[
        tuple[str, str], ReadinessDeclaration
    ] | None = None,
    randomness: Mapping[
        tuple[str, str], EffectiveRandomnessResolver
    ] | None = None,
    utility_transforms: Mapping[tuple[str, str], Any] | None = None,
) -> tuple[CatalogContract, ...]:
    """Install test runtime behavior into typed definitions before freezing."""
    factories = factories or {}
    readiness = readiness or {}
    randomness = randomness or {}
    utility_transforms = utility_transforms or {}
    installed = []
    for contract in contracts:
        key = (contract.contract_id, contract.contract_version)
        definition = contract.definition
        if contract.contract_kind == "binding":
            definition = _updated(
                definition,
                factory=factories.get(key, definition.factory),
                readiness=readiness.get(key, definition.readiness),
                effective_randomness_resolver=randomness.get(
                    key,
                    definition.effective_randomness_resolver,
                ),
            )
        elif contract.contract_kind == "utility_transform":
            definition = _updated(
                definition,
                transform=utility_transforms.get(key, definition.transform),
            )
        installed.append(replace(contract, definition=definition))
    return tuple(installed)


def binding_availability(
    binding: CatalogContract,
    observed_at: datetime,
    result: AvailabilityResult = _AVAILABLE,
) -> CatalogAvailabilityProjection:
    return CatalogAvailabilityProjection(
        ExactContractReference(**binding.reference()),
        observed_at,
        result,
    )


def resolved_dependencies(value: Any) -> tuple[ExactContractReference, ...]:
    references: dict[tuple[str, str, str], ExactContractReference] = {}
    pending = [value]
    while pending:
        current = pending.pop()
        if isinstance(current, Mapping) and set(current) == _REFERENCE_FIELDS:
            reference = ExactContractReference(**current)
            references[reference.key] = reference
        elif isinstance(current, Mapping):
            pending.extend(current.values())
        elif isinstance(current, (list, tuple)):
            pending.extend(current)
    return tuple(references[key] for key in sorted(references))
