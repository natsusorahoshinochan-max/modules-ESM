"""Read the persisted ESMC value without manufacturing absent outputs."""
import json
from typing import Any


def read_representation(encoded: bytes) -> dict[str, Any]:
    return json.loads(encoded)["value"]
