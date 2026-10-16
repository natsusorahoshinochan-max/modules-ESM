"""Published sequence and structure reading owned by protein I/O."""
import json
from typing import Any
from core.catalog.published_reading import plain_published_value
from core.catalog._port_value_codec import _wire_to_value

def read_sequence(encoded: bytes) -> dict[str, Any]:
    return plain_published_value(json.loads(encoded)["value"])


def read_structure(encoded: bytes) -> dict[str, str]:
    structure = _wire_to_value(json.loads(encoded)["value"])
    return {"text": structure.text, "format": structure.format}
