"""Pure reading projections owned by the built-in nominal value codec."""

from __future__ import annotations

import json
from typing import Any

from core.catalog._port_value_codec import _wire_to_value
from datatypes.observation import (
    observation_context_profile,
    observation_context_profile_descriptor,
)


def plain_published_value(value: Any) -> Any:
    """Remove our codec tags from already-published values without admission."""
    if isinstance(value, list):
        return [plain_published_value(item) for item in value]
    if not isinstance(value, dict):
        return value
    if "$dataclass" in value:
        return {
            name: plain_published_value(item)
            for name, item in value["fields"].items()
        }
    if "$tuple" in value:
        return [plain_published_value(item) for item in value["$tuple"]]
    return {key: plain_published_value(item) for key, item in value["$map"]}


def read_scores(encoded: bytes) -> dict[str, Any]:
    fields = json.loads(encoded)["value"]["fields"]
    entries = []
    for encoded_entry in fields["entries"]:
        entry = plain_published_value(encoded_entry)
        context = _wire_to_value(encoded_entry["fields"]["context"])
        entry["context_profile"] = observation_context_profile_descriptor(
            observation_context_profile(context),
        )
        entries.append(entry)
    return {"collection_id": fields["collection_id"], "entries": entries}


def read_sequence(encoded: bytes) -> dict[str, Any]:
    return plain_published_value(json.loads(encoded)["value"])


def read_structure(encoded: bytes) -> dict[str, str]:
    structure = _wire_to_value(json.loads(encoded)["value"])
    return {"text": structure.text, "format": structure.format}
