"""Admission grammar for the folding package's SimpleFold asset closures."""

from __future__ import annotations

import hashlib
import shutil
import subprocess
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from modules.provider_contract import (
    SIMPLEFOLD_ARTIFACT_SHA256,
    SIMPLEFOLD_ESM2_ARTIFACT_SHA256,
    SIMPLEFOLD_ESM2_REVISION,
    SIMPLEFOLD_ESM2_SOURCE_TREE_SHA256,
    SIMPLEFOLD_REVISION,
    ProviderInstallationUnavailable,
    validate_installed_provider_checkout,
)


class SimpleFoldAssetClosureAdmissionError(RuntimeError):
    """One declared SimpleFold closure cannot be admitted at Readiness."""


@dataclass(frozen=True, slots=True)
class SimpleFoldClosureFile:
    """One result-affecting file selected by an exact Binding."""

    role: str
    environment_key: str
    staging_group: str
    runtime_filename: str
    sha256: str


@dataclass(frozen=True, slots=True)
class SimpleFoldClosureSource:
    """One exact source identity selected by an exact Binding."""

    role: str
    revision: str
    source_name: str | None = None
    package_name: str | None = None
    environment_key: str | None = None
    staging_group: str | None = None
    reviewed_files: tuple[str, ...] = ()
    source_tree_sha256: str | None = None

    def __post_init__(self) -> None:
        """Reject incomplete repository-owned declarations immediately."""
        reviewed_tree_fields = (
            self.environment_key,
            self.staging_group,
            self.reviewed_files,
            self.source_tree_sha256,
        )
        if self.package_name is not None:
            if any(reviewed_tree_fields):
                raise ValueError(
                    "SimpleFold source declaration mixes installed and "
                    "reviewed-tree sources"
                )
            return
        if (
            self.environment_key is None
            or self.staging_group is None
            or not self.reviewed_files
            or self.source_tree_sha256 is None
        ):
            raise ValueError("SimpleFold source declaration is incomplete")


@dataclass(frozen=True, slots=True)
class SimpleFoldProviderAssetClosure:
    """One Binding-owned immutable SimpleFold Provider Asset Closure."""

    binding_id: str
    files: tuple[SimpleFoldClosureFile, ...]
    sources: tuple[SimpleFoldClosureSource, ...]

    def file_sha256(self, environment_key: str) -> dict[str, str]:
        """Project exact file identity for one configured closure root."""
        return {
            entry.runtime_filename: entry.sha256
            for entry in self.files
            if entry.environment_key == environment_key
        }

    def readiness_prerequisite(self) -> dict[str, Any]:
        """Project the declaration into one Binding prerequisite."""
        files = tuple(
            {
                "role": entry.role,
                "environment_key": entry.environment_key,
                "runtime_filename": entry.runtime_filename,
                "sha256": entry.sha256,
            }
            for entry in self.files
        )
        sources: list[dict[str, Any]] = []
        for entry in self.sources:
            source: dict[str, Any] = {
                "role": entry.role,
                "revision": entry.revision,
            }
            if entry.source_name is not None:
                source["source_name"] = entry.source_name
            if entry.package_name is not None:
                source["package_name"] = entry.package_name
            if entry.environment_key is not None:
                source["environment_key"] = entry.environment_key
            if entry.reviewed_files:
                source["reviewed_files"] = entry.reviewed_files
            if entry.source_tree_sha256 is not None:
                source["source_tree_sha256"] = entry.source_tree_sha256
            sources.append(source)
        return {
            "files": files,
            "sources": tuple(sources),
            "path_source": "trusted_environment_configuration",
        }

    def provider_identity(self) -> dict[str, Any]:
        """Project exact result-affecting identity without local paths."""
        source_by_role = {source.role: source for source in self.sources}
        provider_source = source_by_role["provider_runtime_source"]
        language_source = source_by_role["language_model_runtime_source"]
        return {
            "source": provider_source.source_name,
            "source_revision": provider_source.revision,
            "esm2_source_revision": language_source.revision,
            "esm2_source_tree_sha256": language_source.source_tree_sha256,
            "esm2_artifact_sha256": self.file_sha256("esm2_model_root"),
            "artifact_sha256": self.file_sha256("model_root"),
        }


