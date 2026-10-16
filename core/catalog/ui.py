"""Module-owned React editor declarations, independent of scientific identity."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class NodeEditorDefinition:
    editor_id: str
    title: str
    node_type_ids: tuple[str, ...]
    component: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "node_type_ids", tuple(self.node_type_ids))


@dataclass(frozen=True, slots=True)
class ModuleUiDefinition:
    extension_id: str
    resource_package: str
    entry: str
    styles: tuple[str, ...]
    react_major: int
    editors: tuple[NodeEditorDefinition, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "styles", tuple(self.styles))
        object.__setattr__(self, "editors", tuple(self.editors))
