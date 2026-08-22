"""Exact ProteinMPNN source and checkpoint identities."""

from __future__ import annotations


PROTEINMPNN_REVISION = "8907e6671bfbfc92303b5f79c4b5e6ce47cdef57"
PROTEINMPNN_V_48_020_SHA256 = (
    "c9cb4a671d79604111231f8dbfc7c590e06f1197453b7a6854ac6661a642f5bd"
)


def proteinmpnn_provider_identity() -> dict[str, str]:
    """Project the package-owned exact Provider identity."""
    return {
        "source": "ProteinMPNN",
        "source_revision": PROTEINMPNN_REVISION,
        "checkpoint_sha256": PROTEINMPNN_V_48_020_SHA256,
    }
