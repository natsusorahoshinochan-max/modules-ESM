"""The sole raw JSON codec for durable Ledger facts and cursors."""

from __future__ import annotations

import base64
import binascii
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
import json
import re
from typing import Any, cast

from core.catalog.port_contract import canonical_json_bytes, canonical_sha256
from core.execution.ledger.facts import (
    AvailabilityBound,
    CancellationRequested,
    ContextSelectorEvidence,
    DerivedRunReference,
    EngineInvocationStarted,
    EngineInvocationTerminal,
    Fact,
    FactPayload,
    ImmutableObjectReference,
    NodeAttemptStarted,
    NodeAttemptTerminal,
    NodeDisposition,
    ObservationSelectorEvidence,
    OperationAttemptStarted,
    OperationAttemptTerminal,
    OutputsPublished,
    PublishedArtifact,
    PublishedOutput,
    ReadinessAttested,
    RunAdmitted,
    RunScopeBound,
    RunStarted,
    RunTerminal,
    SelectionObjectiveEvidence,
    SelectionResult,
    SelectionTerminal,
    StructuredError,
    validate_fact_payload,
)
from core.execution.ledger.projections import RunCursor
from core.catalog.port_contract import is_valid_artifact_media_type
from core.execution.ledger.transitions import (
    ArtifactOutputEvidence,
    PlanNodeEvidence,
    PlanRequiredInputEvidence,
    PlanValueSourceEvidence,
)
from core.project.storage import validate_identifier
from core.operation import (
    EngineInvocationProvenance,
    InvocationRandomness,
    ProviderResidueProjection,
    ProviderResidueProjectionEntry,
)
from core.scoring.selection import SelectionInput
from datatypes.exact_reference import (
    ExactContractReference,
    validate_canonical_identifier,
)
from datatypes.i_json import freeze_i_json, thaw_i_json


TRANSACTION_NAMESPACE = "protein-workbench-run-ledger-transaction/v5"
TRANSACTION_SCHEMA_VERSION = "5.0.0"
CURSOR_NAMESPACE = "protein-workbench-run-cursor/v2"
RUN_SCOPE_NAMESPACE = "protein-workbench-run-scope/v2"
CONTRACT_LOCK_NAMESPACE = "protein-workbench-contract-lock/v2"
READINESS_ATTESTATION_NAMESPACE = (
    "protein-workbench-readiness-attestation/v2"
)


@dataclass(frozen=True, slots=True)
class LedgerTransaction:
    project_id: str
    run_id: str
    transaction_sequence: int
    first_fact_sequence: int
    last_fact_sequence: int
    committed_at: str
    facts: tuple[Fact, ...]


@dataclass(frozen=True, slots=True)
class DecodedCursor:
    scope_digest: str
    sequence: int
    fact_digest: str


def is_timestamp(value: object) -> bool:
    if not isinstance(value, str) or not 20 <= len(value) <= 64:
        return False
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return False
    return parsed.tzinfo is not None


def _mapping(value: object, fields: set[str]) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != fields:
        raise ValueError("Run Ledger typed payload has invalid fields")
    return value


def _reference_to_canonical(value: ExactContractReference) -> dict[str, str]:
    return {
        "contract_kind": value.contract_kind,
        "contract_id": value.contract_id,
        "contract_version": value.contract_version,
        "contract_digest": value.contract_digest,
    }


def _reference_from_canonical(value: object) -> ExactContractReference:
    raw = _mapping(
        value,
        {"contract_kind", "contract_id", "contract_version", "contract_digest"},
    )
    if (
        not all(isinstance(raw[field], str) for field in raw)
        or raw["contract_kind"] not in {
            "binding",
            "method",
            "metric",
            "node_type",
            "port_type",
            "utility_transform",
        }
        or re.fullmatch(
            r"[0-9]+\.[0-9]+\.[0-9]+(?:-[0-9A-Za-z.-]+)?",
            raw["contract_version"],
        )
        is None
        or re.fullmatch(r"sha256:[0-9a-f]{64}", raw["contract_digest"])
        is None
    ):
        raise ValueError("Run Ledger contract reference is invalid")
    validate_canonical_identifier(raw["contract_id"], "contract_id")
    return ExactContractReference(
        contract_kind=raw["contract_kind"],
        contract_id=raw["contract_id"],
        contract_version=raw["contract_version"],
        contract_digest=raw["contract_digest"],
    )


def contract_lock_digest(
    references: tuple[ExactContractReference, ...],
) -> str:
    return canonical_sha256(
        {
            "schema_namespace": CONTRACT_LOCK_NAMESPACE,
            "entries": [
                _reference_to_canonical(reference)
                for reference in references
            ],
        }
    )


def readiness_attestation_digest(
    *,
    binding: ExactContractReference,
    readiness_contract_digest: str,
    observed_at: str,
    conclusion: str,
    proof_source: str,
) -> str:
    return canonical_sha256(
        {
            "schema_namespace": READINESS_ATTESTATION_NAMESPACE,
            "binding": _reference_to_canonical(binding),
            "readiness_contract_digest": readiness_contract_digest,
            "observed_at": observed_at,
            "conclusion": conclusion,
            "proof_source": proof_source,
        }
    )


