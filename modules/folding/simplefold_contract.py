"""Binding identities derived from the owned SimpleFold asset closures."""

from __future__ import annotations

from .simplefold_asset_closure import (
    SIMPLEFOLD_CONFIDENCE_ASSET_CLOSURE,
    SIMPLEFOLD_FOLDING_ASSET_CLOSURE,
)


SIMPLEFOLD_FOLDING_ARTIFACTS = tuple(
    entry.runtime_filename
    for entry in SIMPLEFOLD_FOLDING_ASSET_CLOSURE.files
    if entry.environment_key == "model_root"
)
SIMPLEFOLD_CONFIDENCE_ARTIFACTS = tuple(
    entry.runtime_filename
    for entry in SIMPLEFOLD_CONFIDENCE_ASSET_CLOSURE.files
    if entry.environment_key == "model_root"
)
SIMPLEFOLD_CONFIDENCE_ESM2_ARTIFACTS = tuple(
    entry.runtime_filename
    for entry in SIMPLEFOLD_CONFIDENCE_ASSET_CLOSURE.files
    if entry.environment_key == "esm2_model_root"
)
SIMPLEFOLD_MODEL = "simplefold_100M"
SIMPLEFOLD_DEVICE = "cpu"
SIMPLEFOLD_CONFIDENCE_DEVICE = "cpu"
SIMPLEFOLD_CONFIDENCE_FEATURIZATION = (
    "simplefold-existing-structure-featurization/v2"
)
SIMPLEFOLD_CONFIDENCE_ADAPTER = (
    "protein-workbench-simplefold-confidence-adapter/v2"
)


def simplefold_folding_artifact_sha256() -> dict[str, str]:
    """Return the exact checkpoint closure used by the folding Binding."""
    return SIMPLEFOLD_FOLDING_ASSET_CLOSURE.file_sha256("model_root")


def simplefold_folding_esm2_artifact_sha256() -> dict[str, str]:
    """Return the exact ESM2 weight closure used by folding."""
    return SIMPLEFOLD_FOLDING_ASSET_CLOSURE.file_sha256("esm2_model_root")


def simplefold_confidence_artifact_sha256() -> dict[str, str]:
    """Return the exact SimpleFold model/data closure used by confidence."""
    return SIMPLEFOLD_CONFIDENCE_ASSET_CLOSURE.file_sha256("model_root")


def simplefold_confidence_esm2_artifact_sha256() -> dict[str, str]:
    """Return the representation-only ESM2 weight closure."""
    return SIMPLEFOLD_CONFIDENCE_ASSET_CLOSURE.file_sha256(
        "esm2_model_root"
    )
