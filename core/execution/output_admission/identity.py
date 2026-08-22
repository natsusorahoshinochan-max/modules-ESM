"""One-pass canonical encoding for fresh output identity sources."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import hashlib
from typing import Any

from core.operation import (
    EncodedOutputIdentities,
    EncodedOutputIdentity,
    OutputIdentitySource,
)
from datatypes.exact_reference import ExactContractReference


@dataclass(frozen=True, slots=True)
class _EncodedSource:
    port_type: ExactContractReference
    canonical_bytes: bytes
    content_digest: str


def _exact_port_type(port_type: Any) -> ExactContractReference:
    reference = port_type.reference()
    return ExactContractReference(
        contract_kind=reference["contract_kind"],
        contract_id=reference["contract_id"],
        contract_version=reference["contract_version"],
        contract_digest=reference["contract_digest"],
    )


class _FreshOutputIdentityEncoder:
    """Encode each exact fresh source object at most once per admission."""

    def __init__(self) -> None:
        self._encoded: dict[tuple[ExactContractReference, int], _EncodedSource] = {}

    def encode_value(
        self,
        *,
        port_type: Any,
        value: object,
    ) -> _EncodedSource:
        exact_port_type = _exact_port_type(port_type)
        cache_key = (exact_port_type, id(value))
        encoded = self._encoded.get(cache_key)
        if encoded is not None:
            return encoded
        canonical_bytes = port_type.encode(value)
        encoded = _EncodedSource(
            port_type=exact_port_type,
            canonical_bytes=canonical_bytes,
            content_digest=(
                "sha256:" + hashlib.sha256(canonical_bytes).hexdigest()
            ),
        )
        self._encoded[cache_key] = encoded
        return encoded

    def encode_intent_sources(
        self,
        sources: tuple[OutputIdentitySource, ...],
        source_port_types: Mapping[str, Any],
    ) -> EncodedOutputIdentities:
        if {source.source_role for source in sources} != set(source_port_types):
            raise ValueError(
                "output identity sources do not match the exact Port contract"
            )
        return EncodedOutputIdentities(
            tuple(
                EncodedOutputIdentity(
                    identity_id=source.identity_id,
                    port_type=encoded.port_type,
                    content_digest=encoded.content_digest,
                )
                for source in sources
                for encoded in (
                    self.encode_value(
                        port_type=source_port_types[source.source_role],
                        value=source.value,
                    ),
                )
            )
        )
