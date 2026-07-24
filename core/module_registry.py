"""Module registry: discovers, validates, and stores module definitions."""

from __future__ import annotations

import importlib
import pkgutil
from pathlib import Path
from typing import Protocol

from core.module_definition import ModuleDefinition
from core.type_registry import TypeRegistry


class RegisterFn(Protocol):
    """Protocol for module subpackage register() functions."""

    def __call__(self, registry: ModuleRegistry) -> None: ...


class ModuleRegistry:
    """Registry of all known modules by module ID.

    Two-phase registration:
    1. Import all subpackages under modules/
    2. Each subpackage's register(registry) is called
    The registry is populated at startup and never modified at runtime.
    """

    def __init__(self, type_registry: TypeRegistry) -> None:
        self._modules: dict[str, ModuleDefinition] = {}
        self._type_registry = type_registry

    def register(self, definition: ModuleDefinition) -> None:
        """Register a ModuleDefinition. Raises ValueError on duplicate module_id."""
        if definition.module_id in self._modules:
            raise ValueError(
                f"Module ID '{definition.module_id}' is already registered"
            )

        # Validate that all port types are registered
        for port in definition.input_ports:
            if self._type_registry.get(port.type_id) is None:
                self._type_registry.register(port.type_id)

        for port in definition.output_ports:
            if self._type_registry.get(port.type_id) is None:
                self._type_registry.register(port.type_id)

        self._modules[definition.module_id] = definition

    def get(self, module_id: str) -> ModuleDefinition | None:
        """Get a module definition by ID."""
        return self._modules.get(module_id)

    def list_all(self) -> list[ModuleDefinition]:
        """Return all registered module definitions."""
        return list(self._modules.values())

    def list_by_category(self) -> dict[str, list[ModuleDefinition]]:
        """Return modules grouped by category."""
        result: dict[str, list[ModuleDefinition]] = {}
        for mod in self._modules.values():
            result.setdefault(mod.category, []).append(mod)
        return result

    def __contains__(self, module_id: str) -> bool:
        return module_id in self._modules

    def __len__(self) -> int:
        return len(self._modules)


def discover_modules(registry: ModuleRegistry, modules_package: str = "modules") -> None:
    """Import all subpackages under modules/ and call their register().

    Each subpackage must export a register(registry: ModuleRegistry) function.
    Subpackages without register() are silently skipped.
    Already-registered modules are skipped for idempotency.
    """
    package = importlib.import_module(modules_package)
    package_path = Path(package.__path__[0])  # type: ignore[attr-defined]

    for _, name, is_pkg in pkgutil.iter_modules([str(package_path)]):
        if not is_pkg:
            continue
        try:
            subpkg = importlib.import_module(f"{modules_package}.{name}")
            if hasattr(subpkg, "register"):
                subpkg.register(registry)
        except ValueError:
            # Module already registered — skip for idempotency
            pass
        except Exception:
            # Other import/registration failures — skip
            pass
