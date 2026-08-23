"""One-time admission of exact Binding-scoped Environment Configuration."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from core.catalog.declarations import (
    EnvironmentFieldDeclaration,
    ExecutionBindingDefinition,
)
from core.catalog.model import FrozenCatalog
from core.operation import BindingEnvironment
from datatypes.i_json import freeze_i_json


class EnvironmentConfigurationError(ValueError):
    """Submitted private configuration contradicts its Binding declaration."""


@dataclass(frozen=True, slots=True)
class EnvironmentConfiguration:
    """Admitted private values indexed by exact Binding identity."""

    _entries: Mapping[tuple[str, str], BindingEnvironment]

    def for_binding(
        self,
        binding_id: str,
        binding_version: str,
    ) -> BindingEnvironment:
        return self._entries.get(
            (binding_id, binding_version),
            BindingEnvironment({}),
        )


def _admit_field_value(
    declaration: EnvironmentFieldDeclaration,
    value: Any,
    *,
    path: str,
) -> Any:
    if declaration.value_category == "json_value":
        try:
            return freeze_i_json(value, path=path)
        except ValueError as error:
            raise EnvironmentConfigurationError(
                f"{path} must be a canonical I-JSON value"
            ) from error
    if declaration.value_category == "filesystem_path":
        if (
            not isinstance(value, (str, Path))
            or (isinstance(value, str) and not value)
        ):
            raise EnvironmentConfigurationError(
                f"{path} must be a filesystem path"
            )
        return Path(value)
    if type(value) is not str or not value:
        raise EnvironmentConfigurationError(
            f"{path} must be a credential handle"
        )
    return value


def admit_environment_configuration(
    catalog: FrozenCatalog,
    raw_configuration: Mapping[
        tuple[str, str],
        Mapping[str, Any],
    ],
) -> EnvironmentConfiguration:
    """Admit raw configuration once against exact Catalog Binding fields."""
    if not isinstance(raw_configuration, Mapping):
        raise EnvironmentConfigurationError(
            "Environment Configuration must be an object"
        )
    admitted: dict[tuple[str, str], BindingEnvironment] = {}
    for identity, entry in raw_configuration.items():
        if (
            not isinstance(identity, tuple)
            or len(identity) != 2
            or any(type(part) is not str for part in identity)
        ):
            raise EnvironmentConfigurationError(
                "Environment Configuration must use exact Binding identities"
            )
        binding_id, binding_version = identity
        contract = catalog.require_contract(
            "binding",
            binding_id,
            binding_version,
        )
        if not isinstance(entry, Mapping) or set(entry) != {"values"}:
            raise EnvironmentConfigurationError(
                "Each Environment Configuration entry must contain values"
            )
        values = entry["values"]
        if not isinstance(values, Mapping):
            raise EnvironmentConfigurationError(
                "Environment Configuration values must be an object"
            )
        binding = cast(ExecutionBindingDefinition, contract.definition)
        declarations = {
            declaration.name: declaration
            for declaration in binding.environment_fields
        }
        submitted_fields = set(values)
        required_fields = {
            name
            for name, declaration in declarations.items()
            if declaration.required
        }
        if submitted_fields - set(declarations):
            raise EnvironmentConfigurationError(
                "Environment Configuration contains undeclared fields"
            )
        if required_fields - submitted_fields:
            raise EnvironmentConfigurationError(
                "Environment Configuration omits required fields"
            )
        admitted_values = {
            name: _admit_field_value(
                declarations[name],
                value,
                path=(
                    f"environment:{binding_id}@{binding_version}.values.{name}"
                ),
            )
            for name, value in values.items()
        }
        admitted[identity] = BindingEnvironment(admitted_values)
    return EnvironmentConfiguration(admitted)
