"""Persisted package selection for the production application composition."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from importlib import import_module
import json
from pathlib import Path
import sys

from core.catalog.declarations import ModulePackageRegistration
from core.project.storage import replace_file_durable, validate_identifier
from datatypes.i_json import canonical_json_bytes


@dataclass(frozen=True, slots=True)
class InstalledModule:
    package_id: str
    package_module: str
    enabled: bool
    source_root: str | None = None

    def registration(self) -> ModulePackageRegistration:
        if self.source_root is not None and self.source_root not in sys.path:
            sys.path.insert(0, self.source_root)
        registration = import_module(self.package_module).MODULE_PACKAGE
        if not isinstance(registration, ModulePackageRegistration):
            raise TypeError(f"{self.package_module}.MODULE_PACKAGE must be a ModulePackageRegistration")
        if registration.package_id != self.package_id:
            raise ValueError("Installed package ID disagrees with its registration")
        return registration


DEFAULT_MODULES = tuple(
    InstalledModule(name, f"modules.{name}.package", True)
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
            or set(entry) != {"package_id", "package_module", "enabled", "source_root"}
            or not isinstance(entry["package_module"], str)
            or not entry["package_module"]
            or type(entry["enabled"]) is not bool
            or entry["source_root"] is not None and (
                not isinstance(entry["source_root"], str) or not Path(entry["source_root"]).is_absolute()
            )
        ):
            raise ValueError("Invalid installed module inventory entry")
        validate_identifier(entry["package_id"], "package_id")
        entries.append(InstalledModule(**entry))
    if len({entry.package_id for entry in entries}) != len(entries):
        raise ValueError("Module inventory repeats a package ID")
    return tuple(entries)


def save_installed_modules(data_root: Path, packages: tuple[InstalledModule, ...]) -> None:
    replace_file_durable(
        data_root, ("modules.json",),
        canonical_json_bytes({"packages": [asdict(package) for package in packages]}),
    )
