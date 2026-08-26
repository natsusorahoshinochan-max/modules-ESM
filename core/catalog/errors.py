"""Catalog construction, resolution, and Port value errors."""

from __future__ import annotations


class CatalogBuildError(ValueError):
    """A malformed stable contract prevented atomic Catalog publication."""


class UnknownPortTypeError(LookupError):
    """A stable Port Type identity is not present in the FrozenCatalog."""


class ContractResolutionError(LookupError):
    """A stable Contract identity cannot resolve in the Catalog."""


class UnknownContractError(ContractResolutionError):
    """No active Catalog contract has the requested logical identity."""

    def __init__(
        self,
        contract_kind: str,
        contract_id: str,
    ) -> None:
        self.contract_kind = contract_kind
        self.contract_id = contract_id
        super().__init__(
            f"Unknown contract {contract_kind}:{contract_id}"
        )


class PortValueError(ValueError):
    """A runtime Port value violates its nominal validation or codec contract."""
