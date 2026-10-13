"""Compiler-plan evidence used by Run Runtime."""

from __future__ import annotations

from core.execution.ledger import (
    ArtifactOutputEvidence,
    PlanNodeEvidence,
    PlanRequiredInputEvidence,
    PlanValueSourceEvidence,
)
from core.execution.scope import RunExecutionScope
from core.workflow.plan import ExecutionPlan


def plan_evidence(
    plan: ExecutionPlan,
    scope: RunExecutionScope | None = None,
) -> tuple[PlanNodeEvidence, ...]:
    """Project the plan facts needed for scientific evidence and causality."""
    active = (
        set(scope.execution_node_ids) | set(scope.reused_node_ids)
        if scope is not None else {node.node_id for node in plan.nodes}
    )
    return tuple(
        PlanNodeEvidence(
            node_id=node.node_id,
            dependencies=node._runtime.dependencies,
            required_input_sources=tuple(
                PlanRequiredInputEvidence(
                    input_port=input_port,
                    sources=tuple(
                        sorted(
                            (
                                PlanValueSourceEvidence(
                                    source.node_id,
                                    source.output_port,
                                )
                                for source in sources
                            ),
                            key=lambda source: (
                                source.node_id,
                                source.output_port,
                            ),
                        )
                    ),
                )
                for input_port, sources in sorted(
                    node._runtime.required_input_sources.items()
                )
            ),
            node_type=node.node_type,
            binding=node.binding,
            method=node.method,
            execution_route=node._runtime.execution_route,
            artifact_outputs=tuple(
                ArtifactOutputEvidence(
                    output_port=output.output_port,
                    artifact_kind=output.artifact_kind,
                    artifact_media_type=output.artifact_media_type,
                    port_type=output.port_type,
                    accepted_media_types=output.accepted_media_types,
                )
                for output in node._runtime.artifact_outputs
            ),
            selection_consumer=bool(
                node._runtime.selection_candidate_output_port is not None
                and (scope is None or node.node_id in scope.execution_node_ids)
            ),
        )
        for node in plan.nodes
        if node.node_id in active
    )
