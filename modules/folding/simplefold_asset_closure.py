"""Admission grammar for the folding package's SimpleFold asset closures."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from core.provider_support import (
    ProviderInstallationUnavailable,
    validate_installed_provider_checkout,
    validate_provider_checkout,
)


SIMPLEFOLD_REVISION = "c7a5570a6be9f5c695126e27c804e77567209934"
SIMPLEFOLD_ESM2_REVISION = "2b369911bb5b4b0dda914521b9475cad1656b2ac"
SIMPLEFOLD_ESM2_SOURCE_TREE_SHA256 = (
    "0bdb3dcb95c534b967d84bcca090146bd6528328ab8e010b412da9a3e702ac83"
)
SIMPLEFOLD_ESM2_ARTIFACT_SHA256 = {
    "esm2_t36_3B_UR50D.pt": (
        "7de8b4082ba15891959ab368b77ce3886697af1efb16d3c9e9e7b0c5d3f07500"
    ),
    "esm2_t36_3B_UR50D-contact-regression.pt": (
        "4da500eab246481dc9c8c95bc7b1d02f2803d761c380b0e95186d4a07d0fc84e"
    ),
}
SIMPLEFOLD_ARTIFACT_SHA256 = {
    "simplefold_100M.ckpt": (
        "4cd0b8a0b317a6ab8634444fffd78ce84cfd49c20fe927b83c76c36fda5f54bd"
    ),
    "simplefold_1.6B.ckpt": (
        "aaac2d73dcc59c61153c58a1d56e74a8ada9d6057d67000f7836f3c87325312b"
    ),
    "plddt.ckpt": (
        "cb32fa9cdc9e80406b793a8c09a929077534d9991a1d08f4c159d2e4ed81315f"
    ),
    "ccd.pkl": (
        "2d3b2f03a3c5665944adba51e33263511e51b21c9cd05d902f9c4b7c1e58d2f4"
    ),
}


class SimpleFoldAssetClosureAdmissionError(RuntimeError):
    """One declared SimpleFold closure cannot be admitted at Readiness."""


@dataclass(frozen=True, slots=True)
class SimpleFoldClosureFile:
    """One result-affecting file selected by an exact Binding."""

    role: str
    environment_key: str
    runtime_group: str
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
    runtime_group: str | None = None
    reviewed_files: tuple[str, ...] = ()
    source_tree_sha256: str | None = None

    def __post_init__(self) -> None:
        """Reject incomplete repository-owned declarations immediately."""
        reviewed_tree_fields = (
            self.environment_key,
            self.runtime_group,
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
            or self.runtime_group is None
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
class BoundSimpleFoldProviderAssetClosure:
    """Runtime roots bound from one closure admitted at Readiness."""

    groups: tuple[tuple[str, Path], ...]

    def group_root(self, group: str) -> Path:
        """Return one declaration-owned runtime root."""
        return dict(self.groups)[group]


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _configured_root(environment: Mapping[str, Any], key: str) -> Path:
    root = cast(Path, environment[key])
    if not root.is_dir():
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
        try:
            validate_provider_checkout(source_root, source.revision)
        except ProviderInstallationUnavailable as error:
            raise SimpleFoldAssetClosureAdmissionError(
                "SimpleFold source is not the locked Git checkout"
            ) from error
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


def bind_simplefold_provider_asset_closure(
    closure: SimpleFoldProviderAssetClosure,
    environment: Mapping[str, Any],
) -> BoundSimpleFoldProviderAssetClosure:
    """Bind roots already proved by the Binding's Readiness boundary."""
    group_roots: dict[str, Path] = {}

    def bind(group: str, environment_key: str) -> None:
        root = cast(Path, environment[environment_key])
        prior = group_roots.setdefault(group, root)
        if prior != root:
            raise ValueError("SimpleFold runtime group has conflicting roots")

    for file in closure.files:
        bind(file.runtime_group, file.environment_key)
    for source in closure.sources:
        if source.runtime_group is None:
            continue
        bind(source.runtime_group, cast(str, source.environment_key))
    return BoundSimpleFoldProviderAssetClosure(
        groups=tuple(sorted(group_roots.items())),
    )


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
    runtime_group="esm2_source",
    revision=SIMPLEFOLD_ESM2_REVISION,
    reviewed_files=_ESM2_REVIEWED_RUNTIME_FILES,
    source_tree_sha256=SIMPLEFOLD_ESM2_SOURCE_TREE_SHA256,
)

_CCD = SimpleFoldClosureFile(
    role="chemical_component_dictionary",
    environment_key="model_root",
    runtime_group="simplefold_models",
    runtime_filename="ccd.pkl",
    sha256=SIMPLEFOLD_ARTIFACT_SHA256["ccd.pkl"],
)
_PLDDT = SimpleFoldClosureFile(
    role="confidence_output_head",
    environment_key="model_root",
    runtime_group="simplefold_models",
    runtime_filename="plddt.ckpt",
    sha256=SIMPLEFOLD_ARTIFACT_SHA256["plddt.ckpt"],
)
_SIMPLEFOLD_1_6B = SimpleFoldClosureFile(
    role="confidence_latent_model",
    environment_key="model_root",
    runtime_group="simplefold_models",
    runtime_filename="simplefold_1.6B.ckpt",
    sha256=SIMPLEFOLD_ARTIFACT_SHA256["simplefold_1.6B.ckpt"],
)
_SIMPLEFOLD_100M = SimpleFoldClosureFile(
    role="folding_model",
    environment_key="model_root",
    runtime_group="simplefold_models",
    runtime_filename="simplefold_100M.ckpt",
    sha256=SIMPLEFOLD_ARTIFACT_SHA256["simplefold_100M.ckpt"],
)
_ESM2 = SimpleFoldClosureFile(
    role="language_model",
    environment_key="esm2_model_root",
    runtime_group="esm2_models",
    runtime_filename="esm2_t36_3B_UR50D.pt",
    sha256=SIMPLEFOLD_ESM2_ARTIFACT_SHA256["esm2_t36_3B_UR50D.pt"],
)
_ESM2_CONTACT_REGRESSION = SimpleFoldClosureFile(
    role="language_model_contact_regression",
    environment_key="esm2_model_root",
    runtime_group="esm2_models",
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
