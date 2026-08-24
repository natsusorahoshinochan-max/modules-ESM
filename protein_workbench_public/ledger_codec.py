"""Public REST/WebSocket projection of typed Run Ledger domain values."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from core.execution.ledger import (
    ContextSelectorEvidence,
    CancellationDecision,
    EngineInvocationStarted,
    EngineInvocationTerminal,
    Fact,
    NodeAttemptStarted,
    NodeAttemptTerminal,
    NodeDisposition,
    ObservationSelectorEvidence,
    OperationAttemptStarted,
    OperationAttemptTerminal,
    PublishedArtifact,
    PublishedOutput,
    ReadinessAttested,
    RunAdmitted,
    RunCursor,
    RunProjection,
    RunStarted,
    RunTerminal,
    SelectionObjectiveEvidence,
    SelectionResult,
    SelectionTerminal,
    StructuredError,
    run_cursor,
)
from datatypes.exact_reference import ExactContractReference
from datatypes.i_json import thaw_i_json
from protein_workbench_public.protocol import project_structured_error


def public_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def decode_run_cursor(value: str | None) -> RunCursor | None:
    """Translate one already-admitted public cursor parameter to domain form."""
    return None if value is None else RunCursor(value)


def _reference(value: ExactContractReference) -> dict[str, str]:
    return {
        "contract_kind": value.contract_kind,
        "contract_id": value.contract_id,
        "contract_version": value.contract_version,
        "contract_digest": value.contract_digest,
    }


def _error(value: StructuredError) -> dict[str, Any]:
    _, projected = project_structured_error(
        value.code,
        value.message,
        thaw_i_json(value.details),
        value.correlation_id,
    )
    return projected


def _artifact(value: PublishedArtifact) -> dict[str, Any]:
    result = {
        "artifact_reference": value.artifact_reference,
        "artifact_kind": value.artifact_kind,
        "node_id": value.node_id,
        "output_port": value.output_port,
        "media_type": value.media_type,
        "filename": value.filename,
        "size": value.size,
        "content_digest": value.content_digest,
    }
    if value.candidate_id is not None:
        result["candidate_id"] = value.candidate_id
    return result


def _output(value: PublishedOutput) -> dict[str, Any]:
    return {
        "node_id": value.node_id,
        "output_port": value.output_port,
        "port_type": _reference(value.port_type),
        "content_digest": value.content_digest,
        "result_identity": value.result_identity,
        "materialization": thaw_i_json(value.materialization),
        "producer_provenance": thaw_i_json(value.producer_provenance),
        "value_count": value.value_count,
        "value_manifest_reference": value.value_manifest_reference,
    }


def _selection_input(value: Any) -> dict[str, str]:
    return {"node_id": value.node_id, "output_port": value.output_port}


def _context(value: ContextSelectorEvidence) -> dict[str, Any]:
    result: dict[str, Any] = {"kind": value.kind}
    for field_name in (
        "calibration_metric",
        "calibration_value",
        "calibration_unit",
        "population_id",
        "subject_role",
        "reference_role",
        "pairing_mode",
        "normalization",
    ):
        observed = getattr(value, field_name)
        if observed is not None:
            result[field_name] = observed
    return result


def _selection_objective(
    value: SelectionObjectiveEvidence,
) -> dict[str, Any]:
    return {
        "objective_id": value.objective_id,
        "candidate_input": _selection_input(value.candidate_input),
        "score_collection_input": _selection_input(
            value.score_collection_input
        ),
        "source_partition": value.source_partition,
        "metric": _reference(value.metric),
        "method": _reference(value.method),
        "context_selector": _context(value.context_selector),
        "utility_transform": _reference(value.utility_transform),
        "utility_parameters": thaw_i_json(value.utility_parameters),
        "declared_weight": value.declared_weight,
        "effective_weight": value.effective_weight,
        "match_cardinality": value.match_cardinality,
        "missing_policy": value.missing_policy,
    }


def _observation_selector(
    value: ObservationSelectorEvidence,
) -> dict[str, Any]:
    return {
        "selector_id": value.selector_id,
        "candidate_input": _selection_input(value.candidate_input),
        "score_collection_input": _selection_input(
            value.score_collection_input
        ),
        "source_partition": value.source_partition,
        "metric": _reference(value.metric),
        "method": _reference(value.method),
        "context_selector": _context(value.context_selector),
        "match_cardinality": value.match_cardinality,
        "missing_policy": value.missing_policy,
    }


def _selection(value: SelectionResult) -> dict[str, Any]:
    result = {
        "status": "succeeded",
        "selection_node_id": value.selection_node_id,
        "selection_method": _reference(value.selection_method),
        "candidate_input": _selection_input(value.candidate_input),
        "selected_collection_id": value.selected_collection_id,
        "selected_candidate_ids": list(value.selected_candidate_ids),
    }
    if value.objectives:
        result["objectives"] = [
            _selection_objective(objective) for objective in value.objectives
        ]
    if value.observation_selectors:
        result["observation_selectors"] = [
            _observation_selector(selector)
            for selector in value.observation_selectors
        ]
    return result


def _provenance(value: EngineInvocationStarted) -> dict[str, Any]:
    provenance = value.provenance
    if provenance is None:
        raise TypeError("Engine Invocation has no provenance to project")
    result: dict[str, Any] = {}
    if provenance.effective_randomness is not None:
        randomness = provenance.effective_randomness
        result["effective_randomness"] = {
            "control": randomness.control,
            **(
                {"effective_seed": randomness.effective_seed}
                if randomness.effective_seed is not None
                else {}
            ),
        }
    if provenance.project_input_filename is not None:
        result["project_input_filename"] = provenance.project_input_filename
    if provenance.provider_residue_projection is not None:
        projection = provenance.provider_residue_projection
        result["provider_residue_projection"] = {
            "position_semantics": projection.position_semantics,
            "workbench_chain_order": list(projection.workbench_chain_order),
            "provider_structure_chain_order": list(
                projection.provider_structure_chain_order
            ),
            "provider_chain_order": list(projection.provider_chain_order),
            "entries": [
                {
                    "residue_id": entry.residue_id,
                    "segment_index": entry.segment_index,
                    "provider_chain_id": entry.provider_chain_id,
                    "provider_position": entry.provider_position,
                }
                for entry in projection.entries
            ],
        }
    return result


def encode_cancellation_receipt(
    *,
    project_id: str,
    run_id: str,
    decision: CancellationDecision,
) -> dict[str, Any]:
    return {
        "project_id": project_id,
        "run_id": run_id,
        "outcome": decision.outcome,
        "decision_sequence": decision.decision_sequence,
        "cursor": decision.cursor.value,
    }


def encode_run_projection(projection: RunProjection) -> dict[str, Any]:
    result: dict[str, Any] = {
        "project_id": projection.project_id,
        "run_id": projection.run_id,
        "workflow_commit_id": projection.workflow_commit_id,
        "workflow_commit_revision": projection.workflow_commit_revision,
        "workflow_digest": projection.workflow_digest,
        "status": projection.status,
        "ledger_cursor": projection.ledger_cursor.value,
        "node_dispositions": [
            {
                "node_id": disposition.node_id,
                "outcome": disposition.outcome,
                "blocked_by": list(disposition.blocked_by),
                **(
                    {"resolution": disposition.resolution}
                    if disposition.resolution is not None
                    else {}
                ),
                "terminal_sequence": disposition.terminal_sequence,
            }
            for disposition in projection.node_dispositions
        ],
        "outputs": [_output(output) for output in projection.outputs],
        "artifact_index": [
            _artifact(artifact) for artifact in projection.artifacts
        ],
    }
    if projection.selection_results is not None:
        result["selection_results"] = [
            _selection(selection) for selection in projection.selection_results
        ]
    if projection.selection_error is not None:
        result["selection_error"] = _error(projection.selection_error)
    if projection.terminal_sequence is not None:
        result["terminal_sequence"] = projection.terminal_sequence
    if projection.derived_from_run_id is not None:
        result["derived_from_run_id"] = projection.derived_from_run_id
    return result


def _event_payload(fact: Fact) -> dict[str, Any]:
    payload = fact.payload
    if isinstance(payload, ReadinessAttested):
        return {
            "type": "readiness_attested",
            "binding": _reference(payload.binding),
            "attestation_digest": payload.attestation_digest,
            "observed_at": payload.observed_at,
            "conclusion": payload.conclusion,
            "proof_source": payload.proof_source,
        }
    if isinstance(payload, RunAdmitted):
        return {
            "type": "run_admitted",
            "workflow_commit_id": payload.workflow_commit_id,
            "workflow_commit_revision": payload.workflow_commit_revision,
        }
    if isinstance(payload, RunStarted):
        return {"type": "run_started", "started_at": payload.started_at}
    if isinstance(payload, NodeAttemptStarted):
        return {
            "type": "node_attempt_started",
            "node_id": payload.node_id,
            "node_attempt_id": payload.node_attempt_id,
        }
    if isinstance(payload, OperationAttemptStarted):
        return {
            "type": "operation_attempt_started",
            "operation_attempt_id": payload.operation_attempt_id,
            "node_attempt_id": payload.node_attempt_id,
        }
    if isinstance(payload, EngineInvocationStarted):
        result = {
            "type": "engine_invocation_started",
            "invocation_id": payload.invocation_id,
            "operation_attempt_id": payload.operation_attempt_id,
            "engine_role": payload.engine_role,
            "engine_identity": payload.engine_identity,
        }
        if payload.parent_invocation_id is not None:
            result["parent_invocation_id"] = payload.parent_invocation_id
        if payload.provenance is not None:
            result["invocation_provenance"] = _provenance(payload)
        return result
    if isinstance(payload, EngineInvocationTerminal):
        result = {
            "type": "engine_invocation_terminal",
            "invocation_id": payload.invocation_id,
            "status": payload.status,
        }
        if payload.error is not None:
            result["error"] = _error(payload.error)
        return result
    if isinstance(payload, OperationAttemptTerminal):
        result = {
            "type": "operation_attempt_terminal",
            "operation_attempt_id": payload.operation_attempt_id,
            "status": payload.status,
        }
        if payload.error is not None:
            result["error"] = _error(payload.error)
        return result
    if isinstance(payload, NodeAttemptTerminal):
        result = {
            "type": "node_attempt_terminal",
            "node_attempt_id": payload.node_attempt_id,
            "status": payload.status,
            "resolution": payload.resolution,
        }
        if payload.error is not None:
            result["error"] = _error(payload.error)
        if payload.failure_origin is not None:
            result["failure_origin"] = payload.failure_origin
        return result
    if isinstance(payload, NodeDisposition):
        disposition = {
            "node_id": payload.node_id,
            "outcome": payload.outcome,
            "blocked_by": list(payload.blocked_by),
            **(
                {"resolution": payload.resolution}
                if payload.resolution is not None
                else {}
            ),
            "terminal_sequence": fact.sequence,
        }
        return {"type": "node_disposition", "disposition": disposition}
    if isinstance(payload, SelectionTerminal):
        result = {"type": "selection_terminal", "status": payload.status}
        if payload.result is not None:
            result["result"] = _selection(payload.result)
        if payload.error is not None:
            result["error"] = _error(payload.error)
        return result
    if isinstance(payload, RunTerminal):
        return {"type": "run_terminal", "status": payload.status}
    raise TypeError("Fact is not a public Run event")


def encode_event(
    *,
    project_id: str,
    run_id: str,
    fact: Fact,
) -> dict[str, Any]:
    return {
        "schema_namespace": "protein-workbench-public/v2",
        "project_id": project_id,
        "run_id": run_id,
        "sequence": fact.sequence,
        "cursor": run_cursor(
            fact.sequence,
            project_id=project_id,
            run_id=run_id,
            fact=fact,
        ).value,
        "emitted_at": fact.recorded_at,
        "event": _event_payload(fact),
    }
