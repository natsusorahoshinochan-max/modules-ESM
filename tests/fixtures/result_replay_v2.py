"""Canonical Result replay snapshots for trusted test Cache boundaries."""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType
from typing import Any

from core.catalog.model import (
    FrozenCatalog,
)
from core.catalog.port_contract import (
    PortValueError,
)
from core.operation import AdmittedPort
from tests.support.output_admission import admit_fixture_port
from core.workflow.plan import ExecutionPlanNode


def admitted_replay_outputs(
    *,
    catalog: FrozenCatalog,
    node: ExecutionPlanNode,
    outputs: Mapping[str, Any],
) -> Mapping[tuple[str, str], AdmittedPort]:
    """Admit fixture outputs once, as a conforming Cache source would."""
    ports = node._runtime.output_ports
    candidate_data_port_types = {
        definition.type_id: definition
        for definition in catalog.port_types
    }
    if set(outputs) - set(ports):
        raise PortValueError("Replay fixture supplied an unknown output Port")

    snapshots: dict[tuple[str, str], AdmittedPort] = {}
    for output_port, supplied in outputs.items():
        port = ports[output_port]
        values = (
            tuple(supplied)
            if port.multiplicity == "many"
            else (supplied,)
        )
        snapshots[(node.node_id, output_port)] = admit_fixture_port(
            port_type=port.port_type,
            multiplicity=port.multiplicity,
            values=values,
            candidate_data_port_types=candidate_data_port_types,
        )
    return MappingProxyType(snapshots)
