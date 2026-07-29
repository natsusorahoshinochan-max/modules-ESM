"""Generic values for nominal Port Types that publish Run-bound artifacts."""

from __future__ import annotations

from dataclasses import dataclass
import re


_MEDIA_TYPE = re.compile(r"^[^\s/]+/[^\s/]+$")


def is_valid_artifact_media_type(value: object) -> bool:
    """Return whether a value uses the public type/subtype media grammar."""
    return (
        isinstance(value, str)
        and len(value) <= 256
        and _MEDIA_TYPE.fullmatch(value) is not None
    )


@dataclass(frozen=True, slots=True)
class ArtifactPayload:
    """Validated bytes awaiting generic Run-bound artifact publication."""

    body: bytes
    media_type: str
    filename: str
    candidate_id: str | None = None
