"""User-owned package activation and durable module inventory."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import replace
from pathlib import Path
import importlib
from importlib.metadata import distributions
import shutil
import subprocess
import sys
import tempfile
import threading
import uuid
from typing import Any

from core.execution.runtime import V2RunService
from core.project.storage import validate_identifier
from protein_workbench_public.module_registry import (
    DEFAULT_MODULES, InstalledModule, installed_modules, save_installed_modules,
)


class ModuleManagementError(ValueError):
    """A requested module operation cannot be applied to this installation."""


class ModuleManager:
    def __init__(
        self, data_root: Path, runtime: Callable[[], V2RunService],
        activate: Callable[[tuple[InstalledModule, ...], Callable[[], None], Mapping[str, Mapping[str, Any]] | None], None],
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
            self._publish(tuple(replace(package, enabled=package.package_id in enabled) for package in packages))
            return self.inventory()

    def _publish(self, packages: tuple[InstalledModule, ...]) -> None:
        self._activate(packages, lambda: save_installed_modules(self._data_root, packages), None)

    def apply_environment(
        self, configuration: Mapping[str, Mapping[str, Any]], persist: Callable[[], None],
    ) -> None:
        """Publish environment settings through the same idle service replacement boundary."""
        with self._lock, self._runtime().module_configuration_mutation():
            self._activate(installed_modules(self._data_root), persist, configuration)

    def install_bundled(self, package_id: str) -> dict[str, Any]:
        with self._lock, self._runtime().module_configuration_mutation():
            packages = installed_modules(self._data_root)
            if any(package.package_id == package_id for package in packages):
                raise ModuleManagementError("Package is already installed")
            selected = next((package for package in DEFAULT_MODULES if package.package_id == package_id), None)
            if selected is None:
                raise ModuleManagementError("Bundled package does not exist")
            self._publish((*packages, selected))
            return self.inventory()

    def install_wheel(self, filename: str, payload: bytes) -> dict[str, Any]:
        if Path(filename).name != filename or not filename.endswith(".whl"):
            raise ModuleManagementError("Select a Python wheel file (.whl)")
        with self._lock, self._runtime().module_configuration_mutation():
            packages = installed_modules(self._data_root)
            destination = self._data_root / "module-packages" / uuid.uuid4().hex
            destination.parent.mkdir(parents=True, exist_ok=True)
            try:
                with tempfile.TemporaryDirectory(prefix="module-upload-") as temporary:
                    wheel = Path(temporary) / filename
                    wheel.write_bytes(payload)
                    result = subprocess.run(
                        [sys.executable, "-m", "pip", "install", "--disable-pip-version-check",
                         "--no-cache-dir", "--no-index", "--no-deps", "--target", str(destination), str(wheel)],
                        capture_output=True, text=True, check=False,
                    )
                if result.returncode:
                    raise ModuleManagementError("Wheel installation failed: " + result.stderr[-1500:])
                entries = [entry for distribution in distributions(path=[str(destination)])
                           for entry in distribution.entry_points if entry.group == "protein_workbench.modules"]
                if len(entries) != 1 or entries[0].attr != "MODULE_PACKAGE":
                    raise ModuleManagementError("Wheel must declare one protein_workbench.modules entry point to MODULE_PACKAGE")
                entry = entries[0]
                validate_identifier(entry.name, "package_id")
                if any(package.package_id == entry.name for package in packages):
                    raise ModuleManagementError("Package is already installed; uninstall it before installing a replacement")
                package = InstalledModule(entry.name, entry.module, True, str(destination))
                importlib.invalidate_caches()
                package.registration()
                self._publish((*packages, package))
                return self.inventory()
            finally:
                # Durable inventory owns an installed directory even if a later response fails.
                if not any(package.source_root == str(destination) for package in installed_modules(self._data_root)):
                    _forget_package_imports(destination)
                    if destination.exists():
                        shutil.rmtree(destination)

    def uninstall(self, package_id: str) -> dict[str, Any]:
        with self._lock, self._runtime().module_configuration_mutation():
            packages = installed_modules(self._data_root)
            selected = next((package for package in packages if package.package_id == package_id), None)
            if selected is None:
                raise ModuleManagementError("Package is not installed")
            self._publish(tuple(package for package in packages if package.package_id != package_id))
            if selected.source_root is not None:
                source_root = Path(selected.source_root)
                _forget_package_imports(source_root)
                shutil.rmtree(source_root)
            return self.inventory()


def _forget_package_imports(source_root: Path) -> None:
    """Release exactly the removed distribution so reinstall imports its new files."""
    root = source_root.resolve()
    for name, module in tuple(sys.modules.items()):
        if module is None:
            continue
        namespace = vars(module)
        filename = namespace.get("__file__")
        paths = ([filename] if filename is not None else []) + list(namespace.get("__path__", ()))
        if any(Path(path).resolve().is_relative_to(root) for path in paths):
            del sys.modules[name]
    if str(source_root) in sys.path:
        sys.path.remove(str(source_root))
    importlib.invalidate_caches()
