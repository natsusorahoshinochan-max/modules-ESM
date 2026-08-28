"""Operational resource declarations for the SimpleFold routes."""

from __future__ import annotations

import importlib.util
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast



class SimpleFoldAssetClosureAdmissionError(RuntimeError):
    """One required SimpleFold resource is unavailable at Readiness."""


@dataclass(frozen=True, slots=True)
class SimpleFoldClosureFile:
    """One file used by a SimpleFold route."""

    role: str
    environment_key: str
    runtime_group: str
    runtime_filename: str


@dataclass(frozen=True, slots=True)
class SimpleFoldClosureSource:
    """One import source used by a SimpleFold route."""

    role: str
    source_name: str | None = None
    package_name: str | None = None
    environment_key: str | None = None
    runtime_group: str | None = None
    required_relative_files: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class SimpleFoldProviderAssetClosure:
    """Binding-owned SimpleFold resource roles."""

    binding_id: str
    files: tuple[SimpleFoldClosureFile, ...]
    sources: tuple[SimpleFoldClosureSource, ...]

    def readiness_prerequisite(self) -> dict[str, Any]:
        """Project the declaration into one Binding prerequisite."""
        files = tuple(
            {
                "role": entry.role,
                "environment_key": entry.environment_key,
                "runtime_filename": entry.runtime_filename,
            }
            for entry in self.files
        )
        sources: list[dict[str, Any]] = []
        for entry in self.sources:
            source: dict[str, Any] = {
                "role": entry.role,
            }
            if entry.source_name is not None:
                source["source_name"] = entry.source_name
            if entry.package_name is not None:
                source["package_name"] = entry.package_name
            if entry.environment_key is not None:
                source["environment_key"] = entry.environment_key
            if entry.required_relative_files:
                source["required_relative_files"] = (
                    entry.required_relative_files
                )
            sources.append(source)
        return {
            "files": files,
            "sources": tuple(sources),
            "path_source": "trusted_environment_configuration",
        }

@dataclass(frozen=True, slots=True)
class BoundSimpleFoldProviderAssetClosure:
    """Runtime roots bound from one route declaration."""

    groups: tuple[tuple[str, Path], ...]

    def group_root(self, group: str) -> Path:
        """Return one declaration-owned runtime root."""
        return dict(self.groups)[group]


def _configured_root(environment: Mapping[str, Any], key: str) -> Path:
    root = cast(Path, environment[key])
    if not root.is_dir():
        raise SimpleFoldAssetClosureAdmissionError(
            f"SimpleFold closure root is unavailable: {key}"
        )
    return root


def admit_simplefold_provider_asset_closure(
    closure: SimpleFoldProviderAssetClosure,
    environment: Mapping[str, Any],
) -> None:
    """Check that one route's configured resources are available."""
    for source in closure.sources:
        if source.package_name is not None:
            package_spec = importlib.util.find_spec(source.package_name)
            if package_spec is None:
                raise SimpleFoldAssetClosureAdmissionError(
                    "SimpleFold installed source is unavailable"
                )
            package_root = Path(cast(str, package_spec.origin)).parent
            if any(
                not (package_root / relative_path).is_file()
                for relative_path in source.required_relative_files
            ):
                raise SimpleFoldAssetClosureAdmissionError(
                    "SimpleFold installed source is unavailable"
                )
            continue
        source_root = _configured_root(
            environment,
            cast(str, source.environment_key),
        )
        if source.role == "language_model_runtime_source" and any(
            not (source_root / relative_path).is_file()
            for relative_path in ("esm/__init__.py", "esm/pretrained.py")
        ):
            raise SimpleFoldAssetClosureAdmissionError(
                "SimpleFold language-model source is unavailable"
            )
    for file in closure.files:
        root = _configured_root(environment, file.environment_key)
        if not (root / file.runtime_filename).is_file():
            raise SimpleFoldAssetClosureAdmissionError(
                "SimpleFold closure file is unavailable: "
                f"{file.runtime_filename}"
            )


