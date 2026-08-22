"""Immutable Catalog model, exact lookup, and typed projection."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
from types import MappingProxyType
from typing import Any

from datatypes.exact_reference import ExactContractReference
from datatypes.i_json import thaw_i_json

from .declarations import (
    AvailabilityResult,
    CatalogDefinition,
    ContractKind,
    _freeze_declaration,
    _thaw_declaration,
)
from .port_contract import (
    CATALOG_NAMESPACE,
    CatalogBuildError,
    ContractResolutionError,
    InactiveContractGenerationError,
    PortTypeDefinition,
    UnknownContractError,
    UnknownPortTypeError,
    canonical_json_bytes,
)


_PRESENTATION_CONTRACT_FIELDS = {
    "node_type": frozenset({"title", "summary", "category"}),
    "metric": frozenset({"title", "description"}),
}


def _result_identity_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        is_reference = set(value) == {
            "contract_kind",
            "contract_id",
            "contract_version",
            "contract_digest",
        }
        return {
            key: _result_identity_value(item)
            for key, item in value.items()
            if not (is_reference and key == "contract_digest")
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

    catalog_contract_digest: str
    contracts: tuple[CatalogContractProjection, ...]
    availability_observed_at: datetime
    availability: tuple[CatalogAvailabilityProjection, ...]


@dataclass(frozen=True, slots=True)
class CatalogContract:
    """One resolved contract and its Builder-admitted typed definition."""

    contract_kind: ContractKind
    contract_id: str
    contract_version: str
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
                    "contract_version": self.contract_version,
                    "descriptor": _result_identity_value(
                        {
                            key: value
                            for key, value in self.descriptor.items()
                            if key
                            not in _PRESENTATION_CONTRACT_FIELDS.get(
                                self.contract_kind,
                                (),
                            )
                        }
                    ),
                }
            ),
        )

    @property
    def descriptor_bytes(self) -> bytes:
        return canonical_json_bytes(_thaw_declaration(self.descriptor))

    @property
    def contract_digest(self) -> str:
        return f"sha256:{hashlib.sha256(self.descriptor_bytes).hexdigest()}"

    def reference(self) -> dict[str, Any]:
        return {
            "contract_kind": self.contract_kind,
            "contract_id": self.contract_id,
            "contract_version": self.contract_version,
            "contract_digest": self.contract_digest,
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
            "contract_version": contract.version,
            "descriptor": _result_identity_value(
                contract.canonical_descriptor
            ),
        }
    )


def _canonical_reference(
    reference: ExactContractReference,
) -> dict[str, str]:
    return {
        "contract_kind": reference.contract_kind,
        "contract_id": reference.contract_id,
        "contract_version": reference.contract_version,
        "contract_digest": reference.contract_digest,
    }


@dataclass(frozen=True, slots=True)
class FrozenCatalog:
    """Immutable indexes over Catalog Builder output."""

    port_types: tuple[PortTypeDefinition, ...]
    contracts: tuple[CatalogContract, ...] = ()
    availability: tuple[CatalogAvailabilityProjection, ...] = ()
    availability_observed_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc),
    )
    _by_identity: Mapping[tuple[str, str], PortTypeDefinition] = field(
        init=False,
        repr=False,
    )
    _contracts_by_identity: Mapping[
        tuple[str, str, str], CatalogContract
    ] = field(
        init=False,
        repr=False,
    )
    _active_contract_versions: Mapping[tuple[str, str], str] = field(
        init=False,
        repr=False,
    )

    def __post_init__(self) -> None:
        ordered = tuple(
            sorted(
                self.port_types,
                key=lambda item: (item.type_id, item.version),
            )
        )
        resolved = {
            (definition.type_id, definition.version): definition
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
                    item.contract_version,
                ),
            )
        )
        contracts_by_identity = {
            (
                contract.contract_kind,
                contract.contract_id,
                contract.contract_version,
            ): contract
            for contract in ordered_contracts
        }
        object.__setattr__(self, "contracts", ordered_contracts)
        object.__setattr__(
            self,
            "_contracts_by_identity",
            MappingProxyType(contracts_by_identity),
        )
        active_contract_versions = {
            ("port_type", definition.type_id): definition.version
            for definition in ordered
        }
        active_contract_versions.update(
            {
                (contract_kind, contract_id): contract_version
                for contract_kind, contract_id, contract_version in (
                    contracts_by_identity
                )
            }
        )
        object.__setattr__(
            self,
            "_active_contract_versions",
            MappingProxyType(active_contract_versions),
        )
        object.__setattr__(self, "availability", tuple(self.availability))

    def _contract_projections(self) -> tuple[CatalogContractProjection, ...]:
        projected = [
            CatalogContractProjection(
                reference=ExactContractReference(
                    contract_kind="port_type",
                    contract_id=definition.type_id,
                    contract_version=definition.version,
                    contract_digest=definition.contract_digest,
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
                    contract_version=contract.contract_version,
                    contract_digest=contract.contract_digest,
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
                    item.reference.contract_version,
                ),
            )
        )

    def _catalog_descriptor(self) -> dict[str, Any]:
        """Return the stable Catalog identity, excluding observed availability."""
        return {
            "schema_namespace": CATALOG_NAMESPACE,
            "contracts": [
                {
                    "reference": _canonical_reference(contract.reference),
                    "descriptor": thaw_i_json(contract.descriptor),
                }
                for contract in self._contract_projections()
            ],
        }

    @property
    def catalog_descriptor_bytes(self) -> bytes:
        """RFC 8785 canonical stable Catalog descriptor bytes."""
        return canonical_json_bytes(self._catalog_descriptor())

    @property
    def contract_digest(self) -> str:
        """SHA-256 identity of all stable contracts in this Catalog."""
        return (
            "sha256:"
            f"{hashlib.sha256(self.catalog_descriptor_bytes).hexdigest()}"
        )

    def get_port_type(
        self,
        type_id: str,
        version: str,
    ) -> PortTypeDefinition | None:
        """Return one exact Port Type identity, or None when unknown."""
        return self._by_identity.get((type_id, version))

    def require_port_type(
        self,
        type_id: str,
        version: str,
    ) -> PortTypeDefinition:
        """Resolve one exact identity and fail closed when it is unknown."""
        definition = self.get_port_type(type_id, version)
        if definition is None:
            raise UnknownPortTypeError(f"Unknown Port Type {type_id}@{version}")
        return definition

    def get_contract(
        self,
        contract_kind: str,
        contract_id: str,
        contract_version: str,
    ) -> Any | None:
        """Return one exact stable contract without consulting runtime state."""
        if contract_kind == "port_type":
            return self.get_port_type(contract_id, contract_version)
        return self._contracts_by_identity.get(
            (contract_kind, contract_id, contract_version)
        )

    def require_contract(
        self,
        contract_kind: str,
        contract_id: str,
        contract_version: str,
    ) -> Any:
        """Resolve one exact Catalog contract or fail closed."""
        contract = self.get_contract(
            contract_kind,
            contract_id,
            contract_version,
        )
        if contract is None:
            active_version = self._active_contract_versions.get(
                (contract_kind, contract_id)
            )
            if active_version is None:
                raise UnknownContractError(
                    contract_kind,
                    contract_id,
                    contract_version,
                )
            raise InactiveContractGenerationError(
                contract_kind,
                contract_id,
                contract_version,
                active_version,
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
                contract.version,
                contract.contract_digest,
            )
        return ExactContractReference(
            contract.contract_kind,
            contract.contract_id,
            contract.contract_version,
            contract.contract_digest,
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
                    dependency.version,
                    dependency.contract_digest,
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
            tuple[str, str, str],
            ExactContractReference,
        ] = {}
        while pending:
            requested = pending.pop()
            contract = self.require_contract(*requested.key)
            current = self._exact_reference(contract)
            if requested != current:
                raise ContractResolutionError(
                    "exact contract digest is not active"
                )
            if current.key in reachable:
                continue
            reachable[current.key] = current
            pending.extend(self._dependencies(contract))
        return tuple(reachable[key] for key in sorted(reachable))

    def require_reference(
        self,
        contract_kind: str,
        contract_id: str,
        contract_version: str,
    ) -> ExactContractReference:
        return self._exact_reference(
            self.require_contract(
                contract_kind,
                contract_id,
                contract_version,
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
            "Unknown Binding Availability "
            f"{binding.contract_id}@{binding.contract_version}"
        )


    def projection(self) -> CatalogProjection:
        """Return typed stable contracts and startup Binding observations."""
        return CatalogProjection(
            catalog_contract_digest=self.contract_digest,
            contracts=self._contract_projections(),
            availability_observed_at=self.availability_observed_at,
            availability=self.availability,
        )
