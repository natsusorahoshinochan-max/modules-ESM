"""Derived Run selection over one immutable source Run."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from core.execution._run_runtime_registry import _RunRegistry
from core.execution.ledger import DerivedRunReference, V2RunError
from core.workflow.plan import ExecutionPlan


class _DerivedRunStarter:
    """Resolve derived selection, then invoke normal Run admission."""

    def __init__(
        self,
        *,
        registry: _RunRegistry,
        start_background: Callable[..., dict[str, Any]],
    ) -> None:
        self._registry = registry
        self._start_background = start_background

    @staticmethod
    def _forced_node_closure(
        plan: ExecutionPlan,
        selected_node_ids: frozenset[str],
    ) -> frozenset[str]:
        forced = set(selected_node_ids)
        changed = True
        while changed:
            changed = False
            for node in plan.nodes:
                if (
                    node.node_id not in forced
                    and any(
                        dependency in forced
                        for dependency in node._runtime.dependencies
                    )
                ):
                    forced.add(node.node_id)
                    changed = True
        return frozenset(forced)

    def start(
        self,
        project_id: str,
        *,
        source_run_id: str,
        policy: str,
        node_ids: list[str],
        client_request_id: str,
    ) -> dict[str, Any]:
        """Start a new Run from one immutable terminal source reference."""
        source = self._registry.require_record(project_id, source_run_id)
        source_projection = source.ledger.projection()
        terminal_sequence = source_projection.terminal_sequence
        if terminal_sequence is None:
            raise V2RunError(
                "malformed_request",
                "Start Derived Run requires a terminal source Run",
                details={"field_path": ["source_run_id"]},
            )
        compiled = source.compiled
        if compiled is None:
            raise V2RunError(
                "compile_rejected",
                "Derived Run source Execution Plan is unavailable",
                details={
                    "issues": [
                        {
                            "code": "source_execution_plan_unavailable",
                            "severity": "error",
                            "message": (
                                "Derived Run requires the exact in-memory "
                                "Execution Plan retained by its source Run"
                            ),
                            "field_path": ["source_run_id"],
                        }
                    ]
                },
            )
        plan = compiled.execution_plan
        plan_node_ids = tuple(node.node_id for node in plan.nodes)
        selected = frozenset(node_ids)
        if (
            not node_ids
            or len(selected) != len(node_ids)
            or not selected <= frozenset(plan_node_ids)
        ):
            raise V2RunError(
                "compile_rejected",
                "Derived Run selection is not a closed Plan selection",
                details={
                    "issues": [
                        {
                            "code": "invalid_derived_node_selection",
                            "severity": "error",
                            "message": (
                                "node_ids must be unique Node Instances in "
                                "the immutable source Execution Plan"
                            ),
                            "field_path": ["node_ids"],
                        }
                    ]
                },
            )
        source_outcomes = {
            disposition.node_id: disposition.outcome
            for disposition in source_projection.node_dispositions
        }
        if policy == "retry_failed" and any(
            source_outcomes.get(node_id) != "failed"
            for node_id in selected
        ):
            raise V2RunError(
                "compile_rejected",
                "retry_failed may select only failed source Nodes",
                details={
                    "issues": [
                        {
                            "code": "retry_requires_failed_source_node",
                            "severity": "error",
                            "message": (
                                "retry_failed node_ids must identify failed "
                                "source Run Node Dispositions"
                            ),
                            "field_path": ["node_ids"],
                        }
                    ]
                },
            )
        forced = (
            selected
            if policy == "retry_failed"
            else self._forced_node_closure(plan, selected)
        )
        selected_in_plan_order = [
            node_id for node_id in plan_node_ids if node_id in selected
        ]
        forced_in_plan_order = [
            node_id for node_id in plan_node_ids if node_id in forced
        ]
        return self._start_background(
            project_id,
            workflow_commit_id=source_projection.workflow_commit_id,
            client_request_id=client_request_id,
            _derived_from=DerivedRunReference(
                source_run_id=source_run_id,
                policy=policy,
                selected_node_ids=tuple(selected_in_plan_order),
                forced_node_ids=tuple(forced_in_plan_order),
            ),
            _cache_bypass_nodes=forced,
            _retained_compiled=compiled,
        )
