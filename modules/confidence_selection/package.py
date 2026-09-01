"""Exact pLDDT utility transforms for the pinned WebUI Methods."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from core.catalog.declarations import (
    ContractIdentity,
    ModulePackageRegistration,
    UtilityTransformDefinition,
)
from core.catalog.port_contract import BehaviorReference


def _percent_to_unit(value: float, _parameters: Mapping[str, Any]) -> float:
    return value / 100.0


def _transform(method_id: str, suffix: str) -> UtilityTransformDefinition:
    return UtilityTransformDefinition(
        transform_id=(
            f"structure.plddt.mean_residue.{suffix}.percent_to_unit"
        ),
        compatible_input_contract={
            "metric": ContractIdentity(
                "metric", "structure.plddt.mean_residue"
            ),
            "method": ContractIdentity("method", method_id),
            "context_profile": {"kind": "intrinsic"},
        },
        parameters={},
        behavior=BehaviorReference(
            f"structure.plddt.mean_residue.{suffix}/percent-to-unit",
            {"mapping": "x / 100"},
        ),
        transform=_percent_to_unit,
    )


MODULE_PACKAGE = ModulePackageRegistration(
    package_id="confidence_selection",
    package_module=__package__,
    utility_transforms=(
        _transform(
            "esm3.generate_paired.esm3_medium_2024_08",
            "esm3_medium_2024_08",
        ),
        _transform(
            "folding.fold.esmfold2_fast_biohub_2026_05",
            "esmfold2_fast_biohub_2026_05",
        ),
    ),
)


__all__ = ["MODULE_PACKAGE"]