def _plan_source_to_canonical(
    value: PlanValueSourceEvidence,
) -> dict[str, str]:
    return {"node_id": value.node_id, "output_port": value.output_port}


def _plan_source_from_canonical(value: object) -> PlanValueSourceEvidence:
    raw = _mapping(value, {"node_id", "output_port"})
    return PlanValueSourceEvidence(
        node_id=validate_identifier(raw["node_id"], "node_id"),
        output_port=validate_identifier(raw["output_port"], "output_port"),
    )


def _required_input_to_canonical(
    value: PlanRequiredInputEvidence,
) -> dict[str, Any]:
    return {
        "input_port": value.input_port,
        "sources": [_plan_source_to_canonical(item) for item in value.sources],
    }


def _required_input_from_canonical(
    value: object,
) -> PlanRequiredInputEvidence:
    raw = _mapping(value, {"input_port", "sources"})
    if not isinstance(raw["sources"], list) or not raw["sources"]:
        raise ValueError("Run plan required input is invalid")
    sources = tuple(
        _plan_source_from_canonical(item) for item in raw["sources"]
    )
    if sources != tuple(
        sorted(set(sources), key=lambda item: (item.node_id, item.output_port))
    ):
        raise ValueError("Run plan required input sources are not canonical")
    return PlanRequiredInputEvidence(
        input_port=validate_identifier(raw["input_port"], "input_port"),
        sources=sources,
    )


def _artifact_output_to_canonical(
    value: ArtifactOutputEvidence,
) -> dict[str, Any]:
    return {
        "output_port": value.output_port,
        "artifact_kind": value.artifact_kind,
        "artifact_media_type": value.artifact_media_type,
        "port_type": _reference_to_canonical(value.port_type),
        "accepted_media_types": list(value.accepted_media_types),
    }


def _artifact_output_from_canonical(value: object) -> ArtifactOutputEvidence:
    raw = _mapping(
        value,
        {
            "output_port",
            "artifact_kind",
            "artifact_media_type",
            "port_type",
            "accepted_media_types",
        },
    )
    reference = _reference_from_canonical(raw["port_type"])
    media_types = raw["accepted_media_types"]
    artifact_media_type = raw["artifact_media_type"]
    if (
        reference.contract_kind != "port_type"
        or raw["artifact_kind"] not in {"candidate", "standalone"}
        or not isinstance(media_types, list)
        or not media_types
        or any(
            not isinstance(media_type, str)
            or not is_valid_artifact_media_type(media_type)
            for media_type in media_types
        )
        or media_types != sorted(set(media_types))
        or (
            artifact_media_type is not None
            and (
                not isinstance(artifact_media_type, str)
                or artifact_media_type not in media_types
            )
        )
    ):
        raise ValueError("Run plan Artifact output is invalid")
    return ArtifactOutputEvidence(
        output_port=validate_identifier(raw["output_port"], "output_port"),
        artifact_kind=cast(Any, raw["artifact_kind"]),
        artifact_media_type=cast(str | None, artifact_media_type),
        port_type=reference,
        accepted_media_types=tuple(media_types),
    )


def _plan_node_to_canonical(value: PlanNodeEvidence) -> dict[str, Any]:
    result: dict[str, Any] = {
        "node_id": value.node_id,
        "dependencies": list(value.dependencies),
        "required_input_sources": [
            _required_input_to_canonical(item)
            for item in value.required_input_sources
        ],
        "result_identity_plan_facts_digest": (
            value.result_identity_plan_facts_digest
        ),
        "binding": _reference_to_canonical(value.binding),
        "execution_route": value.execution_route,
    }
    if value.node_type is not None:
        result["node_type"] = _reference_to_canonical(value.node_type)
    if value.artifact_outputs:
        result["artifact_outputs"] = [
            _artifact_output_to_canonical(item)
            for item in value.artifact_outputs
        ]
    if value.selection_consumer:
        result["selection_consumer"] = True
    return result


