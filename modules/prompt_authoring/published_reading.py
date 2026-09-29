"""Read the actual published Prompt tracks, without running an authoring recipe."""

from __future__ import annotations

import json
from typing import Any

from core.catalog.published_reading import plain_published_value


def read_prompt(encoded: bytes) -> dict[str, Any]:
    fields = plain_published_value(json.loads(encoded)["value"])
    return {
        "residue_ids": fields["layout"]["residue_ids"],
        "sequence": fields["sequence"],
        "coordinates": fields["coordinates"],
        "secondary_structure": fields["secondary_structure"],
        "sasa": fields["sasa"],
        "function_annotations": fields["function_annotations"],
    }