def bind_simplefold_provider_asset_closure(
    closure: SimpleFoldProviderAssetClosure,
    environment: Mapping[str, Any],
) -> BoundSimpleFoldProviderAssetClosure:
    """Bind roots already proved by the Binding's Readiness boundary."""
    declarations = (*closure.files, *closure.sources)
    return BoundSimpleFoldProviderAssetClosure(
        groups=tuple(sorted({
            cast(str, item.runtime_group): cast(
                Path,
                environment[cast(str, item.environment_key)],
            )
            for item in declarations
            if item.runtime_group is not None
        }.items())),
    )


_SIMPLEFOLD_FOLDING_SOURCE = SimpleFoldClosureSource(
    role="provider_runtime_source",
    source_name="ml-simplefold",
    package_name="simplefold",
    required_relative_files=(
        "configs/model/architecture/foldingdit_100M.yaml",
        "configs/model/architecture/plddt_module.yaml",
        "configs/model/architecture/foldingdit_1.6B.yaml",
    ),
)
_SIMPLEFOLD_CONFIDENCE_SOURCE = SimpleFoldClosureSource(
    role="provider_runtime_source",
    source_name="ml-simplefold",
    package_name="simplefold",
    required_relative_files=(
        "configs/model/architecture/plddt_module.yaml",
        "configs/model/architecture/foldingdit_1.6B.yaml",
    ),
)
_ESM2_SOURCE = SimpleFoldClosureSource(
    role="language_model_runtime_source",
    source_name="facebookresearch/esm",
    environment_key="esm2_source_root",
    runtime_group="esm2_source",
)

_CCD = SimpleFoldClosureFile(
    role="chemical_component_dictionary",
    environment_key="model_root",
    runtime_group="simplefold_models",
    runtime_filename="ccd.pkl",
)
_PLDDT = SimpleFoldClosureFile(
    role="confidence_output_head",
    environment_key="model_root",
    runtime_group="simplefold_models",
    runtime_filename="plddt.ckpt",
)
_SIMPLEFOLD_1_6B = SimpleFoldClosureFile(
    role="confidence_latent_model",
    environment_key="model_root",
    runtime_group="simplefold_models",
    runtime_filename="simplefold_1.6B.ckpt",
)
_SIMPLEFOLD_100M = SimpleFoldClosureFile(
    role="folding_model",
    environment_key="model_root",
    runtime_group="simplefold_models",
    runtime_filename="simplefold_100M.ckpt",
)
_ESM2 = SimpleFoldClosureFile(
    role="language_model",
    environment_key="esm2_model_root",
    runtime_group="esm2_models",
    runtime_filename="esm2_t36_3B_UR50D.pt",
)
_ESM2_CONTACT_REGRESSION = SimpleFoldClosureFile(
    role="language_model_contact_regression",
    environment_key="esm2_model_root",
    runtime_group="esm2_models",
    runtime_filename="esm2_t36_3B_UR50D-contact-regression.pt",
)


SIMPLEFOLD_FOLDING_ASSET_CLOSURE = SimpleFoldProviderAssetClosure(
    binding_id="folding.fold.simplefold_local",
    files=(
        _CCD,
        _ESM2,
        _ESM2_CONTACT_REGRESSION,
        _PLDDT,
        _SIMPLEFOLD_1_6B,
        _SIMPLEFOLD_100M,
    ),
    sources=(_SIMPLEFOLD_FOLDING_SOURCE, _ESM2_SOURCE),
)

SIMPLEFOLD_CONFIDENCE_ASSET_CLOSURE = SimpleFoldProviderAssetClosure(
    binding_id="folding.simplefold_confidence.simplefold_local",
    files=(_CCD, _ESM2, _PLDDT, _SIMPLEFOLD_1_6B),
    sources=(_SIMPLEFOLD_CONFIDENCE_SOURCE, _ESM2_SOURCE),
)
