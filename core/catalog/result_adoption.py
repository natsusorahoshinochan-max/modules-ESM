"""Module declaration for restoring a published value as a workflow input."""
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ResultSourceDefinition:
    port_type_id: str
    node_type_id: str
    binding_id: str
    output_port: str = 'value'
