"""One authority for range previews and Run admission with pinned reuse."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from core.execution._node_attempt_identity import _node_output_plan, _result_identity, _resolve_effective_randomness
from core.execution._node_preparation import prepare_node
from core.execution._run_runtime_registry import _RunRegistry
from core.execution.ledger import V2RunError
from core.execution.results.store import ResultIntegrityError, ResultStore, StoredNodeResult
from core.execution.scope import RunExecutionScope, RunScopeRequest
from core.operation import AdmittedPort
from core.project.manager import ProjectManager
from core.project.objects import StoredObject
from core.workflow.authoring import VerifiedWorkflowCommit, WorkflowAuthoringService
from datatypes.i_json import thaw_i_json


@dataclass(frozen=True, slots=True)
class _ScopeAdmission:
    compiled: VerifiedWorkflowCommit
    scope: RunExecutionScope
    reused: dict[str, StoredNodeResult]
    blockers: tuple[dict[str, Any], ...]
    nodes: tuple[dict[str, Any], ...]
    continuations: dict[str, StoredNodeResult] = field(default_factory=dict)

    def projection(self, workflow_commit_id: str) -> dict[str, Any]:
        return {
            "workflow_commit_id": workflow_commit_id,
            "scope": self.scope.projection(),
            "blockers": list(self.blockers),
            "nodes": list(self.nodes),
        }

    def require_ready(self) -> None:
        if self.blockers:
            raise V2RunError(
                "compile_rejected",
                "Run scope requires reusable upstream results",
                details={"issues": list(self.blockers)},
            )


class _RunScopeAdmission:
    def __init__(self, projects: ProjectManager, authoring: WorkflowAuthoringService,
                 registry: _RunRegistry, results: ResultStore) -> None:
        self._projects = projects
        self._authoring = authoring
        self._registry = registry
        self._results = results

    def resolve(self, project_id: str, workflow_commit_id: str,
                request: RunScopeRequest, materialization_run_id: str,
                *, include_summaries: bool = False, continuation_node_ids: tuple[str, ...] = ()) -> _ScopeAdmission:
        compiled = self._authoring.require_verified_commit(
            project_id, workflow_commit_id=workflow_commit_id
        )
        plan = compiled.execution_plan
        ordered = tuple(node.node_id for node in plan.nodes)
        selected = set(request.node_ids)
        if (
            request.mode not in {"full", "to_node", "from_node"}
            or len(selected) != len(request.node_ids)
            or not selected <= set(ordered)
            or (request.mode == "full" and (selected or request.source_run_id is not None))
            or (request.mode != "full" and not selected)
            or (request.mode == "from_node") != (request.source_run_id is not None)
        ):
            raise V2RunError(
                "malformed_request", "Run scope selection is invalid",
                details={"field_path": ["scope"]},
            )

        def ancestors(node_ids: set[str]) -> set[str]:
            result = set(node_ids)
            for node in reversed(plan.nodes):
                if node.node_id in result:
                    result.update(node._runtime.dependencies)
            return result

        execution = set(ordered) if request.mode == "full" else set(selected)
        if request.mode == "to_node":
            execution = ancestors(execution)
        elif request.mode == "from_node":
            for node in plan.nodes:
                if execution.intersection(node._runtime.dependencies):
                    execution.add(node.node_id)
        reused_ids = ancestors(execution) - execution
        active = execution | reused_ids
        scope = RunExecutionScope(
            mode=request.mode,
            selected_node_ids=tuple(n for n in ordered if n in selected),
            execution_node_ids=tuple(n for n in ordered if n in execution),
            reused_node_ids=tuple(n for n in ordered if n in reused_ids),
            out_of_scope_node_ids=tuple(n for n in ordered if n not in execution),
            source_run_id=request.source_run_id,
        )
        publications = {}
        all_publications = {}
        if request.source_run_id is not None:
            source = self._registry.require_record(project_id, request.source_run_id)
            source.require_lifecycle_evidence()
            source_projection = source.ledger.projection()
            if source_projection.terminal_sequence is None:
                raise V2RunError(
                    "malformed_request", "Continue requires a terminal source Run",
                    details={"field_path": ["scope", "source_run_id"]},
                )
            all_publications = {item.node_id: item for item in source_projection.publications}
            succeeded = {
                item.node_id for item in source_projection.node_dispositions
                if item.outcome == "succeeded"
            }
            publications = {
                item.node_id: item for item in source_projection.publications
                if item.node_id in succeeded
            }
        values: dict[tuple[str, str], AdmittedPort] = {}
        reused: dict[str, StoredNodeResult] = {}
        blockers: list[dict[str, Any]] = []
        summaries: list[dict[str, Any]] = []
        for node in plan.nodes:
            if node.node_id not in active:
                continue
            if include_summaries:
                summary = {
                    "node_id": node.node_id,
                    "binding": {"contract_kind": "binding", "contract_id": node.binding.contract_id},
                    "method": {"contract_kind": "method", "contract_id": node.method.contract_id},
                    "node_parameters": thaw_i_json(dict(node.node_parameters)),
                    "binding_parameters": thaw_i_json(dict(node.binding_parameters)),
                    "action": "reuse" if node.node_id in reused_ids else "execute",
                    "randomness_status": "awaiting_inputs",
                }
                if node._runtime.effective_randomness_resolver is None:
                    randomness = _resolve_effective_randomness(node, {})
                    summary["randomness_status"] = "resolved"
                    summary["effective_randomness"] = thaw_i_json(randomness.effective_randomness)
                summaries.append(summary)
                if node.node_id in reused_ids and node.node_id not in publications:
                    blockers.append({
                        "code": "upstream_result_missing", "severity": "error",
                        "node_id": node.node_id,
                        "message": f"No published upstream result for {node.node_id}",
                        "field_path": ["scope", "source_run_id"],
                    })
                continue
            can_resolve = all(dependency in reused for dependency in node._runtime.dependencies)
            prepared = (
                prepare_node(self._projects, project_id, node, values)
                if can_resolve and node.node_id in reused_ids else None
            )
            if node.node_id not in reused_ids:
                continue
            publication = publications.get(node.node_id)
            reason = None
            if publication is None:
                reason = "upstream_result_missing"
            elif prepared is None:
                reason = "upstream_dependency_unavailable"
            else:
                identity = prepared.result_identity or _result_identity(
                    node, prepared.inputs,
                    resolved_resource_inputs=prepared.resource_identities,
                    effective_randomness_snapshot=prepared.effective_randomness,
                )
                if identity != publication.result_identity:
                    reason = "upstream_result_identity_mismatch"
                else:
                    try:
                        restored = self._results.restore(
                            project_id=project_id,
                            materialization_run_id=materialization_run_id,
                            producer_run_id=(
                                publication.outputs[0].producer_run_id
                                if publication.outputs else
                                publication.artifacts[0].producer_run_id
                                if publication.artifacts and publication.artifacts[0].producer_run_id
                                else request.source_run_id
                            ),
                            node_plan=_node_output_plan(node, plan._runtime.candidate_data_port_types),
                            result_identity=identity,
                            node_result_manifest=StoredObject(
                                publication.node_result_manifest.content_digest,
                                publication.node_result_manifest.size,
                            ),
                        )
                    except (ResultIntegrityError, OSError):
                        reason = "upstream_result_unavailable"
                    else:
                        reused[node.node_id] = restored
                        values.update({(node.node_id, port): value
                                       for port, value in restored.admitted_output.ports.items()})
            if reason is not None:
                blockers.append({
                    "code": reason, "severity": "error", "node_id": node.node_id,
                    "message": f"Cannot reuse upstream Node {node.node_id}: {reason}",
                    "field_path": ["scope", "source_run_id"],
                })
        for node in (() if include_summaries else plan.nodes):
            if node.node_id not in execution:
                continue
            for port_name, sources in node._runtime.required_input_sources.items():
                if (all(source.node_id in reused_ids for source in sources)
                    and not any(values.get((source.node_id, source.output_port)) is not None
                                and values[(source.node_id, source.output_port)].values
                                for source in sources)):
                    blockers.append({
                        "code": "required_upstream_value_missing", "severity": "error",
                        "node_id": node.node_id,
                        "message": f"No reusable value for required input {node.node_id}.{port_name}",
                        "field_path": ["scope", "source_run_id"],
                    })
        continuations = {}
        for node in (() if blockers else plan.nodes):
            if node.node_id not in continuation_node_ids:
                continue
            publication = all_publications.get(node.node_id)
            if publication is None:
                raise V2RunError("malformed_request", "Node has no resumable batch publication",
                                 details={"field_path": ["node_ids"]})
            prepared = prepare_node(self._projects, project_id, node, values)
            identity = _result_identity(node, prepared.inputs,
                resolved_resource_inputs=prepared.resource_identities,
                effective_randomness_snapshot=prepared.effective_randomness)
            if identity != publication.result_identity:
                raise V2RunError("malformed_request", "Batch inputs or parameters changed",
                                 details={"field_path": ["source_run_id"]})
            restored = self._results.restore(
                project_id=project_id, materialization_run_id=materialization_run_id,
                producer_run_id=request.source_run_id,
                node_plan=_node_output_plan(node, plan._runtime.candidate_data_port_types),
                result_identity=identity,
                node_result_manifest=StoredObject(publication.node_result_manifest.content_digest,
                                                  publication.node_result_manifest.size))
            if restored.continuation_state is None:
                raise V2RunError("malformed_request", "Node has no resumable batch state",
                                 details={"field_path": ["node_ids"]})
            continuations[node.node_id] = restored
        return _ScopeAdmission(compiled, scope, reused, tuple(blockers), tuple(summaries), continuations)
