"""Persisted package selection for the production application composition."""

from __future__ import annotations

from dataclasses import dataclass
from importlib import import_module
import json
from pathlib import Path

from core.catalog.declarations import ModulePackageRegistration


@dataclass(frozen=True, slots=True)
class InstalledModule:
    package_module: str
    enabled: bool

    def registration(self) -> ModulePackageRegistration:
        registration = import_module(self.package_module).MODULE_PACKAGE
        if not isinstance(registration, ModulePackageRegistration):
            raise TypeError(f"{self.package_module}.MODULE_PACKAGE must be a ModulePackageRegistration")
        return registration


DEFAULT_MODULES = tuple(
    InstalledModule(f"modules.{name}.package", True)
    for name in (
        "collection_ops", "esm3", "folding", "prompt_authoring", "protein_io",
        "proteinmpnn", "residue_data", "selection", "solubility",
        "structure_annotation", "structure_comparison", "structure_prediction",
        "structure_transform",
    )
)


def installed_modules(data_root: Path) -> tuple[InstalledModule, ...]:
    """Read one installation's package inventory; fresh installs use bundled modules."""
    path = data_root / "modules.json"
    if not path.exists():
        return DEFAULT_MODULES
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict) or set(document) != {"packages"} or not isinstance(document["packages"], list):
        raise ValueError("Module inventory must contain a packages array")
    entries = []
    for entry in document["packages"]:
        if (
            not isinstance(entry, dict)
            or set(entry) != {"package_module", "enabled"}
            or not isinstance(entry["package_module"], str)
            or not entry["package_module"]
            or type(entry["enabled"]) is not bool
        ):
            raise ValueError("Module inventory entry requires package_module and enabled")
        entries.append(InstalledModule(entry["package_module"], entry["enabled"]))
    if len({entry.package_module for entry in entries}) != len(entries):
        raise ValueError("Module inventory repeats a package")
    return tuple(entries)
