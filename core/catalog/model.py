"""Immutable Catalog model, exact lookup, and typed projection."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from types import MappingProxyType
from typing import Any

from datatypes.exact_reference import ExactContractReference

from .declarations import (
    AvailabilityResult,
    CatalogDefinition,
    ContractKind,
    _freeze_declaration,
)
from core.catalog.errors import (
    CatalogBuildError,
    UnknownPortTypeError,
    UnknownContractError,
)
from .port_contract import PortTypeDefinition


_NON_SCIENTIFIC_CONTRACT_FIELDS = {
    "node_type": frozenset(
        {"title", "summary", "category", "parameter_groups"}
    ),
    "metric": frozenset({"title", "description"}),
}
_INTERNAL_CONTRACT_FIELDS = frozenset(
    {"schema_namespace", "contract_kind", "contract_id"}
)


def _result_identity_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            key: _result_identity_value(item)
            for key, item in value.items()
        }
    if isinstance(value, tuple):
        return [_result_identity_value(item) for item in value]
    return value


@dataclass(frozen=True, slots=True)
class CatalogAvailabilityProjection:
    """Typed observation for one exact Binding contract."""

    binding: ExactContractReference
    observed_at: datetime
    result: AvailabilityResult


@dataclass(frozen=True, slots=True)
class CatalogContractProjection:
    """Provider-independent identity and canonical scientific descriptor."""

    reference: ExactContractReference
    descriptor: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class CatalogProjection:
    """Typed stable contracts and observed Binding availability."""

    contracts: tuple[CatalogContractProjection, ...]
    availability_observed_at: datetime
    availability: tuple[CatalogAvailabilityProjection, ...]


@dataclass(frozen=True, slots=True)
class CatalogContract:
    """One resolved contract and its Builder-admitted typed definition."""

    contract_kind: ContractKind
    contract_id: str
    descriptor: Mapping[str, Any]
    dependencies: tuple[ExactContractReference, ...] = field(repr=False)
    definition: CatalogDefinition = field(repr=False)
    result_identity_descriptor: Mapping[str, Any] = field(
        init=False,
        repr=False,
    )

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "descriptor",
            _freeze_declaration(self.descriptor),
        )
        object.__setattr__(self, "dependencies", tuple(self.dependencies))
        object.__setattr__(
            self,
            "result_identity_descriptor",
            _freeze_declaration(
                {
                    "contract_kind": self.contract_kind,
                    "contract_id": self.contract_id,
                    "descriptor": _result_identity_value(
                        {
                            key: value
                            for key, value in self.descriptor.items()
                            if key
                            not in _INTERNAL_CONTRACT_FIELDS
                            | _NON_SCIENTIFIC_CONTRACT_FIELDS.get(
                                self.contract_kind, frozenset()
                            )
                        }
                    ),
                }
            ),
        )

    def reference(self) -> dict[str, Any]:
        return {
            "contract_kind": self.contract_kind,
            "contract_id": self.contract_id,
        }


def result_identity_contract(
    contract: PortTypeDefinition | CatalogContract,
) -> Mapping[str, Any]:
    """Return Catalog-owned identity facts without presentation or digests."""
    if isinstance(contract, CatalogContract):
        return contract.result_identity_descriptor
    return _freeze_declaration(
        {
            "contract_kind": "port_type",
            "contract_id": contract.type_id,
            "descriptor": _result_identity_value(
                {
                    key: value
                    for key, value in contract.canonical_descriptor.items()
                    if key not in _INTERNAL_CONTRACT_FIELDS
                }
            ),
        }
    )


@dataclass(frozen=True, slots=True)
class FrozenCatalog:
    """Immutable indexes over Catalog Builder output."""

    port_types: tuple[PortTypeDefinition, ...]
    contracts: tuple[CatalogContract, ...]
    availability: tuple[CatalogAvailabilityProjection, ...]
    availability_observed_at: datetime
    _by_identity: Mapping[str, PortTypeDefinition] = field(
        init=False,
        repr=False,
    )
    _contracts_by_identity: Mapping[
        tuple[str, str], CatalogContract
    ] = field(
        init=False,
        repr=False,
    )

    def __post_init__(self) -> None:
        ordered = tuple(
            sorted(
                self.port_types,
                key=lambda item: item.type_id,
            )
        )
        resolved = {
            definition.type_id: definition
            for definition in ordered
        }
        object.__setattr__(self, "port_types", ordered)
        object.__setattr__(self, "_by_identity", MappingProxyType(resolved))
        ordered_contracts = tuple(
            sorted(
                self.contracts,
                key=lambda item: (
                    item.contract_kind,
                    item.contract_id,
                ),
            )
        )
        contracts_by_identity = {
            (
                contract.contract_kind,
                contract.contract_id,
            ): contract
            for contract in ordered_contracts
        }
        object.__setattr__(self, "contracts", ordered_contracts)
        object.__setattr__(
            self,
            "_contracts_by_identity",
            MappingProxyType(contracts_by_identity),
        )
        object.__setattr__(self, "availability", tuple(self.availability))

    def _contract_projections(self) -> tuple[CatalogContractProjection, ...]:
        projected = [
            CatalogContractProjection(
                reference=ExactContractReference(
                    contract_kind="port_type",
                    contract_id=definition.type_id,
                ),
                descriptor=definition.canonical_descriptor,
            )
            for definition in self.port_types
        ]
        projected.extend(
            CatalogContractProjection(
                reference=ExactContractReference(
                    contract_kind=contract.contract_kind,
                    contract_id=contract.contract_id,
                ),
                descriptor=contract.descriptor,
            )
            for contract in self.contracts
        )
        return tuple(
            sorted(
                projected,
                key=lambda item: (
                    item.reference.contract_kind,
                    item.reference.contract_id,
                ),
            )
        )

    def get_port_type(
        self,
        type_id: str,
    ) -> PortTypeDefinition | None:
        """Return one stable Port Type identity, or None when unknown."""
        return self._by_identity.get(type_id)

    def require_port_type(
        self,
        type_id: str,
    ) -> PortTypeDefinition:
        """Resolve one stable identity and fail when it is unknown."""
        definition = self.get_port_type(type_id)
        if definition is None:
            raise UnknownPortTypeError(f"Unknown Port Type {type_id}")
        return definition

    def get_contract(
        self,
        contract_kind: str,
        contract_id: str,
    ) -> Any | None:
        """Return one exact stable contract without consulting runtime state."""
        if contract_kind == "port_type":
            return self.get_port_type(contract_id)
        return self._contracts_by_identity.get(
            (contract_kind, contract_id)
        )

    def require_contract(
        self,
        contract_kind: str,
        contract_id: str,
    ) -> Any:
        """Resolve one stable Catalog contract or fail."""
        contract = self.get_contract(
            contract_kind,
            contract_id,
        )
        if contract is None:
            raise UnknownContractError(
                contract_kind,
                contract_id,
            )
        return contract

    @staticmethod
    def _exact_reference(
        contract: PortTypeDefinition | CatalogContract,
    ) -> ExactContractReference:
        if isinstance(contract, PortTypeDefinition):
            return ExactContractReference(
                "port_type",
                contract.type_id,
            )
        return ExactContractReference(
            contract.contract_kind,
            contract.contract_id,
        )

    @staticmethod
    def _dependencies(
        contract: PortTypeDefinition | CatalogContract,
    ) -> tuple[ExactContractReference, ...]:
        if isinstance(contract, PortTypeDefinition):
            return tuple(
                ExactContractReference(
                    "port_type",
                    dependency.type_id,
                )
                for dependency in (
                    contract.output_identity_source_port_types.values()
                )
            )
        return contract.dependencies

    def resolve_contract_closure(
        self,
        roots: tuple[ExactContractReference, ...],
    ) -> tuple[ExactContractReference, ...]:
        """Resolve one admitted exact dependency closure without descriptors."""
        pending = list(roots)
        reachable: dict[
            tuple[str, str],
            ExactContractReference,
        ] = {}
        while pending:
            requested = pending.pop()
            contract = self.require_contract(*requested.key)
            current = self._exact_reference(contract)
            if current.key in reachable:
                continue
            reachable[current.key] = current
            pending.extend(self._dependencies(contract))
        return tuple(reachable[key] for key in sorted(reachable))

    def require_reference(
        self,
        contract_kind: str,
        contract_id: str,
    ) -> ExactContractReference:
        return self._exact_reference(
            self.require_contract(
                contract_kind,
                contract_id,
            )
        )

    def require_availability(
        self,
        binding: ExactContractReference,
    ) -> CatalogAvailabilityProjection:
        """Return the typed startup observation for one exact Binding."""
        for observation in self.availability:
            if observation.binding == binding:
                return observation
        raise CatalogBuildError(
            f"Unknown Binding Availability {binding.contract_id}"
        )

    def projection(self) -> CatalogProjection:
        """Return typed stable contracts and startup Binding observations."""
        return CatalogProjection(
            contracts=self._contract_projections(),
            availability_observed_at=self.availability_observed_at,
            availability=self.availability,
        )
