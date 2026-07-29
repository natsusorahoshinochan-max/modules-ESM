"""Generic values for nominal Port Types that publish Run-bound artifacts."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ArtifactPayload:
    """Validated bytes awaiting generic Run-bound artifact publication."""

    body: bytes
    media_type: str
    filename: str
    candidate_id: str | None = None
