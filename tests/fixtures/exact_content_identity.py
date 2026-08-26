"""Test-owned exact built-in content-identity definitions for fixed fixtures."""

from core.catalog.port_contract import (
    BehaviorReference,
    PortTypeDefinition,
)
from core.catalog.port_contract import (
    PORT_VALUE_NAMESPACE,
)


def exact_content_identity(
    type_id: str,
    value_kind: str,
) -> PortTypeDefinition:
    """Bind one exact built-in codec without consulting a runtime Catalog."""
    behavior_prefix = f"protein-workbench.port-type/{type_id}"
    return PortTypeDefinition(
        type_id=type_id,
        validator=BehaviorReference(
            f"{behavior_prefix}/validate",
            {
                "accepted_value_kind": value_kind,
                "complete_values_only": True,
            },
        ),
        codec=BehaviorReference(
            f"{behavior_prefix}/canonical-json-codec",
            {
                "canonicalization": "RFC 8785",
                "character_encoding": "UTF-8",
                "envelope_namespace": PORT_VALUE_NAMESPACE,
                "value_kind": value_kind,
            },
        ),
        content_identity=BehaviorReference(
            f"{behavior_prefix}/content-sha256",
            {
                "digest_algorithm": "SHA-256",
                "digest_input": "canonical_codec_bytes",
                "digest_representation": (
                    "sha256:<64 lowercase hexadecimal digits>"
                ),
            },
        ),
    )