def _plan_node_from_canonical(value: object) -> PlanNodeEvidence:
    if not isinstance(value, Mapping):
        raise ValueError("Run plan node is invalid")
    required = {
        "node_id",
        "dependencies",
        "required_input_sources",
        "result_identity_plan_facts_digest",
        "binding",
        "execution_route",
    }
    if not required <= set(value) or set(value) - required - {
        "node_type",
        "artifact_outputs",
        "selection_consumer",
    }:
        raise ValueError("Run plan node is invalid")
    dependencies = value["dependencies"]
    required_inputs = value["required_input_sources"]
    artifact_outputs = value.get("artifact_outputs", [])
    if (
        not isinstance(dependencies, list)
        or not all(isinstance(item, str) for item in dependencies)
        or dependencies != sorted(set(dependencies))
        or not isinstance(required_inputs, list)
        or not isinstance(artifact_outputs, list)
        or value["execution_route"] not in {"direct", "adapter"}
        or type(value.get("selection_consumer", False)) is not bool
        or not isinstance(value["result_identity_plan_facts_digest"], str)
        or re.fullmatch(
            r"sha256:[0-9a-f]{64}",
            value["result_identity_plan_facts_digest"],
        )
        is None
    ):
        raise ValueError("Run plan node is invalid")
    binding = _reference_from_canonical(value["binding"])
    node_type = (
        _reference_from_canonical(value["node_type"])
        if "node_type" in value
        else None
    )
    parsed_required = tuple(
        _required_input_from_canonical(item) for item in required_inputs
    )
    parsed_artifacts = tuple(
        _artifact_output_from_canonical(item) for item in artifact_outputs
    )
    if (
        binding.contract_kind != "binding"
        or (node_type is not None and node_type.contract_kind != "node_type")
        or parsed_required
        != tuple(sorted(set(parsed_required), key=lambda item: item.input_port))
        or any(
            source.node_id not in dependencies
            for required_input in parsed_required
            for source in required_input.sources
        )
        or len({item.output_port for item in parsed_artifacts})
        != len(parsed_artifacts)
    ):
        raise ValueError("Run plan node is invalid")
    return PlanNodeEvidence(
        node_id=validate_identifier(value["node_id"], "node_id"),
        dependencies=tuple(dependencies),
        required_input_sources=parsed_required,
        result_identity_plan_facts_digest=value[
            "result_identity_plan_facts_digest"
        ],
        binding=binding,
        execution_route=cast(Any, value["execution_route"]),
        node_type=node_type,
        artifact_outputs=parsed_artifacts,
        selection_consumer=value.get("selection_consumer", False),
    )


def _plan_evidence_from_canonical(
    value: object,
) -> tuple[PlanNodeEvidence, ...]:
    if not isinstance(value, list):
        raise ValueError("Run plan evidence is invalid")
    nodes = tuple(_plan_node_from_canonical(item) for item in value)
    node_ids = tuple(node.node_id for node in nodes)
    if len(set(node_ids)) != len(node_ids) or any(
        dependency not in node_ids
        for node in nodes
        for dependency in node.dependencies
    ):
        raise ValueError("Run plan evidence is invalid")
    return nodes


def _error_to_canonical(value: StructuredError) -> dict[str, Any]:
    return {
        "code": value.code,
        "message": value.message,
        "retryable": value.retryable,
        "correlation_id": value.correlation_id,
        "details": thaw_i_json(value.details),
    }


def _error_from_canonical(value: object) -> StructuredError:
    raw = _mapping(
        value,
        {"code", "message", "retryable", "correlation_id", "details"},
    )
    return StructuredError(
        code=cast(str, raw["code"]),
        message=cast(str, raw["message"]),
        retryable=cast(bool, raw["retryable"]),
        correlation_id=cast(str, raw["correlation_id"]),
        details=freeze_i_json(raw["details"]),
    )


def _object_to_canonical(value: ImmutableObjectReference) -> dict[str, Any]:
    return {"content_digest": value.content_digest, "size": value.size}


def _object_from_canonical(value: object) -> ImmutableObjectReference:
    raw = _mapping(value, {"content_digest", "size"})
    return ImmutableObjectReference(cast(str, raw["content_digest"]), cast(int, raw["size"]))


def _output_to_canonical(value: PublishedOutput) -> dict[str, Any]:
    return {
        "node_id": value.node_id,
        "output_port": value.output_port,
        "port_type": _reference_to_canonical(value.port_type),
        "content_digest": value.content_digest,
        "result_identity": value.result_identity,
        "materialization": thaw_i_json(value.materialization),
        "producer_provenance": thaw_i_json(value.producer_provenance),
        "value_count": value.value_count,
        "value_manifest_reference": value.value_manifest_reference,
    }


def _output_from_canonical(value: object) -> PublishedOutput:
    raw = _mapping(
        value,
        {
            "node_id", "output_port", "port_type", "content_digest",
            "result_identity", "materialization", "producer_provenance",
            "value_count", "value_manifest_reference",
        },
    )
    return PublishedOutput(
        node_id=cast(str, raw["node_id"]),
        output_port=cast(str, raw["output_port"]),
        port_type=_reference_from_canonical(raw["port_type"]),
        content_digest=cast(str, raw["content_digest"]),
        result_identity=cast(str, raw["result_identity"]),
        materialization=freeze_i_json(raw["materialization"]),
        producer_provenance=freeze_i_json(raw["producer_provenance"]),
        value_count=cast(int, raw["value_count"]),
        value_manifest_reference=cast(str, raw["value_manifest_reference"]),
    )


def _artifact_to_canonical(value: PublishedArtifact) -> dict[str, Any]:
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


