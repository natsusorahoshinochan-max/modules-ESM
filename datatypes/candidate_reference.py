"""Provider-independent identity for one Candidate data value."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import re
from typing import cast

from datatypes.identifiers import validate_canonical_identifier

_CONTENT_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")


@dataclass(frozen=True, slots=True)
class CandidateDataReference:
    """Canonical content identity of one Candidate's data value."""

    candidate_id: str
    data_type_id: str
    content_digest: str

    def __post_init__(self) -> None:
        for field_name in ("candidate_id", "data_type_id"):
            validate_canonical_identifier(getattr(self, field_name), field_name)
        if (
            type(self.content_digest) is not str
            or _CONTENT_DIGEST.fullmatch(self.content_digest) is None
        ):
            raise ValueError(
                "content_digest must be a canonical sha256 digest"
            )

    def to_public(self) -> dict[str, str]:
        """Return the stable exact-field public representation."""
        return {
            "candidate_id": self.candidate_id,
            "data_type_id": self.data_type_id,
            "content_digest": self.content_digest,
        }

    @classmethod
    def from_public(
        cls,
        value: object,
    ) -> CandidateDataReference:
        """Construct from the stable exact-field public representation."""
        exact_fields = {
            "candidate_id",
            "data_type_id",
            "content_digest",
        }
        if not isinstance(value, Mapping) or set(value) != exact_fields:
            raise ValueError(
                "CandidateDataReference public value must contain exact fields"
            )
        return cls(
            candidate_id=cast(str, value["candidate_id"]),
            data_type_id=cast(str, value["data_type_id"]),
            content_digest=cast(str, value["content_digest"]),
        )
