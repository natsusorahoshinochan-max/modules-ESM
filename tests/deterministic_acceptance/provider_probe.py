"""Test-side observation of deterministic provider calls."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ProviderCallProbe:
    """Read provider-owned telemetry without crossing the backend client seam."""

    path: Path

    def calls(self) -> list[str]:
        return self.path.read_text().splitlines() if self.path.exists() else []
