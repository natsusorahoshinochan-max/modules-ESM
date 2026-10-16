"""Module-owned React editor and result viewer declarations, independent of scientific identity."""

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
class ResultViewerDefinition:
    viewer_id: str
    title: str
    port_type_id: str
    component: str
    is_default: bool = False


@dataclass(frozen=True, slots=True)
class RunViewerDefinition:
    viewer_id: str
    title: str
    port_type_ids: tuple[str, ...]
    component: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "port_type_ids", tuple(self.port_type_ids))


@dataclass(frozen=True, slots=True)
class ModuleUiDefinition:
    extension_id: str
    resource_package: str
    entry: str
    styles: tuple[str, ...]
    react_major: int
    editors: tuple[NodeEditorDefinition, ...]
    viewers: tuple[ResultViewerDefinition, ...] = ()
    run_viewers: tuple[RunViewerDefinition, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "styles", tuple(self.styles))
        object.__setattr__(self, "editors", tuple(self.editors))
        object.__setattr__(self, "viewers", tuple(self.viewers))
        object.__setattr__(self, "run_viewers", tuple(self.run_viewers))
