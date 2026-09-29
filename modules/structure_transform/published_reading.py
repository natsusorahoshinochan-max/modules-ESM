"""Reading facts from already-published exact axes; never reconstruct from PDB."""

from __future__ import annotations

import json
from typing import Any


def read_candidate_sequences(encoded: bytes) -> dict[str, Any]:
    value = json.loads(encoded)["value"]
    return {
        "entries": [
            {"subject": entry["subject"], "sequence": entry["residue_axis"]["sequence"]}
            for entry in value["entries"]
        ],
    }


def read_axis_layout(encoded: bytes) -> dict[str, Any]:
    value = json.loads(encoded)["value"]
    return {
        "residue_ids": value["layout"]["fields"]["residue_ids"],
        "chain_ids": [segment["chain_id"] for segment in value["segments"]],
    }
