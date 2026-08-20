"""Canonical Result replay snapshots for trusted test Cache boundaries."""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType
from typing import Any

from core.port_types import FrozenCatalog, PortValueError
from core.operation import AdmittedPort
from core.value_admission import admitted_port_values
from core.workflow_v2 import ExecutionPlanNode


def admitted_replay_outputs(
    *,
    catalog: FrozenCatalog,
    node: ExecutionPlanNode,
    outputs: Mapping[str, Any],
) -> Mapping[tuple[str, str], AdmittedPort]:
    """Admit fixture outputs once, as a conforming Cache source would."""
    declarations = {
        name: port.declaration
        for name, port in node._runtime.output_ports.items()
    }
    candidate_data_port_types = {
        definition.type_id: definition
        for definition in catalog.port_types
    }
    if set(outputs) - set(declarations):
        raise PortValueError("Replay fixture supplied an unknown output Port")

    snapshots: dict[tuple[str, str], AdmittedPort] = {}
    for output_port, supplied in outputs.items():
        declaration = declarations[output_port]
        port_type = node._runtime.output_ports[output_port].port_type
        values = (
            tuple(supplied)
            if declaration["multiplicity"] == "many"
            else (supplied,)
        )
        snapshots[(node.node_id, output_port)] = admitted_port_values(
            port_type=port_type,
            multiplicity=declaration["multiplicity"],
            values=values,
            candidate_data_port_types=candidate_data_port_types,
        )
    return MappingProxyType(snapshots)
