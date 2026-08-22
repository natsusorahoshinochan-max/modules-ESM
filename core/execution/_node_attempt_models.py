"""Typed facts shared inside the Node Execution Attempt owner."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Literal

from core.execution.resources import CancellationControl, RunResources
from core.operation import AdmittedPort
from core.project.manager import ProjectInputDescriptor
from core.workflow.plan import ExecutionPlanNode


class ExecutionTermination(RuntimeError):
    """A bounded terminal conclusion reported by a started engine seam."""

    def __init__(self, status: str) -> None:
        self.status = status
        super().__init__("Execution terminated without public diagnostics")


@dataclass(frozen=True, slots=True)
class AttemptOutcome:
    """The only Node Execution Attempt outcome visible to Run scheduling."""

    disposition: Literal[
        "succeeded",
        "failed",
        "cancelled",
        "interrupted",
        "blocked",
    ]
    admitted_outputs: Mapping[
        tuple[str, str],
        AdmittedPort,
    ] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "admitted_outputs",
            MappingProxyType(dict(self.admitted_outputs)),
        )


@dataclass(frozen=True, slots=True)
class AttemptSpec:
    """Run-scoped admitted facts for one schedulable Plan Node."""

    project_id: str
    run_id: str
    node: ExecutionPlanNode
    candidate_data_port_types: Mapping[str, Any]
    admitted_inputs: Mapping[str, AdmittedPort]
    cancellation: CancellationControl
    cache_bypassed: bool

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "candidate_data_port_types",
            MappingProxyType(dict(self.candidate_data_port_types)),
        )
        object.__setattr__(
            self,
            "admitted_inputs",
            MappingProxyType(dict(self.admitted_inputs)),
        )


@dataclass(slots=True)
class _NodeExecutionAttemptState:
    """Closed internal state for one Node Execution Attempt lifecycle."""

    project_id: str
    run_id: str
    node: ExecutionPlanNode
    candidate_data_port_types: Mapping[str, Any]
    cancellation: CancellationControl
    node_attempt_id: str
    operation_attempt_id: str
    inputs: Mapping[str, AdmittedPort]
    project_inputs: Mapping[str, tuple[ProjectInputDescriptor, bytes]]
    resource_identities: tuple[Mapping[str, Any], ...]
    cache_eligible: bool = False
    resolution: Literal["executed", "cache_replayed"] = "executed"
    resources: RunResources | None = None
    operation_started: bool = False


__all__ = ["AttemptOutcome", "AttemptSpec", "ExecutionTermination"]