def _artifact_from_canonical(value: object) -> PublishedArtifact:
    if not isinstance(value, Mapping):
        raise ValueError("Run Ledger Artifact is invalid")
    required = {
        "artifact_reference", "artifact_kind", "node_id", "output_port",
        "media_type", "filename", "size", "content_digest",
    }
    if frozenset(value) not in {
        frozenset(required),
        frozenset(required | {"candidate_id"}),
    }:
        raise ValueError("Run Ledger Artifact is invalid")
    return PublishedArtifact(
        artifact_reference=cast(str, value["artifact_reference"]),
        artifact_kind=cast(Any, value["artifact_kind"]),
        node_id=cast(str, value["node_id"]),
        output_port=cast(str, value["output_port"]),
        media_type=cast(str, value["media_type"]),
        filename=cast(str, value["filename"]),
        size=cast(int, value["size"]),
        content_digest=cast(str, value["content_digest"]),
        candidate_id=cast(str | None, value.get("candidate_id")),
    )


def _selection_input_to_canonical(value: SelectionInput) -> dict[str, str]:
    return {"node_id": value.node_id, "output_port": value.output_port}


def _selection_input_from_canonical(value: object) -> SelectionInput:
    raw = _mapping(value, {"node_id", "output_port"})
    return SelectionInput(cast(str, raw["node_id"]), cast(str, raw["output_port"]))


def _context_to_canonical(value: ContextSelectorEvidence) -> dict[str, Any]:
    result = {"kind": value.kind}
    for name in (
        "calibration_metric", "calibration_value", "calibration_unit",
        "population_id", "subject_role", "reference_role", "pairing_mode",
        "normalization",
    ):
        observed = getattr(value, name)
        if observed is not None:
            result[name] = observed
    return result


def _context_from_canonical(value: object) -> ContextSelectorEvidence:
    if not isinstance(value, Mapping) or "kind" not in value:
        raise ValueError("Selection Context evidence is invalid")
    fields_by_kind = {
        "intrinsic": {"kind"},
        "calibration": {
            "kind",
            "calibration_metric",
            "calibration_value",
            "calibration_unit",
            "population_id",
        },
        "pairwise": {
            "kind",
            "subject_role",
            "reference_role",
            "pairing_mode",
            "normalization",
        },
    }
    kind = value["kind"]
    if type(kind) is not str or set(value) != fields_by_kind.get(kind):
        raise ValueError("Selection Context evidence is invalid")
    return ContextSelectorEvidence(**dict(value))


def _objective_to_canonical(value: SelectionObjectiveEvidence) -> dict[str, Any]:
    return {
        "objective_id": value.objective_id,
        "candidate_input": _selection_input_to_canonical(value.candidate_input),
        "score_collection_input": _selection_input_to_canonical(value.score_collection_input),
        "source_partition": value.source_partition,
        "metric": _reference_to_canonical(value.metric),
        "method": _reference_to_canonical(value.method),
        "context_selector": _context_to_canonical(value.context_selector),
        "utility_transform": _reference_to_canonical(value.utility_transform),
        "utility_parameters": thaw_i_json(value.utility_parameters),
        "declared_weight": value.declared_weight,
        "effective_weight": value.effective_weight,
        "match_cardinality": value.match_cardinality,
        "missing_policy": value.missing_policy,
    }


def _objective_from_canonical(value: object) -> SelectionObjectiveEvidence:
    fields = {
        "objective_id", "candidate_input", "score_collection_input",
        "source_partition", "metric", "method", "context_selector",
        "utility_transform", "utility_parameters", "declared_weight",
        "effective_weight", "match_cardinality", "missing_policy",
    }
    raw = _mapping(value, fields)
    return SelectionObjectiveEvidence(
        objective_id=cast(str, raw["objective_id"]),
        candidate_input=_selection_input_from_canonical(raw["candidate_input"]),
        score_collection_input=_selection_input_from_canonical(raw["score_collection_input"]),
        source_partition=cast(str, raw["source_partition"]),
        metric=_reference_from_canonical(raw["metric"]),
        method=_reference_from_canonical(raw["method"]),
        context_selector=_context_from_canonical(raw["context_selector"]),
        utility_transform=_reference_from_canonical(raw["utility_transform"]),
        utility_parameters=freeze_i_json(raw["utility_parameters"]),
        declared_weight=float(raw["declared_weight"]),
        effective_weight=float(raw["effective_weight"]),
        match_cardinality=cast(str, raw["match_cardinality"]),
        missing_policy=cast(str, raw["missing_policy"]),
    )


def _selector_to_canonical(value: ObservationSelectorEvidence) -> dict[str, Any]:
    return {
        "selector_id": value.selector_id,
        "candidate_input": _selection_input_to_canonical(value.candidate_input),
        "score_collection_input": _selection_input_to_canonical(value.score_collection_input),
        "source_partition": value.source_partition,
        "metric": _reference_to_canonical(value.metric),
        "method": _reference_to_canonical(value.method),
        "context_selector": _context_to_canonical(value.context_selector),
        "match_cardinality": value.match_cardinality,
        "missing_policy": value.missing_policy,
    }


