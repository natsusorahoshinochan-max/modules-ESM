"""Read-only graph facts available to module authoring actions."""

from collections.abc import Mapping
from dataclasses import dataclass

from core.catalog.declarations import NodePortDefinition
from core.workflow.document import WorkflowNodeInstance


@dataclass(frozen=True, slots=True)
class NodeOutputReference:
    node_id: str
    output_port: str


@dataclass(frozen=True, slots=True)
class WorkflowGraphDescription:
    nodes_by_id: Mapping[str, WorkflowNodeInstance]
    input_sources: Mapping[str, Mapping[str, tuple[tuple[int, NodeOutputReference], ...]]]
    output_ports_by_node: Mapping[str, Mapping[str, NodePortDefinition]]
    node_order: tuple[str, ...]
