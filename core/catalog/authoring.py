"""Startup-frozen authoring roles over one exact scientific Catalog."""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Literal, Mapping, Sequence

from datatypes.exact_reference import ExactContractReference

from .errors import CatalogBuildError
from .model import FrozenCatalog


AuthoringRole = Literal[
    "ordinary_node",
    "specialized_composition",
    "managed_member",
]


@dataclass(frozen=True, slots=True)
class AuthoringSourceKind:
    """One role-labelled source accepted by a specialized editor."""

    source_kind: str
    title: str
    accepted_port_types: tuple[ExactContractReference, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "accepted_port_types",
            tuple(self.accepted_port_types),
        )


@dataclass(frozen=True, slots=True)
class AuthoringRoleEndpoint:
    """One externally connectable role of a specialized composition."""

    role: str
    port_type: ExactContractReference


@dataclass(frozen=True, slots=True)
class AuthoringCapabilityDefinition:
    """One Module Package contribution to the authoring projection."""

    capability_id: str
    title: str
    summary: str
    category: str
    editor_kind: str
    source_kinds: tuple[AuthoringSourceKind, ...]
    exposed_inputs: tuple[AuthoringRoleEndpoint, ...]
    exposed_outputs: tuple[AuthoringRoleEndpoint, ...]
    managed_node_types: tuple[ExactContractReference, ...]
    materialized_node_types: tuple[ExactContractReference, ...]

    def __post_init__(self) -> None:
        for field_name in (
            "source_kinds",
            "exposed_inputs",
            "exposed_outputs",
            "managed_node_types",
            "materialized_node_types",
        ):
            object.__setattr__(
                self,
                field_name,
                tuple(getattr(self, field_name)),
            )


@dataclass(frozen=True, slots=True)
class AuthoringNodeProjection:
    """One exact Node Type's ordinary or managed authoring role."""

    node_type: ExactContractReference
    role: Literal["ordinary_node", "managed_member"]
    capability_id: str | None = None


@dataclass(frozen=True, slots=True)
class AuthoringCapabilityProjection:
    """Immutable non-scientific authoring hierarchy for one startup."""

    capabilities: tuple[AuthoringCapabilityDefinition, ...]
    node_roles: tuple[AuthoringNodeProjection, ...]
    _capabilities_by_id: Mapping[str, AuthoringCapabilityDefinition] = field(
        init=False,
        repr=False,
    )

    def __post_init__(self) -> None:
        capabilities = tuple(
            sorted(self.capabilities, key=lambda item: item.capability_id)
        )
        node_roles = tuple(
            sorted(
                self.node_roles,
                key=lambda item: item.node_type.contract_id,
            )
        )
        object.__setattr__(self, "capabilities", capabilities)
        object.__setattr__(self, "node_roles", node_roles)
        object.__setattr__(
            self,
            "_capabilities_by_id",
            MappingProxyType(
                {item.capability_id: item for item in capabilities}
            ),
        )

    def require_capability(
        self,
        capability_id: str,
    ) -> AuthoringCapabilityDefinition:
        return self._capabilities_by_id[capability_id]


def _require_exact_reference(
    catalog: FrozenCatalog,
    reference: ExactContractReference,
    *,
    contract_kind: str,
) -> None:
    if reference.contract_kind != contract_kind:
        raise CatalogBuildError(
            f"Authoring reference {reference.contract_id} must be a "
            f"{contract_kind}"
        )
    catalog.require_reference(*reference.key)


def build_authoring_capability_projection(
    registrations: Sequence[object],
    catalog: FrozenCatalog,
) -> AuthoringCapabilityProjection:
    """Admit authoring-owned relationships once against one Catalog."""
    capabilities: list[AuthoringCapabilityDefinition] = []
    capability_ids: set[str] = set()
    managed_by_node_type: dict[str, str] = {}
    for registration in registrations:
        for capability in registration.authoring_capabilities:
            if capability.capability_id in capability_ids:
                raise CatalogBuildError(
                    "duplicate Authoring Capability identity "
                    f"{capability.capability_id}"
                )
            capability_ids.add(capability.capability_id)
            allowed = {
                reference.contract_id
                for reference in capability.materialized_node_types
            }
            for reference in capability.materialized_node_types:
                _require_exact_reference(
                    catalog,
                    reference,
                    contract_kind="node_type",
                )
            for reference in capability.managed_node_types:
                _require_exact_reference(
                    catalog,
                    reference,
                    contract_kind="node_type",
                )
                if reference.contract_id not in allowed:
                    raise CatalogBuildError(
                        f"managed Node Type {reference.contract_id} is not "
                        "allowed by its Authoring Capability"
                    )
                previous = managed_by_node_type.get(reference.contract_id)
                if previous is not None:
                    raise CatalogBuildError(
                        f"managed Node Type {reference.contract_id} belongs "
                        f"to both {previous} and {capability.capability_id}"
                    )
                managed_by_node_type[reference.contract_id] = (
                    capability.capability_id
                )
            for source in capability.source_kinds:
                for reference in source.accepted_port_types:
                    _require_exact_reference(
                        catalog,
                        reference,
                        contract_kind="port_type",
                    )
            for endpoint in (
                *capability.exposed_inputs,
                *capability.exposed_outputs,
            ):
                _require_exact_reference(
                    catalog,
                    endpoint.port_type,
                    contract_kind="port_type",
                )
            capabilities.append(capability)

    node_roles = tuple(
        AuthoringNodeProjection(
            node_type=ExactContractReference("node_type", contract.contract_id),
            role=(
                "managed_member"
                if contract.contract_id in managed_by_node_type
                else "ordinary_node"
            ),
            capability_id=managed_by_node_type.get(contract.contract_id),
        )
        for contract in catalog.contracts
        if contract.contract_kind == "node_type"
    )
    return AuthoringCapabilityProjection(tuple(capabilities), node_roles)
