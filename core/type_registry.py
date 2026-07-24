"""Type registry: maps string type IDs for port compatibility checking."""

from dataclasses import dataclass, field


@dataclass
class TypeInfo:
    """Registered type definition."""

    type_id: str
    display_name: str = ""
    description: str = ""


class TypeRegistry:
    """Registry of all known port type IDs.

    Port compatibility is checked by exact string match on type_id.
    The engine never inspects the internal structure of data passing through ports.
    """

    def __init__(self) -> None:
        self._types: dict[str, TypeInfo] = {}

    def register(self, type_id: str, display_name: str = "", description: str = "") -> None:
        """Register a new type ID. Raises ValueError on duplicate."""
        if type_id in self._types:
            raise ValueError(f"Type ID '{type_id}' is already registered")
        self._types[type_id] = TypeInfo(
            type_id=type_id,
            display_name=display_name,
            description=description,
        )

    def is_compatible(self, source_type: str, target_type: str) -> bool:
        """Check whether two type IDs are compatible (exact match)."""
        return source_type == target_type

    def get(self, type_id: str) -> TypeInfo | None:
        """Get type info by ID, or None if not registered."""
        return self._types.get(type_id)

    def list_all(self) -> list[str]:
        """Return all registered type ID strings."""
        return sorted(self._types.keys())

    def __len__(self) -> int:
        return len(self._types)
