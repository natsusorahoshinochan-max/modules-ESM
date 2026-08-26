"""Closed typed fact grammar retained by the Run Evidence Ledger."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
import math
import re
from typing import Literal, TypeAlias

from core.catalog.port_contract import is_valid_artifact_media_type
from core.operation import EngineInvocationProvenance
from core.scoring.selection import SelectionInput
from core.execution.ledger.transitions import PlanNodeEvidence
from datatypes.exact_reference import ExactContractReference
from datatypes.i_json import freeze_i_json


_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:/+-]{0,127}")
_SHA256 = re.compile(r"sha256:[0-9a-f]{64}")


def _valid_identifier(value: object) -> bool:
    return type(value) is str and _IDENTIFIER.fullmatch(value) is not None


def _valid_digest(value: object) -> bool:
    return type(value) is str and _SHA256.fullmatch(value) is not None


def _valid_timestamp(value: object) -> bool:
    if type(value) is not str or not 20 <= len(value) <= 64:
        return False
    try:
        return datetime.fromisoformat(value).tzinfo is not None
    except ValueError:
        return False


def _require_reference_kind(
    reference: ExactContractReference,
    *,
    expected_kind: str,
) -> None:
    if reference.contract_kind != expected_kind:
        raise ValueError("Run Ledger contract reference is invalid")


def _validate_error(error: StructuredError | None) -> None:
    if error is None:
        return
    if (
        not _valid_identifier(error.code)
        or type(error.message) is not str
        or not 1 <= len(error.message) <= 2048
        or type(error.retryable) is not bool
        or not _valid_identifier(error.correlation_id)
    ):
        raise ValueError("Run Ledger structured error is invalid")


def _validate_invocation_provenance(
    provenance: EngineInvocationProvenance | None,
) -> None:
    if provenance is None:
        return
    randomness = provenance.effective_randomness
    if randomness is not None and (
        randomness.control not in {"exact_seed", "provider_uncontrolled"}
        or (
            randomness.control == "exact_seed"
            and type(randomness.effective_seed) is not int
        )
        or (
            randomness.control == "provider_uncontrolled"
            and randomness.effective_seed is not None
        )
    ):
        raise ValueError("Engine invocation randomness is invalid")
    if (
        provenance.project_input_filename is not None
        and (
            type(provenance.project_input_filename) is not str
            or not provenance.project_input_filename
        )
    ):
        raise ValueError("Engine invocation input filename is invalid")


@dataclass(frozen=True, slots=True)
class ImmutableObjectReference:
    content_digest: str
    size: int


@dataclass(frozen=True, slots=True)
class StructuredError:
    code: str
    message: str
    retryable: bool
    correlation_id: str
    details: object

    def __post_init__(self) -> None:
        object.__setattr__(self, "details", freeze_i_json(self.details))


@dataclass(frozen=True, slots=True)
class PublishedOutput:
    output_port: str
    port_type: ExactContractReference
    content_digest: str
    materialization: object
    producer_run_id: str
    value_count: int
    value_manifest_reference: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "materialization",
            freeze_i_json(self.materialization),
        )


@dataclass(frozen=True, slots=True)
class PublishedArtifact:
    artifact_reference: str
    artifact_kind: Literal["candidate", "standalone"]
    output_port: str
    media_type: str
    filename: str
    size: int
    content_digest: str
    candidate_id: str | None = None


@dataclass(frozen=True, slots=True)
class DerivedRunReference:
    source_run_id: str
    policy: Literal["retry_failed", "force_selected"]
    selected_node_ids: tuple[str, ...]
    forced_node_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ContextSelectorEvidence:
    kind: Literal["intrinsic", "calibration", "pairwise"]
    calibration_metric: str | None = None
    calibration_value: float | None = None
    calibration_unit: str | None = None
    population_id: str | None = None
    subject_role: str | None = None
    reference_role: str | None = None
    pairing_mode: str | None = None
    normalization: str | None = None


@dataclass(frozen=True, slots=True)
class SelectionObjectiveEvidence:
    objective_id: str
    candidate_input: SelectionInput
    score_collection_input: SelectionInput
    source_partition: str
    metric: ExactContractReference
    method: ExactContractReference
    context_selector: ContextSelectorEvidence
    utility_transform: ExactContractReference
    utility_parameters: Mapping[str, object]
    declared_weight: float
    effective_weight: float
    match_cardinality: str
    missing_policy: str

@dataclass(frozen=True, slots=True)
class ObservationSelectorEvidence:
    selector_id: str
    candidate_input: SelectionInput
    score_collection_input: SelectionInput
    source_partition: str
    metric: ExactContractReference
    method: ExactContractReference
    context_selector: ContextSelectorEvidence
    match_cardinality: str
    missing_policy: str


@dataclass(frozen=True, slots=True)
class SelectionResult:
    selection_node_id: str
    selection_method: ExactContractReference
    candidate_input: SelectionInput
    selected_collection_id: str
    selected_candidate_ids: tuple[str, ...]
    objectives: tuple[SelectionObjectiveEvidence, ...] = ()
    observation_selectors: tuple[ObservationSelectorEvidence, ...] = ()


@dataclass(frozen=True, slots=True)
class RunScopeBound:
    project_id: str
    run_id: str
    workflow_commit_id: str
    plan_nodes: tuple[PlanNodeEvidence, ...]
    selection_terminal_keys: tuple[str, ...]
    derived_from: DerivedRunReference | None = None


@dataclass(frozen=True, slots=True)
class AvailabilityBound:
    binding: ExactContractReference
    catalog_observed_at: str
    available: bool


@dataclass(frozen=True, slots=True)
class ReadinessAttested:
    binding: ExactContractReference
    observed_at: str
    conclusion: Literal["passing", "failing"]
    proof_source: str


@dataclass(frozen=True, slots=True)
class RunAdmitted:
    workflow_commit_id: str


@dataclass(frozen=True, slots=True)
class RunStarted:
    started_at: str


@dataclass(frozen=True, slots=True)
class CancellationRequested:
    requested_at: str


@dataclass(frozen=True, slots=True)
class NodeAttemptStarted:
    node_id: str
    node_attempt_id: str


@dataclass(frozen=True, slots=True)
class OperationAttemptStarted:
    operation_attempt_id: str
    node_attempt_id: str


@dataclass(frozen=True, slots=True)
class EngineInvocationStarted:
    invocation_id: str
    operation_attempt_id: str
    engine_role: str
    engine_identity: str
    parent_invocation_id: str | None = None
    provenance: EngineInvocationProvenance | None = None


AttemptStatus: TypeAlias = Literal[
    "succeeded",
    "failed",
    "cancelled",
    "interrupted",
    "outcome_unknown",
]


@dataclass(frozen=True, slots=True)
class EngineInvocationTerminal:
    invocation_id: str
    status: AttemptStatus
    error: StructuredError | None = None


@dataclass(frozen=True, slots=True)
class OutputsPublished:
    node_id: str
    result_identity: str
    node_result_manifest: ImmutableObjectReference
    outputs: tuple[PublishedOutput, ...]
    artifacts: tuple[PublishedArtifact, ...]


@dataclass(frozen=True, slots=True)
class OperationAttemptTerminal:
    operation_attempt_id: str
    status: AttemptStatus
    error: StructuredError | None = None


@dataclass(frozen=True, slots=True)
class NodeAttemptTerminal:
    node_attempt_id: str
    status: AttemptStatus
    resolution: Literal["executed", "cache_replayed"]
    error: StructuredError | None = None
    failure_origin: Literal[
        "attempt",
        "binding",
        "operation",
        "publication",
    ] | None = None


@dataclass(frozen=True, slots=True)
class NodeDisposition:
    node_id: str
    outcome: Literal[
        "succeeded",
        "failed",
        "blocked",
        "cancelled",
        "interrupted",
    ]
    blocked_by: tuple[str, ...]
    resolution: Literal["executed", "cache_replayed"] | None = None


@dataclass(frozen=True, slots=True)
class SelectionTerminal:
    status: Literal["succeeded", "failed"]
    result: SelectionResult | None = None
    error: StructuredError | None = None


@dataclass(frozen=True, slots=True)
class RunTerminal:
    status: Literal["succeeded", "failed", "cancelled", "interrupted"]


FactPayload: TypeAlias = (
    RunScopeBound
    | AvailabilityBound
    | ReadinessAttested
    | RunAdmitted
    | RunStarted
    | CancellationRequested
    | NodeAttemptStarted
    | OperationAttemptStarted
    | EngineInvocationStarted
    | EngineInvocationTerminal
    | OutputsPublished
    | OperationAttemptTerminal
    | NodeAttemptTerminal
    | NodeDisposition
    | SelectionTerminal
    | RunTerminal
)


@dataclass(frozen=True, slots=True)
class Fact:
    sequence: int
    recorded_at: str
    payload: FactPayload


def validate_plan_evidence(nodes: tuple[PlanNodeEvidence, ...]) -> None:
    """Validate the closed typed plan evidence retained by a Run scope."""
    node_ids = tuple(node.node_id for node in nodes)
    if len(set(node_ids)) != len(node_ids):
        raise ValueError("Run plan evidence is invalid")
    for node in nodes:
        if (
            not _valid_identifier(node.node_id)
            or node.dependencies != tuple(sorted(set(node.dependencies)))
            or any(dependency not in node_ids for dependency in node.dependencies)
            or node.execution_route not in {"direct", "adapter"}
            or type(node.selection_consumer) is not bool
        ):
            raise ValueError("Run plan evidence is invalid")
        _require_reference_kind(node.node_type, expected_kind="node_type")
        _require_reference_kind(node.binding, expected_kind="binding")
        _require_reference_kind(node.method, expected_kind="method")
        if (
            node.required_input_sources != tuple(
                sorted(
                    set(node.required_input_sources),
                    key=lambda item: item.input_port,
                )
            )
        ):
            raise ValueError("Run plan required inputs are invalid")
        for required_input in node.required_input_sources:
            if (
                not _valid_identifier(required_input.input_port)
                or not required_input.sources
                or required_input.sources
                != tuple(
                    sorted(
                        set(required_input.sources),
                        key=lambda item: (item.node_id, item.output_port),
                    )
                )
                or any(
                    not _valid_identifier(source.node_id)
                    or not _valid_identifier(source.output_port)
                    or source.node_id not in node.dependencies
                    for source in required_input.sources
                )
            ):
                raise ValueError("Run plan required inputs are invalid")
        output_names: set[str] = set()
        for output in node.artifact_outputs:
            if (
                not _valid_identifier(output.output_port)
                or output.output_port in output_names
                or output.artifact_kind not in {"candidate", "standalone"}
                or not output.accepted_media_types
                or any(
                    type(media_type) is not str
                    or not is_valid_artifact_media_type(media_type)
                    for media_type in output.accepted_media_types
                )
                or output.accepted_media_types
                != tuple(sorted(set(output.accepted_media_types)))
                or (
                    output.artifact_media_type is not None
                    and output.artifact_media_type
                    not in output.accepted_media_types
                )
            ):
                raise ValueError("Run plan Artifact output is invalid")
            _require_reference_kind(
                output.port_type,
                expected_kind="port_type",
            )
            output_names.add(output.output_port)


def _validate_published_output(output: PublishedOutput) -> None:
    if (
        not _valid_identifier(output.output_port)
        or not _valid_digest(output.content_digest)
        or type(output.value_count) is not int
        or not 0 <= output.value_count <= 65_536
        or not _valid_digest(output.value_manifest_reference)
    ):
        raise ValueError("Run Ledger Typed Output is invalid")
    _require_reference_kind(output.port_type, expected_kind="port_type")


def _validate_artifact(artifact: PublishedArtifact) -> None:
    if (
        artifact.artifact_kind not in {"candidate", "standalone"}
        or type(artifact.artifact_reference) is not str
        or not artifact.artifact_reference
        or not _valid_identifier(artifact.output_port)
        or type(artifact.media_type) is not str
        or not artifact.media_type
        or type(artifact.filename) is not str
        or not artifact.filename
        or type(artifact.size) is not int
        or artifact.size < 0
        or not _valid_digest(artifact.content_digest)
        or (artifact.artifact_kind == "candidate")
        != (artifact.candidate_id is not None)
    ):
        raise ValueError("Run Ledger Artifact is invalid")


def _validate_selection_input(value: SelectionInput) -> None:
    if (
        not _valid_identifier(value.node_id)
        or not _valid_identifier(value.output_port)
    ):
        raise ValueError("Selection input evidence is invalid")


def _valid_finite_number(value: object, *, positive: bool = False) -> bool:
    if type(value) not in {int, float}:
        return False
    try:
        numeric = float(value)
    except OverflowError:
        return False
    return (
        math.isfinite(numeric)
        and not (numeric == 0 and math.copysign(1.0, numeric) < 0)
        and (not positive or numeric > 0)
    )


def _validate_selection_context(value: ContextSelectorEvidence) -> None:
    if type(value.kind) is not str:
        raise ValueError("Selection Context evidence is invalid")
    calibration_fields = (
        value.calibration_metric,
        value.calibration_value,
        value.calibration_unit,
        value.population_id,
    )
    pairwise_fields = (
        value.subject_role,
        value.reference_role,
        value.pairing_mode,
        value.normalization,
    )
    if value.kind == "intrinsic":
        if any(
            item is not None
            for item in (*calibration_fields, *pairwise_fields)
        ):
            raise ValueError("Selection Context evidence is invalid")
        return
    if value.kind == "calibration":
        if (
            not _valid_identifier(value.calibration_metric)
            or not _valid_finite_number(value.calibration_value)
            or not _valid_identifier(value.calibration_unit)
            or not _valid_identifier(value.population_id)
            or any(item is not None for item in pairwise_fields)
        ):
            raise ValueError("Selection Context evidence is invalid")
        return
    if value.kind == "pairwise":
        if (
            any(item is not None for item in calibration_fields)
            or type(value.subject_role) is not str
            or value.subject_role != "subject"
            or type(value.reference_role) is not str
            or value.reference_role != "reference"
            or type(value.pairing_mode) is not str
            or value.pairing_mode
            not in {"fixed_reference", "per_subject_counterpart"}
            or not _valid_identifier(value.normalization)
        ):
            raise ValueError("Selection Context evidence is invalid")
        return
    raise ValueError("Selection Context evidence is invalid")


def _validate_selection_objective(
    value: SelectionObjectiveEvidence,
) -> None:
    if (
        not _valid_identifier(value.objective_id)
        or not _valid_identifier(value.source_partition)
        or not _valid_finite_number(value.declared_weight, positive=True)
        or not _valid_finite_number(value.effective_weight, positive=True)
        or float(value.effective_weight) > 1.0
        or value.match_cardinality != "exactly_one"
        or value.missing_policy != "error"
    ):
        raise ValueError("Selection Objective evidence is invalid")
    _validate_selection_input(value.candidate_input)
    _validate_selection_input(value.score_collection_input)
    _require_reference_kind(value.metric, expected_kind="metric")
    _require_reference_kind(value.method, expected_kind="method")
    _require_reference_kind(
        value.utility_transform,
        expected_kind="utility_transform",
    )
    _validate_selection_context(value.context_selector)


def _validate_observation_selector(
    value: ObservationSelectorEvidence,
) -> None:
    if (
        not _valid_identifier(value.selector_id)
        or not _valid_identifier(value.source_partition)
        or value.match_cardinality != "exactly_one"
        or value.missing_policy != "error"
    ):
        raise ValueError("Observation Selector evidence is invalid")
    _validate_selection_input(value.candidate_input)
    _validate_selection_input(value.score_collection_input)
    _require_reference_kind(value.metric, expected_kind="metric")
    _require_reference_kind(value.method, expected_kind="method")
    _validate_selection_context(value.context_selector)


def _validate_selection_result(value: SelectionResult) -> None:
    if (
        not _valid_identifier(value.selection_node_id)
        or not _valid_identifier(value.selected_collection_id)
        or any(
            not _valid_identifier(candidate_id)
            for candidate_id in value.selected_candidate_ids
        )
        or value.selected_candidate_ids
        != tuple(dict.fromkeys(value.selected_candidate_ids))
        or bool(value.objectives) == bool(value.observation_selectors)
    ):
        raise ValueError("Selection result is invalid")
    _require_reference_kind(value.selection_method, expected_kind="method")
    _validate_selection_input(value.candidate_input)
    if value.objectives:
        for objective in value.objectives:
            _validate_selection_objective(objective)
            if objective.candidate_input != value.candidate_input:
                raise ValueError(
                    "Selection Objective evidence is inconsistent"
                )
        objective_ids = tuple(
            objective.objective_id for objective in value.objectives
        )
        if objective_ids != tuple(dict.fromkeys(objective_ids)):
            raise ValueError("Selection Objective evidence is invalid")
        declared_total = math.fsum(
            float(objective.declared_weight) for objective in value.objectives
        )
        effective_total = math.fsum(
            float(objective.effective_weight) for objective in value.objectives
        )
        if (
            not math.isfinite(declared_total)
            or not math.isclose(
                effective_total,
                1.0,
                rel_tol=1e-12,
                abs_tol=1e-12,
            )
            or any(
                not math.isclose(
                    float(objective.effective_weight),
                    float(objective.declared_weight) / declared_total,
                    rel_tol=1e-12,
                    abs_tol=1e-12,
                )
                for objective in value.objectives
            )
        ):
            raise ValueError("Selection Objective weights are invalid")
        return
    for selector in value.observation_selectors:
        _validate_observation_selector(selector)
        if selector.candidate_input != value.candidate_input:
            raise ValueError(
                "Observation Selector evidence is inconsistent"
            )
    selector_ids = tuple(
        selector.selector_id for selector in value.observation_selectors
    )
    if selector_ids != tuple(dict.fromkeys(selector_ids)):
        raise ValueError("Observation Selector evidence is invalid")


def validate_fact_payload(payload: FactPayload) -> None:
    """Validate one owner-typed fact without projecting through JSON."""
    if isinstance(payload, RunScopeBound):
        validate_plan_evidence(payload.plan_nodes)
        if (
            not _valid_identifier(payload.project_id)
            or not _valid_identifier(payload.run_id)
            or not _valid_identifier(payload.workflow_commit_id)
            or payload.selection_terminal_keys
            != tuple(dict.fromkeys(payload.selection_terminal_keys))
        ):
            raise ValueError("Run scope fact is invalid")
        if payload.derived_from is not None:
            derived = payload.derived_from
            if (
                not _valid_identifier(derived.source_run_id)
                or derived.policy not in {"retry_failed", "force_selected"}
                or derived.selected_node_ids
                != tuple(dict.fromkeys(derived.selected_node_ids))
                or derived.forced_node_ids
                != tuple(dict.fromkeys(derived.forced_node_ids))
                or any(
                    node_id not in {node.node_id for node in payload.plan_nodes}
                    for node_id in (
                        *derived.selected_node_ids,
                        *derived.forced_node_ids,
                    )
                )
            ):
                raise ValueError("Derived Run evidence is invalid")
        return
    if isinstance(payload, AvailabilityBound):
        _require_reference_kind(payload.binding, expected_kind="binding")
        if (
            not _valid_timestamp(payload.catalog_observed_at)
            or type(payload.available) is not bool
        ):
            raise ValueError("Availability evidence is invalid")
        return
    if isinstance(payload, ReadinessAttested):
        _require_reference_kind(payload.binding, expected_kind="binding")
        if (
            not _valid_timestamp(payload.observed_at)
            or payload.conclusion not in {"passing", "failing"}
            or not _valid_identifier(payload.proof_source)
        ):
            raise ValueError("Readiness evidence is invalid")
        return
    if isinstance(payload, RunAdmitted):
        if not _valid_identifier(payload.workflow_commit_id):
            raise ValueError("Run admission evidence is invalid")
        return
    if isinstance(payload, (RunStarted, CancellationRequested)):
        timestamp = (
            payload.started_at
            if isinstance(payload, RunStarted)
            else payload.requested_at
        )
        if not _valid_timestamp(timestamp):
            raise ValueError("Run timestamp evidence is invalid")
        return
    if isinstance(payload, NodeAttemptStarted):
        if not _valid_identifier(payload.node_id) or not _valid_identifier(
            payload.node_attempt_id
        ):
            raise ValueError("Node Attempt evidence is invalid")
        return
    if isinstance(payload, OperationAttemptStarted):
        if not _valid_identifier(
            payload.operation_attempt_id
        ) or not _valid_identifier(payload.node_attempt_id):
            raise ValueError("Operation Attempt evidence is invalid")
        return
    if isinstance(payload, EngineInvocationStarted):
        if (
            not _valid_identifier(payload.invocation_id)
            or not _valid_identifier(payload.operation_attempt_id)
            or not _valid_identifier(payload.engine_role)
            or not _valid_identifier(payload.engine_identity)
            or (
                payload.parent_invocation_id is not None
                and not _valid_identifier(payload.parent_invocation_id)
            )
        ):
            raise ValueError("Engine Invocation evidence is invalid")
        _validate_invocation_provenance(payload.provenance)
        return
    if isinstance(payload, EngineInvocationTerminal):
        if (
            not _valid_identifier(payload.invocation_id)
            or payload.status
            not in {
                "succeeded",
                "failed",
                "cancelled",
                "interrupted",
                "outcome_unknown",
            }
        ):
            raise ValueError("Engine Invocation conclusion is invalid")
        _validate_error(payload.error)
        return
    if isinstance(payload, OutputsPublished):
        if (
            not _valid_identifier(payload.node_id)
            or not _valid_digest(payload.result_identity)
            or not _valid_digest(payload.node_result_manifest.content_digest)
            or type(payload.node_result_manifest.size) is not int
            or payload.node_result_manifest.size < 0
        ):
            raise ValueError("Typed Output publication is invalid")
        for output in payload.outputs:
            _validate_published_output(output)
        for artifact in payload.artifacts:
            _validate_artifact(artifact)
        return
    if isinstance(payload, OperationAttemptTerminal):
        if (
            not _valid_identifier(payload.operation_attempt_id)
            or payload.status
            not in {
                "succeeded",
                "failed",
                "cancelled",
                "interrupted",
                "outcome_unknown",
            }
        ):
            raise ValueError("Operation Attempt conclusion is invalid")
        _validate_error(payload.error)
        return
    if isinstance(payload, NodeAttemptTerminal):
        if (
            not _valid_identifier(payload.node_attempt_id)
            or payload.status
            not in {
                "succeeded",
                "failed",
                "cancelled",
                "interrupted",
                "outcome_unknown",
            }
            or payload.resolution not in {"executed", "cache_replayed"}
            or (payload.status == "failed")
            != (
                payload.failure_origin
                in {"attempt", "binding", "operation", "publication"}
            )
        ):
            raise ValueError("Node Attempt conclusion is invalid")
        _validate_error(payload.error)
        if payload.status == "failed" and payload.error is None:
            raise ValueError("Node Attempt failure lacks an error")
        return
    if isinstance(payload, NodeDisposition):
        if (
            not _valid_identifier(payload.node_id)
            or payload.outcome
            not in {
                "succeeded",
                "failed",
                "blocked",
                "cancelled",
                "interrupted",
            }
            or payload.blocked_by != tuple(sorted(set(payload.blocked_by)))
            or (payload.outcome == "succeeded")
            != (payload.resolution is not None)
            or (
                payload.resolution is not None
                and payload.resolution not in {"executed", "cache_replayed"}
            )
        ):
            raise ValueError("Node disposition is invalid")
        return
    if isinstance(payload, SelectionTerminal):
        if (
            payload.status not in {"succeeded", "failed"}
            or (payload.status == "succeeded")
            != (payload.result is not None and payload.error is None)
            or (payload.status == "failed")
            != (payload.error is not None and payload.result is None)
        ):
            raise ValueError("Selection conclusion is invalid")
        _validate_error(payload.error)
        if payload.result is not None:
            _validate_selection_result(payload.result)
        return
    if isinstance(payload, RunTerminal):
        if payload.status not in {
            "succeeded",
            "failed",
            "cancelled",
            "interrupted",
        }:
            raise ValueError("Run conclusion is invalid")
        return
    raise TypeError("Run Ledger fact payload is not current")