def _selector_from_canonical(value: object) -> ObservationSelectorEvidence:
    fields = {
        "selector_id", "candidate_input", "score_collection_input",
        "source_partition", "metric", "method", "context_selector",
        "match_cardinality", "missing_policy",
    }
    raw = _mapping(value, fields)
    return ObservationSelectorEvidence(
        selector_id=cast(str, raw["selector_id"]),
        candidate_input=_selection_input_from_canonical(raw["candidate_input"]),
        score_collection_input=_selection_input_from_canonical(raw["score_collection_input"]),
        source_partition=cast(str, raw["source_partition"]),
        metric=_reference_from_canonical(raw["metric"]),
        method=_reference_from_canonical(raw["method"]),
        context_selector=_context_from_canonical(raw["context_selector"]),
        match_cardinality=cast(str, raw["match_cardinality"]),
        missing_policy=cast(str, raw["missing_policy"]),
    )


def _selection_to_canonical(value: SelectionResult) -> dict[str, Any]:
    result = {
        "status": "succeeded",
        "selection_node_id": value.selection_node_id,
        "selection_method": _reference_to_canonical(value.selection_method),
        "candidate_input": _selection_input_to_canonical(value.candidate_input),
        "selected_collection_id": value.selected_collection_id,
        "selected_candidate_ids": list(value.selected_candidate_ids),
    }
    if value.objectives:
        result["objectives"] = [_objective_to_canonical(item) for item in value.objectives]
    if value.observation_selectors:
        result["observation_selectors"] = [_selector_to_canonical(item) for item in value.observation_selectors]
    return result


def _selection_from_canonical(value: object) -> SelectionResult:
    if not isinstance(value, Mapping) or value.get("status") != "succeeded":
        raise ValueError("Selection result is invalid")
    required = {
        "status",
        "selection_node_id",
        "selection_method",
        "candidate_input",
        "selected_collection_id",
        "selected_candidate_ids",
    }
    if set(value) not in {
        frozenset(required | {"objectives"}),
        frozenset(required | {"observation_selectors"}),
    } or not isinstance(value["selected_candidate_ids"], list):
        raise ValueError("Selection result is invalid")
    nested_key = (
        "objectives" if "objectives" in value else "observation_selectors"
    )
    if not isinstance(value[nested_key], list) or not value[nested_key]:
        raise ValueError("Selection result is invalid")
    return SelectionResult(
        selection_node_id=cast(str, value["selection_node_id"]),
        selection_method=_reference_from_canonical(value["selection_method"]),
        candidate_input=_selection_input_from_canonical(value["candidate_input"]),
        selected_collection_id=cast(str, value["selected_collection_id"]),
        selected_candidate_ids=tuple(cast(list[str], value["selected_candidate_ids"])),
        objectives=tuple(_objective_from_canonical(item) for item in value.get("objectives", [])),
        observation_selectors=tuple(_selector_from_canonical(item) for item in value.get("observation_selectors", [])),
    )


