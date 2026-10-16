"""Private installation settings declared by installed module Bindings."""
from __future__ import annotations

from collections.abc import Mapping
import json
from pathlib import Path
from typing import Any

from core.catalog.declarations import ExecutionBindingDefinition
from core.execution.environment import EnvironmentConfigurationError, admit_environment_field_value
from core.project.storage import replace_file_durable
from datatypes.i_json import canonical_json_bytes
from protein_workbench_public.module_management import ModuleManager
from protein_workbench_public.module_registry import installed_modules


def read_module_settings(data_root: Path) -> dict[str, dict[str, Any]]:
    path = data_root / "module-settings.json"
    return json.loads(path.read_text()) if path.exists() else {}


def save_module_settings(data_root: Path, values: Mapping[str, Mapping[str, Any]]) -> None:
    serializable = {binding: {name: str(value) if isinstance(value, Path) else value
                             for name, value in fields.items()} for binding, fields in values.items()}
    # The durable writer creates its temporary file with owner-only permissions.
    replace_file_durable(data_root, ("module-settings.json",), canonical_json_bytes(serializable))


class ModuleSettings:
    def __init__(self, data_root: Path, manager: ModuleManager) -> None:
        self._data_root = data_root
        self._manager = manager

    def declarations(self) -> dict[str, tuple[str, ExecutionBindingDefinition]]:
        return {binding.binding_id: (package.package_id, binding)
                for package in installed_modules(self._data_root)
                for binding in package.registration().bindings if binding.environment_fields}

    def projection(self) -> dict[str, Any]:
        stored = read_module_settings(self._data_root)
        return {"schema_namespace": "protein-workbench-public/v2", "bindings": [
            {"package_id": package_id, "binding_id": binding_id,
             "fields": [field.descriptor() for field in binding.environment_fields],
             "values": {field.name: stored[binding_id][field.name]
                        for field in binding.environment_fields
                        if field.value_category != "credential_handle" and field.name in stored.get(binding_id, {})},
             "configured_secrets": [field.name for field in binding.environment_fields
                                    if field.value_category == "credential_handle" and field.name in stored.get(binding_id, {})]}
            for binding_id, (package_id, binding) in self.declarations().items()]}

    def update(self, binding_id: str, values: Mapping[str, Any]) -> dict[str, Any]:
        def updated_configuration() -> dict[str, dict[str, Any]]:
            declaration = self.declarations().get(binding_id)
            if declaration is None:
                raise EnvironmentConfigurationError("Unknown settings Binding")
            fields = {field.name: field for field in declaration[1].environment_fields}
            if set(values) - fields.keys():
                raise EnvironmentConfigurationError("Settings contain undeclared fields")
            configuration = read_module_settings(self._data_root)
            selected = configuration.setdefault(binding_id, {})
            for name, value in values.items():
                if value is None:
                    selected.pop(name, None)
                else:
                    selected[name] = admit_environment_field_value(fields[name], value, path=f"environment:{binding_id}.{name}")
            return configuration

        self._manager.apply_environment(
            updated_configuration,
            lambda configuration: save_module_settings(self._data_root, configuration),
        )
        return self.projection()
