"""Exact ProteinMPNN source, checkpoint, and readiness admission."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from core.provider_support import (
    ProviderInstallationUnavailable,
    validate_provider_checkout,
)

PROTEINMPNN_REVISION = "8907e6671bfbfc92303b5f79c4b5e6ce47cdef57"
PROTEINMPNN_V_48_020_SHA256 = (
    "c9cb4a671d79604111231f8dbfc7c590e06f1197453b7a6854ac6661a642f5bd"
)
_LOCKED_CHECKPOINT = "vanilla_model_weights/v_48_020.pt"


class ProteinMPNNReadinessUnavailable(RuntimeError):
    """The exact ProteinMPNN source or checkpoint cannot be admitted."""


def _verify_provider_checkout(root: Path) -> None:
    provider_file = root / "protein_mpnn_utils.py"
    if not provider_file.is_file():
        raise ProteinMPNNReadinessUnavailable(
            "Configured ProteinMPNN provider root must contain "
            "protein_mpnn_utils.py"
        )
    try:
        validate_provider_checkout(root, PROTEINMPNN_REVISION)
    except ProviderInstallationUnavailable as error:
        raise ProteinMPNNReadinessUnavailable(
            "ProteinMPNN provider root is not the locked Git checkout"
        ) from error


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            while chunk := handle.read(1024 * 1024):
                digest.update(chunk)
    except OSError as error:
        raise ProteinMPNNReadinessUnavailable(
            "ProteinMPNN checkpoint is unavailable"
        ) from error
    return digest.hexdigest()


@dataclass(frozen=True)
class ProteinMPNNReadiness:
    ready: bool
    provider_root: Path | None = None
    checkpoint_path: Path | None = None
    detail: str | None = None


def validate_proteinmpnn_checkout(root: Path) -> Path:
    """Admit the configured checkout against the exact source identity."""
    resolved_root = root.expanduser().resolve()
    _verify_provider_checkout(resolved_root)
    return resolved_root


def validate_proteinmpnn_checkpoint(
    path: Path,
) -> Path:
    """Admit the configured checkpoint against its exact scientific identity."""
    digest = _sha256_file(path)
    if digest != PROTEINMPNN_V_48_020_SHA256:
        raise ProteinMPNNReadinessUnavailable(
            f"ProteinMPNN checkpoint SHA-256 mismatch for {path.name}: "
            f"expected {PROTEINMPNN_V_48_020_SHA256}, got {digest}"
        )
    return path


def _checkpoint_path(
    provider_root: Path,
) -> Path:
    """Resolve the fixed checkpoint path from trusted configuration."""
    return provider_root / _LOCKED_CHECKPOINT


def check_proteinmpnn_readiness(
    provider_root: Path,
) -> ProteinMPNNReadiness:
    """Report whether the locked provider and selected checkpoint are usable."""
    try:
        resolved_root = validate_proteinmpnn_checkout(provider_root)
        checkpoint_path = validate_proteinmpnn_checkpoint(
            _checkpoint_path(resolved_root),
        )
    except ProteinMPNNReadinessUnavailable as exc:
        return ProteinMPNNReadiness(ready=False, detail=str(exc))
    return ProteinMPNNReadiness(
        ready=True,
        provider_root=resolved_root,
        checkpoint_path=checkpoint_path,
    )
