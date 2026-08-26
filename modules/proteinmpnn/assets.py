"""ProteinMPNN source, checkpoint, and readiness paths."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

_CHECKPOINT = "vanilla_model_weights/v_48_020.pt"


class ProteinMPNNReadinessUnavailable(RuntimeError):
    """The configured ProteinMPNN source or checkpoint is unavailable."""


def _verify_provider_root(root: Path) -> None:
    provider_file = root / "protein_mpnn_utils.py"
    if not provider_file.is_file():
        raise ProteinMPNNReadinessUnavailable(
            "Configured ProteinMPNN provider root must contain "
            "protein_mpnn_utils.py"
        )


@dataclass(frozen=True)
class ProteinMPNNReadiness:
    ready: bool
    provider_root: Path | None = None
    checkpoint_path: Path | None = None
    detail: str | None = None


def _provider_root(root: Path) -> Path:
    resolved_root = root.expanduser().resolve()
    _verify_provider_root(resolved_root)
    return resolved_root


def _checkpoint_path(
    provider_root: Path,
) -> Path:
    path = provider_root / _CHECKPOINT
    if not path.is_file():
        raise ProteinMPNNReadinessUnavailable(
            "ProteinMPNN checkpoint is unavailable"
        )
    return path


def check_proteinmpnn_readiness(
    provider_root: Path,
) -> ProteinMPNNReadiness:
    """Report whether the configured provider paths are usable."""
    try:
        resolved_root = _provider_root(provider_root)
        checkpoint_path = _checkpoint_path(resolved_root)
    except ProteinMPNNReadinessUnavailable as exc:
        return ProteinMPNNReadiness(ready=False, detail=str(exc))
    return ProteinMPNNReadiness(
        ready=True,
        provider_root=resolved_root,
        checkpoint_path=checkpoint_path,
    )
