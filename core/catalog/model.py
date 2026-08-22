"""Immutable Catalog model, exact lookup, and typed projection."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
from types import MappingProxyType
from typing import Any

from datatypes.exact_reference import ExactContractReference
from datatypes.i_json import freeze_i_json, thaw_i_json

from .declarations import AvailabilityResult, CatalogContract
from .port_contract import (
    CATALOG_NAMESPACE,
    CatalogBuildError,
    InactiveContractGenerationError,
    PortTypeDefinition,
    UnknownContractError,
    UnknownPortTypeError,
    _require_single_active_contract_version,
    canonical_json_bytes,
)


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
    """Immutable, atomically validated v2 Catalog and runtime declarations."""

    port_types: tuple[PortTypeDefinition, ...]
    contracts: tuple[Any, ...] = ()
    availability: tuple[Mapping[str, Any], ...] = ()
    availability_observed_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc),
    )
    factories: Mapping[tuple[str, str], Any] = field(
        default_factory=dict,
        repr=False,
        compare=False,
    )
    readiness_declarations: Mapping[tuple[str, str], Any] = field(
        default_factory=dict,
        repr=False,
        compare=False,
    )
    effective_randomness_resolvers: Mapping[tuple[str, str], Any] = field(
        default_factory=dict,
        repr=False,
        compare=False,
    )
    utility_transforms: Mapping[tuple[str, str], Any] = field(
        default_factory=dict,
        repr=False,
        compare=False,
    )
    owners: Mapping[tuple[str, str, str], frozenset[str]] = field(
        default_factory=dict,
        repr=False,
        compare=False,
    )
    _by_identity: Mapping[tuple[str, str], PortTypeDefinition] = field(
        init=False,
        repr=False,
    )
    _contracts_by_identity: Mapping[tuple[str, str, str], Any] = field(
        init=False,
        repr=False,
    )
    _active_contract_versions: Mapping[tuple[str, str], str] = field(
        init=False,
        repr=False,
    )

    def __post_init__(self) -> None:
        resolved: dict[tuple[str, str], PortTypeDefinition] = {}
        for definition in self.port_types:
            definition.validate_runtime_contract()
            identity = (definition.type_id, definition.version)
            if identity in resolved:
                raise CatalogBuildError(
                    "duplicate Port Type identity "
                    f"{definition.type_id}@{definition.version}"
                )
            resolved[identity] = definition
        ordered = tuple(
            sorted(
                resolved.values(),
                key=lambda item: (item.type_id, item.version),
            )
        )
        object.__setattr__(self, "port_types", ordered)
        object.__setattr__(self, "_by_identity", MappingProxyType(resolved))
        contracts_by_identity: dict[tuple[str, str, str], Any] = {}
        ordered_contracts = tuple(
            sorted(
                tuple(self.contracts),
                key=lambda item: (
                    item.contract_kind,
                    item.contract_id,
                    item.contract_version,
                ),
            )
        )
        for contract in ordered_contracts:
            identity = (
                contract.contract_kind,
                contract.contract_id,
                contract.contract_version,
            )
            if identity[0] == "port_type":
                raise CatalogBuildError(
                    "Port Type contracts must use the Port Type definition view"
                )
            if identity in contracts_by_identity:
                raise CatalogBuildError(
                    "duplicate contract identity "
                    f"{identity[0]}:{identity[1]}@{identity[2]}"
                )
            contracts_by_identity[identity] = contract
        _require_single_active_contract_version(
            (
                "port_type",
                definition.type_id,
                definition.version,
            )
            for definition in ordered
        )
        _require_single_active_contract_version(contracts_by_identity)
        observation_time = self.availability_observed_at
        if (
            not isinstance(observation_time, datetime)
            or observation_time.tzinfo is None
            or observation_time.utcoffset() is None
        ):
            raise CatalogBuildError(
                "Catalog Availability observation time must be timezone-aware"
            )
        frozen_availability = tuple(
            freeze_i_json(thaw_i_json(snapshot))
            for snapshot in self.availability
        )
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
        object.__setattr__(self, "availability", frozen_availability)
        object.__setattr__(
            self,
            "availability_observed_at",
            observation_time.astimezone(timezone.utc),
        )
        object.__setattr__(
            self,
            "factories",
            MappingProxyType(dict(self.factories)),
        )
        object.__setattr__(
            self,
            "readiness_declarations",
            MappingProxyType(dict(self.readiness_declarations)),
        )
        object.__setattr__(
            self,
            "effective_randomness_resolvers",
            MappingProxyType(dict(self.effective_randomness_resolvers)),
        )
        object.__setattr__(
            self,
            "utility_transforms",
            MappingProxyType(dict(self.utility_transforms)),
        )
        object.__setattr__(
            self,
            "owners",
            MappingProxyType(dict(self.owners)),
        )

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

    def directly_compatible(
        self,
        source_type_id: str,
        source_version: str,
        target_type_id: str,
        target_version: str,
    ) -> bool:
        """Accept a direct connection only between known exact identities."""
        source = self.require_port_type(source_type_id, source_version)
        target = self.require_port_type(target_type_id, target_version)
        return (source.type_id, source.version) == (
            target.type_id,
            target.version,
        )

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

    def require_factory(
        self,
        binding_id: str,
        binding_version: str,
    ) -> Any:
        """Return the lazy factory owned by one exact Binding."""
        try:
            return self.factories[(binding_id, binding_version)]
        except KeyError as error:
            raise CatalogBuildError(
                f"Unknown Binding factory {binding_id}@{binding_version}"
            ) from error

    def require_readiness_declaration(
        self,
        binding_id: str,
        binding_version: str,
    ) -> Any:
        """Return the run-scoped Readiness declaration for one Binding."""
        try:
            return self.readiness_declarations[
                (binding_id, binding_version)
            ]
        except KeyError as error:
            raise CatalogBuildError(
                f"Unknown Binding readiness {binding_id}@{binding_version}"
            ) from error

    def require_availability(
        self,
        binding: ExactContractReference,
    ) -> CatalogAvailabilityProjection:
        """Return the typed startup observation for one exact Binding."""
        for observation in self.projection().availability:
            if observation.binding == binding:
                return observation
        raise CatalogBuildError(
            "Unknown Binding Availability "
            f"{binding.contract_id}@{binding.contract_version}"
        )

    def get_effective_randomness_resolver(
        self,
        binding_id: str,
        binding_version: str,
    ) -> Any | None:
        """Return a Binding's optional pre-Cache randomness resolver."""
        return self.effective_randomness_resolvers.get(
            (binding_id, binding_version)
        )

    def require_utility_transform(
        self,
        transform_id: str,
        transform_version: str,
    ) -> Any:
        """Return one private Utility Transform runtime."""
        try:
            return self.utility_transforms[
                (transform_id, transform_version)
            ]
        except KeyError as error:
            raise CatalogBuildError(
                f"Unknown Utility Transform "
                f"{transform_id}@{transform_version}"
            ) from error

    def projection(
        self,
        *,
        observed_at: datetime | None = None,
    ) -> CatalogProjection:
        """Return typed stable contracts and startup Binding observations."""
        timestamp = observed_at or self.availability_observed_at
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise CatalogBuildError(
                "Catalog projection observation time must be timezone-aware"
            )
        timestamp = timestamp.astimezone(timezone.utc)
        contracts = self._contract_projections()
        references_by_identity = {
            (
                contract.reference.contract_kind,
                contract.reference.contract_id,
                contract.reference.contract_version,
            ): contract.reference
            for contract in contracts
        }
        availability = tuple(
            CatalogAvailabilityProjection(
                binding=references_by_identity[
                    (
                        "binding",
                        snapshot["binding"]["contract_id"],
                        snapshot["binding"]["contract_version"],
                    )
                ],
                observed_at=(
                    timestamp
                    if observed_at is not None
                    else datetime.fromisoformat(
                        snapshot["observed_at"].replace("Z", "+00:00")
                    )
                ),
                result=(
                    AvailabilityResult.available()
                    if snapshot["available"]
                    else AvailabilityResult.unavailable(
                        snapshot["reason"]["code"],
                        snapshot["reason"]["message"],
                        retryable=snapshot["reason"]["retryable"],
                    )
                ),
            )
            for snapshot in self.availability
        )
        return CatalogProjection(
            catalog_contract_digest=self.contract_digest,
            contracts=contracts,
            availability_observed_at=timestamp,
            availability=availability,
        )
