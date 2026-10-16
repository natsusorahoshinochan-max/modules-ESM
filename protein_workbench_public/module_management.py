"""User-owned package activation and durable module inventory."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
import threading
from typing import Any

from core.execution.runtime import V2RunService
from protein_workbench_public.module_registry import (
    DEFAULT_MODULES, InstalledModule, installed_modules,
)


class ModuleManagementError(ValueError):
    """A requested module operation cannot be applied to this installation."""


class ModuleManager:
    def __init__(
        self, data_root: Path, runtime: Callable[[], V2RunService],
        activate: Callable[[tuple[InstalledModule, ...]], None],
    ) -> None:
        self._data_root = data_root
        self._runtime = runtime
        self._activate = activate
        self._lock = threading.RLock()

    def inventory(self) -> dict[str, Any]:
        packages = installed_modules(self._data_root)
        package_ids = {package.package_id for package in packages}
        return {
            "schema_namespace": "protein-workbench-public/v2",
            "modules": [{
                "package_id": package.package_id,
                "package_module": package.package_module,
                "enabled": package.enabled,
                "origin": "bundled" if package.source_root is None else "external",
            } for package in packages],
            "bundled_packages": [{"package_id": package.package_id, "package_module": package.package_module}
                                 for package in DEFAULT_MODULES if package.package_id not in package_ids],
        }

    def set_enabled(self, package_ids: list[str]) -> dict[str, Any]:
        with self._lock, self._runtime().module_configuration_mutation():
            packages = installed_modules(self._data_root)
            enabled = set(package_ids)
            if enabled - {package.package_id for package in packages}:
                raise ModuleManagementError("An enabled package is not installed")
            self._activate(tuple(replace(package, enabled=package.package_id in enabled) for package in packages))
            return self.inventory()