def _provenance_to_canonical(value: EngineInvocationProvenance) -> dict[str, Any]:
    result: dict[str, Any] = {}
    if value.effective_randomness is not None:
        result["effective_randomness"] = {
            "control": value.effective_randomness.control,
            **(
                {"effective_seed": value.effective_randomness.effective_seed}
                if value.effective_randomness.effective_seed is not None else {}
            ),
        }
    if value.project_input_filename is not None:
        result["project_input_filename"] = value.project_input_filename
    if value.provider_residue_projection is not None:
        projection = value.provider_residue_projection
        result["provider_residue_projection"] = {
            "position_semantics": projection.position_semantics,
            "workbench_chain_order": list(projection.workbench_chain_order),
            "provider_structure_chain_order": list(projection.provider_structure_chain_order),
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


def _provenance_from_canonical(value: object) -> EngineInvocationProvenance:
    if not isinstance(value, Mapping):
        raise ValueError("Invocation provenance is invalid")
    randomness = value.get("effective_randomness")
    projection = value.get("provider_residue_projection")
    return EngineInvocationProvenance(
        effective_randomness=(
            InvocationRandomness(
                control=randomness["control"],
                effective_seed=randomness.get("effective_seed"),
            ) if isinstance(randomness, Mapping) else None
        ),
        project_input_filename=cast(str | None, value.get("project_input_filename")),
        provider_residue_projection=(
            ProviderResidueProjection(
                workbench_chain_order=tuple(projection["workbench_chain_order"]),
                provider_structure_chain_order=tuple(projection["provider_structure_chain_order"]),
                provider_chain_order=tuple(projection["provider_chain_order"]),
                entries=tuple(ProviderResidueProjectionEntry(**entry) for entry in projection["entries"]),
                position_semantics=projection["position_semantics"],
            ) if isinstance(projection, Mapping) else None
        ),
    )


_FACT_TYPE_BY_PAYLOAD = {
    RunScopeBound: "run_scope_bound",
    AvailabilityBound: "availability_bound",
    ReadinessAttested: "readiness_attested",
    RunAdmitted: "run_admitted",
    RunStarted: "run_started",
    CancellationRequested: "cancellation_requested",
    NodeAttemptStarted: "node_attempt_started",
    OperationAttemptStarted: "operation_attempt_started",
    EngineInvocationStarted: "engine_invocation_started",
    EngineInvocationTerminal: "engine_invocation_terminal",
    OutputsPublished: "outputs_published",
    OperationAttemptTerminal: "operation_attempt_terminal",
    NodeAttemptTerminal: "node_attempt_terminal",
    NodeDisposition: "node_disposition",
    SelectionTerminal: "selection_terminal",
    RunTerminal: "run_terminal",
}


def fact_type(payload: FactPayload) -> str:
    return _FACT_TYPE_BY_PAYLOAD[type(payload)]


def payload_to_canonical(payload: FactPayload) -> dict[str, Any]:
    if isinstance(payload, RunScopeBound):
        result = {
            "project_id": payload.project_id,
            "run_id": payload.run_id,
            "workflow_commit_id": payload.workflow_commit_id,
            "workflow_commit_revision": payload.workflow_commit_revision,
            "workflow_digest": payload.workflow_digest,
            "contract_lock_digest": payload.contract_lock_digest,
            "execution_plan_digest": payload.execution_plan_digest,
            "catalog_contract_digest": payload.catalog_contract_digest,
            "resolved_contracts": [_reference_to_canonical(item) for item in payload.resolved_contracts],
            "resolved_contract_roots": [_reference_to_canonical(item) for item in payload.resolved_contract_roots],
            "plan_nodes": [
                _plan_node_to_canonical(item) for item in payload.plan_nodes
            ],
            "selection_required": payload.selection_required,
            "selection_terminal_keys": list(payload.selection_terminal_keys),
        }
        if payload.derived_from is not None:
            result["derived_from"] = {
                "source_run_id": payload.derived_from.source_run_id,
                "policy": payload.derived_from.policy,
                "selected_node_ids": list(payload.derived_from.selected_node_ids),
                "forced_node_ids": list(payload.derived_from.forced_node_ids),
            }
        return result
    if isinstance(payload, AvailabilityBound):
        return {"binding": _reference_to_canonical(payload.binding), "catalog_observed_at": payload.catalog_observed_at, "available": payload.available}
    if isinstance(payload, ReadinessAttested):
        return {"binding": _reference_to_canonical(payload.binding), "readiness_contract_digest": payload.readiness_contract_digest, "observed_at": payload.observed_at, "conclusion": payload.conclusion, "proof_source": payload.proof_source, "attestation_digest": payload.attestation_digest}
    if isinstance(payload, RunAdmitted):
        return {"workflow_commit_id": payload.workflow_commit_id, "workflow_commit_revision": payload.workflow_commit_revision}
    if isinstance(payload, RunStarted): return {"started_at": payload.started_at}
    if isinstance(payload, CancellationRequested): return {"requested_at": payload.requested_at}
    if isinstance(payload, NodeAttemptStarted): return {"node_id": payload.node_id, "node_attempt_id": payload.node_attempt_id}
    if isinstance(payload, OperationAttemptStarted): return {"operation_attempt_id": payload.operation_attempt_id, "node_attempt_id": payload.node_attempt_id}
    if isinstance(payload, EngineInvocationStarted):
        result = {"invocation_id": payload.invocation_id, "operation_attempt_id": payload.operation_attempt_id, "engine_role": payload.engine_role, "engine_identity": payload.engine_identity}
        if payload.parent_invocation_id is not None: result["parent_invocation_id"] = payload.parent_invocation_id
        if payload.provenance is not None: result["invocation_provenance"] = _provenance_to_canonical(payload.provenance)
        return result
    if isinstance(payload, EngineInvocationTerminal):
        result = {"invocation_id": payload.invocation_id, "status": payload.status}
        if payload.error is not None: result["error"] = _error_to_canonical(payload.error)
        return result
    if isinstance(payload, OutputsPublished):
        return {"node_id": payload.node_id, "result_identity": payload.result_identity, "node_result_manifest": _object_to_canonical(payload.node_result_manifest), "outputs": [_output_to_canonical(item) for item in payload.outputs], "artifacts": [_artifact_to_canonical(item) for item in payload.artifacts]}
    if isinstance(payload, OperationAttemptTerminal):
        result = {"operation_attempt_id": payload.operation_attempt_id, "status": payload.status}
        if payload.error is not None: result["error"] = _error_to_canonical(payload.error)
        return result
    if isinstance(payload, NodeAttemptTerminal):
        result = {"node_attempt_id": payload.node_attempt_id, "status": payload.status, "resolution": payload.resolution}
        if payload.error is not None: result["error"] = _error_to_canonical(payload.error)
        if payload.failure_origin is not None: result["failure_origin"] = payload.failure_origin
        return result
    if isinstance(payload, NodeDisposition):
        result = {"node_id": payload.node_id, "outcome": payload.outcome, "blocked_by": list(payload.blocked_by)}
        if payload.resolution is not None: result["resolution"] = payload.resolution
        return result
    if isinstance(payload, SelectionTerminal):
        result = {"status": payload.status}
        if payload.result is not None: result["result"] = _selection_to_canonical(payload.result)
        if payload.error is not None: result["error"] = _error_to_canonical(payload.error)
        return result
    if isinstance(payload, RunTerminal): return {"status": payload.status}
    raise TypeError("Unknown typed Ledger fact")


def _payload_from_canonical(kind: str, value: object) -> FactPayload:
    if not isinstance(value, Mapping): raise ValueError("Ledger payload is invalid")
    v = value
    if kind == "run_scope_bound":
        derived = v.get("derived_from")
        return RunScopeBound(
            project_id=v["project_id"], run_id=v["run_id"], workflow_commit_id=v["workflow_commit_id"], workflow_commit_revision=v["workflow_commit_revision"], workflow_digest=v["workflow_digest"], contract_lock_digest=v["contract_lock_digest"], execution_plan_digest=v["execution_plan_digest"], catalog_contract_digest=v["catalog_contract_digest"],
            resolved_contracts=tuple(_reference_from_canonical(item) for item in v["resolved_contracts"]), resolved_contract_roots=tuple(_reference_from_canonical(item) for item in v["resolved_contract_roots"]), plan_nodes=_plan_evidence_from_canonical(v["plan_nodes"]), selection_required=v["selection_required"], selection_terminal_keys=tuple(v["selection_terminal_keys"]),
            derived_from=(DerivedRunReference(source_run_id=derived["source_run_id"], policy=derived["policy"], selected_node_ids=tuple(derived["selected_node_ids"]), forced_node_ids=tuple(derived["forced_node_ids"])) if isinstance(derived, Mapping) else None),
        )
    if kind == "availability_bound": return AvailabilityBound(_reference_from_canonical(v["binding"]), v["catalog_observed_at"], v["available"])
    if kind == "readiness_attested": return ReadinessAttested(_reference_from_canonical(v["binding"]), v["readiness_contract_digest"], v["observed_at"], v["conclusion"], v["proof_source"], v["attestation_digest"])
    if kind == "run_admitted": return RunAdmitted(v["workflow_commit_id"], v["workflow_commit_revision"])
    if kind == "run_started": return RunStarted(v["started_at"])
    if kind == "cancellation_requested": return CancellationRequested(v["requested_at"])
    if kind == "node_attempt_started": return NodeAttemptStarted(v["node_id"], v["node_attempt_id"])
    if kind == "operation_attempt_started": return OperationAttemptStarted(v["operation_attempt_id"], v["node_attempt_id"])
    if kind == "engine_invocation_started": return EngineInvocationStarted(v["invocation_id"], v["operation_attempt_id"], v["engine_role"], v["engine_identity"], v.get("parent_invocation_id"), _provenance_from_canonical(v["invocation_provenance"]) if "invocation_provenance" in v else None)
    if kind == "engine_invocation_terminal": return EngineInvocationTerminal(v["invocation_id"], v["status"], _error_from_canonical(v["error"]) if "error" in v else None)
    if kind == "outputs_published": return OutputsPublished(v["node_id"], v["result_identity"], _object_from_canonical(v["node_result_manifest"]), tuple(_output_from_canonical(item) for item in v["outputs"]), tuple(_artifact_from_canonical(item) for item in v["artifacts"]))
    if kind == "operation_attempt_terminal": return OperationAttemptTerminal(v["operation_attempt_id"], v["status"], _error_from_canonical(v["error"]) if "error" in v else None)
    if kind == "node_attempt_terminal": return NodeAttemptTerminal(v["node_attempt_id"], v["status"], v["resolution"], _error_from_canonical(v["error"]) if "error" in v else None, v.get("failure_origin"))
    if kind == "node_disposition": return NodeDisposition(v["node_id"], v["outcome"], tuple(v["blocked_by"]), v.get("resolution"))
    if kind == "selection_terminal": return SelectionTerminal(v["status"], _selection_from_canonical(v["result"]) if "result" in v else None, _error_from_canonical(v["error"]) if "error" in v else None)
    if kind == "run_terminal": return RunTerminal(v["status"])
    raise ValueError("Unknown Ledger fact type")


def payload_from_canonical(kind: str, value: object) -> FactPayload:
    """Decode one exact canonical payload into the closed Fact union."""
    payload = _payload_from_canonical(kind, value)
    if (
        not isinstance(value, Mapping)
        or canonical_json_bytes(payload_to_canonical(payload))
        != canonical_json_bytes(dict(value))
    ):
        raise ValueError("Run Ledger fact payload is not canonical")
    validate_fact_payload(payload)
    return payload


def fact_to_canonical(fact: Fact) -> dict[str, Any]:
    return {"sequence": fact.sequence, "recorded_at": fact.recorded_at, "fact_type": fact_type(fact.payload), "payload": payload_to_canonical(fact.payload)}


def fact_from_canonical(value: object) -> Fact:
    raw = _mapping(value, {"sequence", "recorded_at", "fact_type", "payload"})
    if type(raw["sequence"]) is not int or raw["sequence"] < 1 or not is_timestamp(raw["recorded_at"]) or not isinstance(raw["fact_type"], str):
        raise ValueError("Run Ledger fact is invalid")
    return Fact(raw["sequence"], raw["recorded_at"], payload_from_canonical(raw["fact_type"], raw["payload"]))


def transaction_to_canonical(transaction: LedgerTransaction) -> dict[str, Any]:
    return {"schema_namespace": TRANSACTION_NAMESPACE, "schema_version": TRANSACTION_SCHEMA_VERSION, "project_id": transaction.project_id, "run_id": transaction.run_id, "transaction_sequence": transaction.transaction_sequence, "first_fact_sequence": transaction.first_fact_sequence, "last_fact_sequence": transaction.last_fact_sequence, "committed_at": transaction.committed_at, "facts": [fact_to_canonical(fact) for fact in transaction.facts]}


def encode_transaction(transaction: LedgerTransaction) -> bytes:
    return canonical_json_bytes(transaction_to_canonical(transaction))


def decode_transaction(encoded: bytes, *, expected_project_id: str, expected_run_id: str, expected_transaction_sequence: int, expected_first_fact_sequence: int) -> LedgerTransaction:
    try: raw = json.loads(encoded)
    except (UnicodeDecodeError, json.JSONDecodeError) as error: raise ValueError("Run Ledger transaction is invalid") from error
    fields = {"schema_namespace", "schema_version", "project_id", "run_id", "transaction_sequence", "first_fact_sequence", "last_fact_sequence", "committed_at", "facts"}
    if not isinstance(raw, Mapping) or set(raw) != fields or raw["schema_namespace"] != TRANSACTION_NAMESPACE or raw["schema_version"] != TRANSACTION_SCHEMA_VERSION or raw["project_id"] != expected_project_id or raw["run_id"] != expected_run_id or raw["transaction_sequence"] != expected_transaction_sequence or raw["first_fact_sequence"] != expected_first_fact_sequence or not is_timestamp(raw["committed_at"]) or not isinstance(raw["facts"], list) or not raw["facts"] or canonical_json_bytes(dict(raw)) != encoded: raise ValueError("Run Ledger transaction is invalid")
    facts = tuple(fact_from_canonical(item) for item in raw["facts"])
    if facts[0].sequence != raw["first_fact_sequence"] or facts[-1].sequence != raw["last_fact_sequence"] or tuple(f.sequence for f in facts) != tuple(range(facts[0].sequence, facts[-1].sequence + 1)): raise ValueError("Run Ledger fact sequence is invalid")
    return LedgerTransaction(raw["project_id"], raw["run_id"], raw["transaction_sequence"], raw["first_fact_sequence"], raw["last_fact_sequence"], raw["committed_at"], facts)


def encode_cursor(
    sequence: int,
    *,
    project_id: str,
    run_id: str,
    fact: Fact | None,
) -> RunCursor:
    payload = canonical_json_bytes({"schema_namespace": CURSOR_NAMESPACE, "scope_digest": cursor_scope_digest(project_id, run_id), "sequence": sequence, "fact_digest": "origin" if fact is None else canonical_sha256(fact_to_canonical(fact))})
    return RunCursor(
        "pw2."
        + base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")
    )


def cursor_scope_digest(project_id: str, run_id: str) -> str:
    return canonical_sha256(
        {
            "schema_namespace": RUN_SCOPE_NAMESPACE,
            "project_id": project_id,
            "run_id": run_id,
        }
    )


def decode_cursor(value: RunCursor) -> DecodedCursor:
    if type(value) is not RunCursor or not value.value.startswith("pw2."):
        raise ValueError("cursor prefix is invalid")
    encoded = value.value.removeprefix("pw2.")
    if not encoded or re.fullmatch(r"[A-Za-z0-9_-]+", encoded) is None: raise ValueError("cursor encoding is invalid")
    try: payload = json.loads(base64.b64decode(encoded + "=" * (-len(encoded) % 4), altchars=b"-_", validate=True))
    except (binascii.Error, UnicodeDecodeError, json.JSONDecodeError) as error: raise ValueError("cursor encoding is invalid") from error
    if not isinstance(payload, Mapping) or set(payload) != {"schema_namespace", "scope_digest", "sequence", "fact_digest"} or payload["schema_namespace"] != CURSOR_NAMESPACE or not isinstance(payload["scope_digest"], str) or type(payload["sequence"]) is not int or payload["sequence"] < 0 or not isinstance(payload["fact_digest"], str): raise ValueError("cursor payload is invalid")
    return DecodedCursor(
        scope_digest=payload["scope_digest"],
        sequence=payload["sequence"],
        fact_digest=payload["fact_digest"],
    )
