"""One-time admission of Binding-scoped external configuration."""

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
    """Admitted private values indexed by stable Binding ID."""

    _entries: Mapping[str, BindingEnvironment]

    def for_binding(
        self,
        binding_id: str,
    ) -> BindingEnvironment:
        return self._entries.get(
            binding_id,
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
        filesystem_path = Path(value)
        if not filesystem_path.is_absolute():
            raise EnvironmentConfigurationError(
                f"{path} must be an absolute filesystem path"
            )
        return filesystem_path
    if type(value) is not str or not value:
        raise EnvironmentConfigurationError(
            f"{path} must be a credential handle"
        )
    return value


def admit_environment_configuration(
    catalog: FrozenCatalog,
    raw_configuration: Mapping[str, Mapping[str, Any]],
) -> EnvironmentConfiguration:
    """Admit external fields once against stable Binding declarations."""
    if not isinstance(raw_configuration, Mapping):
        raise EnvironmentConfigurationError(
            "Environment Configuration must be an object"
        )
    admitted: dict[str, BindingEnvironment] = {}
    for binding_id, values in raw_configuration.items():
        if type(binding_id) is not str:
            raise EnvironmentConfigurationError(
                "Environment Configuration must use stable Binding IDs"
            )
        contract = catalog.get_contract("binding", binding_id)
        if contract is None:
            raise EnvironmentConfigurationError(
                f"Unknown Environment Configuration Binding {binding_id}"
            )
        if not isinstance(values, Mapping):
            raise EnvironmentConfigurationError(
                "Environment Configuration entry must be an object"
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
                path=f"environment:{binding_id}.{name}",
            )
            for name, value in values.items()
        }
        admitted[binding_id] = BindingEnvironment(admitted_values)
    return EnvironmentConfiguration(admitted)
