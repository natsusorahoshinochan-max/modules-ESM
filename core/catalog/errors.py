"""Catalog construction, resolution, and Port value errors."""

from __future__ import annotations


class CatalogBuildError(ValueError):
    """A malformed stable contract prevented atomic Catalog publication."""


class UnknownPortTypeError(LookupError):
    """An exact Port Type identity is not present in the FrozenCatalog."""


class ContractResolutionError(LookupError):
    """An exact Contract identity cannot resolve in the active Catalog."""


class UnknownContractError(ContractResolutionError):
    """No active Catalog contract has the requested logical identity."""

    def __init__(
        self,
        contract_kind: str,
        contract_id: str,
        requested_version: str,
    ) -> None:
        self.contract_kind = contract_kind
        self.contract_id = contract_id
        self.requested_version = requested_version
        super().__init__(
            f"Unknown contract {contract_kind}:"
            f"{contract_id}@{requested_version}"
        )


class InactiveContractGenerationError(ContractResolutionError):
    """A logical contract exists, but its requested version is not active."""

    def __init__(
        self,
        contract_kind: str,
        contract_id: str,
        requested_version: str,
        active_version: str,
    ) -> None:
        self.contract_kind = contract_kind
        self.contract_id = contract_id
        self.requested_version = requested_version
        self.active_version = active_version
        super().__init__(
            f"Requested contract version {contract_kind}:"
            f"{contract_id}@{requested_version} is not active; active version is "
            f"{active_version}"
        )


class PortValueError(ValueError):
    """A runtime Port value violates its nominal validation or codec contract."""
