"""The alignment codec already publishes the complete plain scientific record."""

from __future__ import annotations

import json
from typing import Any


def read_alignment(encoded: bytes) -> dict[str, Any]:
    """Retain every field emitted by alignment_evidence_to_wire, unchanged."""
    return json.loads(encoded)["value"]
