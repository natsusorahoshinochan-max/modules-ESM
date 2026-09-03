"""Exact Port Types for the closed ProteinPrompt aggregate."""

from __future__ import annotations

from typing import Any

from core.catalog import _port_value_codec as _value_codec
from core.catalog.port_contract import (
    BehaviorReference,
    PortTypeDefinition,
)
from datatypes.prompt import ProteinPrompt

from .prompts import validate_protein_prompt


def _validate_prompt(value: object) -> None:
    validate_protein_prompt(value)


def _prompt_to_wire(prompt: ProteinPrompt) -> Any:
    return _value_codec._value_to_wire(prompt)


def _prompt_from_wire(value: Any) -> Any:
    return _value_codec._wire_to_value(value)


PROTEIN_PROMPT_PORT_TYPE = PortTypeDefinition(
    type_id="protein.prompt",
    validator=BehaviorReference(
        "prompt_authoring.protein.prompt/validate",
        {
            "accepted_value_kind": "canonical_protein_prompt",
            "complete_values_only": True,
            "aggregate_contract": {
                "layout": "one identity-complete ResidueLayout",
                "sequence": "always present, all-null allowed",
                "coordinates": "always present, all-null allowed",
                "secondary_structure": "JSON null means whole-track absent",
                "sasa": "JSON null means whole-track absent",
                "function_annotations": (
                    "identity-addressed intervals within the layout"
                ),
            },
            "absent_and_all_null_distinct": True,
        },
    ),
    codec=BehaviorReference(
        "prompt_authoring.protein.prompt/canonical-json-codec",
        {
            "canonicalization": "RFC 8785",
            "character_encoding": "UTF-8",
            "envelope_namespace": "protein-workbench-port-value/v2",
            "wire_shape": "closed-ProteinPrompt-dataclass",
        },
    ),
    content_identity=BehaviorReference(
        "prompt_authoring.protein.prompt/content-sha256",
        {
            "digest_algorithm": "SHA-256",
            "digest_input": "canonical_codec_bytes",
        },
    ),
    runtime_validator=_validate_prompt,
    runtime_to_wire=_prompt_to_wire,
    runtime_from_wire=_prompt_from_wire,
)


PROMPT_PORT_TYPES = (PROTEIN_PROMPT_PORT_TYPE,)
