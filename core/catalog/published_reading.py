"""Pure reading projections owned by the built-in nominal value codec."""

from __future__ import annotations

from typing import Any


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
