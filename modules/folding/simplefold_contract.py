"""Lightweight identities for the folding package's SimpleFold boundary."""

from __future__ import annotations

from modules.provider_contract import (
    SIMPLEFOLD_ARTIFACT_SHA256,
    SIMPLEFOLD_ESM2_ARTIFACT_SHA256,
)


SIMPLEFOLD_FOLDING_ARTIFACTS = (
    "ccd.pkl",
    "plddt.ckpt",
    "simplefold_1.6B.ckpt",
    "simplefold_100M.ckpt",
)
SIMPLEFOLD_CONFIDENCE_ARTIFACTS = (
    "ccd.pkl",
    "plddt.ckpt",
    "simplefold_1.6B.ckpt",
)
SIMPLEFOLD_CONFIDENCE_ESM2_ARTIFACTS = ("esm2_t36_3B_UR50D.pt",)
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
    return {
        name: SIMPLEFOLD_ARTIFACT_SHA256[name]
        for name in SIMPLEFOLD_FOLDING_ARTIFACTS
    }


def simplefold_confidence_artifact_sha256() -> dict[str, str]:
    """Return the exact SimpleFold model/data closure used by confidence."""
    return {
        name: SIMPLEFOLD_ARTIFACT_SHA256[name]
        for name in SIMPLEFOLD_CONFIDENCE_ARTIFACTS
    }


def simplefold_confidence_esm2_artifact_sha256() -> dict[str, str]:
    """Return the representation-only ESM2 weight closure."""
    return {
        name: SIMPLEFOLD_ESM2_ARTIFACT_SHA256[name]
        for name in SIMPLEFOLD_CONFIDENCE_ESM2_ARTIFACTS
    }