@dataclass(frozen=True, slots=True)
class StagedSimpleFoldProviderAssetClosure:
    """Private per-invocation layout populated from one admitted closure."""

    root: Path
    groups: tuple[tuple[str, Path], ...]

    def group_root(self, group: str) -> Path:
        """Return one declaration-owned staged group."""
        return dict(self.groups)[group]


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _git(root: Path, *args: str) -> str:
    try:
        completed = subprocess.run(
            ["git", "-C", str(root), *args],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (
        OSError,
        subprocess.CalledProcessError,
        subprocess.TimeoutExpired,
    ) as exc:
        raise SimpleFoldAssetClosureAdmissionError(
            "SimpleFold source is not a usable locked Git checkout"
        ) from exc
    return completed.stdout.strip()


def _configured_root(environment: Mapping[str, Any], key: str) -> Path:
    root = environment.get(key)
    if not isinstance(root, Path) or not root.is_dir():
        raise SimpleFoldAssetClosureAdmissionError(
            f"SimpleFold closure root is unavailable: {key}"
        )
    return root


def _source_tree_sha256(
    source_root: Path,
    reviewed_files: tuple[str, ...],
) -> str:
    digest = hashlib.sha256()
    for relative in sorted(reviewed_files):
        digest.update(relative.encode() + b"\0")
        digest.update(bytes.fromhex(_sha256_file(source_root / relative)))
    return digest.hexdigest()


def admit_simplefold_provider_asset_closure(
    closure: SimpleFoldProviderAssetClosure,
    environment: Mapping[str, Any],
) -> None:
    """Prove one exact Binding closure at its Readiness seam."""
    for source in closure.sources:
        if source.package_name is not None:
            try:
                validate_installed_provider_checkout(
                    source.package_name,
                    source.revision,
                )
            except ProviderInstallationUnavailable as error:
                raise SimpleFoldAssetClosureAdmissionError(
                    "SimpleFold installed source revision is unavailable"
                ) from error
            continue
        source_root = _configured_root(
            environment,
            cast(str, source.environment_key),
        )
        checkout_root = Path(
            _git(source_root, "rev-parse", "--show-toplevel")
        ).resolve()
        if checkout_root != source_root.resolve():
            raise SimpleFoldAssetClosureAdmissionError(
                "SimpleFold source root must be the Git checkout root"
            )
        if _git(source_root, "rev-parse", "HEAD") != source.revision:
            raise SimpleFoldAssetClosureAdmissionError(
                "SimpleFold source revision changed"
            )
        try:
            source_tree_sha256 = _source_tree_sha256(
                source_root,
                source.reviewed_files,
            )
        except OSError as error:
            raise SimpleFoldAssetClosureAdmissionError(
                "SimpleFold reviewed source tree is unavailable"
            ) from error
        if source_tree_sha256 != cast(str, source.source_tree_sha256):
            raise SimpleFoldAssetClosureAdmissionError(
                "SimpleFold reviewed source tree changed"
            )
    for file in closure.files:
        root = _configured_root(environment, file.environment_key)
        try:
            observed_sha256 = _sha256_file(root / file.runtime_filename)
        except OSError as error:
            raise SimpleFoldAssetClosureAdmissionError(
                "SimpleFold closure file is unavailable: "
                f"{file.runtime_filename}"
            ) from error
        if observed_sha256 != file.sha256:
            raise SimpleFoldAssetClosureAdmissionError(
                "SimpleFold closure file changed: "
                f"{file.runtime_filename}"
            )


def stage_simplefold_provider_asset_closure(
    closure: SimpleFoldProviderAssetClosure,
    environment: Mapping[str, Any],
    staging_directory: Path,
) -> StagedSimpleFoldProviderAssetClosure:
    """Copy only one admitted declaration without proving it again."""
    root = staging_directory / "simplefold_provider_assets"
    root.mkdir(parents=True, mode=0o700)
    group_names = {
        file.staging_group for file in closure.files
    } | {
        source.staging_group
        for source in closure.sources
        if source.staging_group is not None
    }
    groups = tuple(
        (group, root / group) for group in sorted(group_names)
    )
    for _, group_root in groups:
        group_root.mkdir(mode=0o700)
    group_roots = dict(groups)
    for file in closure.files:
        source_root = cast(Path, environment[file.environment_key])
        shutil.copyfile(
            source_root / file.runtime_filename,
            group_roots[file.staging_group] / file.runtime_filename,
        )
    for source in closure.sources:
        if source.staging_group is None:
            continue
        source_root = cast(
            Path,
            environment[cast(str, source.environment_key)],
        )
        destination_root = group_roots[source.staging_group]
        for relative in source.reviewed_files:
            destination = destination_root / relative
            destination.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
            shutil.copyfile(source_root / relative, destination)
    return StagedSimpleFoldProviderAssetClosure(root=root, groups=groups)


_ESM2_REVIEWED_RUNTIME_FILES = (
    "esm/__init__.py",
    "esm/axial_attention.py",
    "esm/constants.py",
    "esm/data.py",
    "esm/model/__init__.py",
    "esm/model/esm1.py",
    "esm/model/esm2.py",
    "esm/model/msa_transformer.py",
    "esm/modules.py",
    "esm/multihead_attention.py",
    "esm/pretrained.py",
    "esm/rotary_embedding.py",
    "esm/version.py",
)

_SIMPLEFOLD_SOURCE = SimpleFoldClosureSource(
    role="provider_runtime_source",
    source_name="ml-simplefold",
    package_name="simplefold",
    revision=SIMPLEFOLD_REVISION,
)
_ESM2_SOURCE = SimpleFoldClosureSource(
    role="language_model_runtime_source",
    source_name="facebookresearch/esm",
    environment_key="esm2_source_root",
    staging_group="esm2_source",
    revision=SIMPLEFOLD_ESM2_REVISION,
    reviewed_files=_ESM2_REVIEWED_RUNTIME_FILES,
    source_tree_sha256=SIMPLEFOLD_ESM2_SOURCE_TREE_SHA256,
)

_CCD = SimpleFoldClosureFile(
    role="chemical_component_dictionary",
    environment_key="model_root",
    staging_group="simplefold_models",
    runtime_filename="ccd.pkl",
    sha256=SIMPLEFOLD_ARTIFACT_SHA256["ccd.pkl"],
)
_PLDDT = SimpleFoldClosureFile(
    role="confidence_output_head",
    environment_key="model_root",
    staging_group="simplefold_models",
    runtime_filename="plddt.ckpt",
    sha256=SIMPLEFOLD_ARTIFACT_SHA256["plddt.ckpt"],
)
_SIMPLEFOLD_1_6B = SimpleFoldClosureFile(
    role="confidence_latent_model",
    environment_key="model_root",
    staging_group="simplefold_models",
    runtime_filename="simplefold_1.6B.ckpt",
    sha256=SIMPLEFOLD_ARTIFACT_SHA256["simplefold_1.6B.ckpt"],
)
_SIMPLEFOLD_100M = SimpleFoldClosureFile(
    role="folding_model",
    environment_key="model_root",
    staging_group="simplefold_models",
    runtime_filename="simplefold_100M.ckpt",
    sha256=SIMPLEFOLD_ARTIFACT_SHA256["simplefold_100M.ckpt"],
)
_ESM2 = SimpleFoldClosureFile(
    role="language_model",
    environment_key="esm2_model_root",
    staging_group="esm2_models",
    runtime_filename="esm2_t36_3B_UR50D.pt",
    sha256=SIMPLEFOLD_ESM2_ARTIFACT_SHA256["esm2_t36_3B_UR50D.pt"],
)
_ESM2_CONTACT_REGRESSION = SimpleFoldClosureFile(
    role="language_model_contact_regression",
    environment_key="esm2_model_root",
    staging_group="esm2_models",
    runtime_filename="esm2_t36_3B_UR50D-contact-regression.pt",
    sha256=SIMPLEFOLD_ESM2_ARTIFACT_SHA256[
        "esm2_t36_3B_UR50D-contact-regression.pt"
    ],
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
    sources=(_SIMPLEFOLD_SOURCE, _ESM2_SOURCE),
)

SIMPLEFOLD_CONFIDENCE_ASSET_CLOSURE = SimpleFoldProviderAssetClosure(
    binding_id="folding.simplefold_confidence.simplefold_local",
    files=(_CCD, _ESM2, _PLDDT, _SIMPLEFOLD_1_6B),
    sources=(_SIMPLEFOLD_SOURCE, _ESM2_SOURCE),
)
