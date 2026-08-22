"""Closed typed fact grammar retained by the Run Evidence Ledger."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
import math
import re
from typing import Literal, TypeAlias

from core.operation import EngineInvocationProvenance
from core.scoring.selection import SelectionInput
from core.execution.ledger.transitions import PlanNodeEvidence
from datatypes.exact_reference import ExactContractReference
from datatypes.i_json import freeze_i_json
from datatypes.residue import residue_identity_chain


_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:/+-]{0,127}")
_SEMANTIC_VERSION = re.compile(
    r"[0-9]+\.[0-9]+\.[0-9]+(?:-[0-9A-Za-z.-]+)?"
)
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


def _validate_reference(
    reference: ExactContractReference,
    *,
    expected_kind: str | None = None,
) -> None:
    if (
        type(reference) is not ExactContractReference
        or reference.contract_kind
        not in {
            "binding",
            "method",
            "metric",
            "node_type",
            "port_type",
            "utility_transform",
        }
        or (
            expected_kind is not None
            and reference.contract_kind != expected_kind
        )
        or not _valid_identifier(reference.contract_id)
        or type(reference.contract_version) is not str
        or _SEMANTIC_VERSION.fullmatch(reference.contract_version) is None
        or not _valid_digest(reference.contract_digest)
    ):
        raise ValueError("Run Ledger contract reference is invalid")


def _validate_error(error: StructuredError | None) -> None:
    if error is None:
        return
    if (
        type(error) is not StructuredError
        or not _valid_identifier(error.code)
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
    if type(provenance) is not EngineInvocationProvenance:
        raise ValueError("Engine invocation provenance is invalid")
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
    projection = provenance.provider_residue_projection
    if projection is None:
        return
    if projection.position_semantics != "one_based_chain_local":
        raise ValueError("Engine invocation residue projection is invalid")
    workbench_order = projection.workbench_chain_order
    structure_order = projection.provider_structure_chain_order
    provider_order = projection.provider_chain_order
    if (
        not workbench_order
        or not structure_order
        or not provider_order
        or len(set(workbench_order)) != len(workbench_order)
        or len(set(structure_order)) != len(structure_order)
        or len(set(provider_order)) != len(provider_order)
        or set(structure_order) != set(provider_order)
        or not projection.entries
    ):
        raise ValueError("Engine invocation residue projection is invalid")
    residue_ids: set[str] = set()
    provider_positions: set[tuple[str, int]] = set()
    observed_workbench_chains: set[str] = set()
    observed_provider_chains: set[str] = set()
    workbench_segment_order: list[str] = []
    current_segment = -1
    current_position = 0
    for entry in projection.entries:
        chain = residue_identity_chain(
            entry.residue_id,
            subject="provider projection residue identity",
        )
        coordinate = (entry.provider_chain_id, entry.provider_position)
        if (
            chain not in workbench_order
            or entry.provider_chain_id not in provider_order
            or type(entry.segment_index) is not int
            or entry.segment_index < current_segment
            or entry.segment_index > current_segment + 1
            or entry.segment_index >= len(structure_order)
            or entry.provider_chain_id != structure_order[entry.segment_index]
            or type(entry.provider_position) is not int
            or entry.provider_position < 1
            or entry.residue_id in residue_ids
            or coordinate in provider_positions
        ):
            raise ValueError("Engine invocation residue projection is invalid")
        if entry.segment_index != current_segment:
            if entry.provider_position != 1:
                raise ValueError(
                    "Engine invocation residue projection is invalid"
                )
            current_segment = entry.segment_index
            current_position = 1
            workbench_segment_order.append(chain)
        elif (
            entry.provider_position != current_position + 1
            or workbench_segment_order[-1] != chain
        ):
            raise ValueError("Engine invocation residue projection is invalid")
        else:
            current_position = entry.provider_position
        residue_ids.add(entry.residue_id)
        provider_positions.add(coordinate)
        observed_workbench_chains.add(chain)
        observed_provider_chains.add(entry.provider_chain_id)
    collapsed_workbench_order = tuple(
        chain
        for index, chain in enumerate(workbench_segment_order)
        if index == 0 or chain != workbench_segment_order[index - 1]
    )
    if (
        observed_workbench_chains != set(workbench_order)
        or observed_provider_chains != set(structure_order)
        or current_segment != len(structure_order) - 1
        or collapsed_workbench_order != workbench_order
    ):
        raise ValueError("Engine invocation residue projection is invalid")


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
    node_id: str
    output_port: str
    port_type: ExactContractReference
    content_digest: str
    result_identity: str
    materialization: object
    producer_provenance: object
    value_count: int
    value_manifest_reference: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "materialization",
            freeze_i_json(self.materialization),
        )
        object.__setattr__(
            self,
            "producer_provenance",
            freeze_i_json(self.producer_provenance),
        )


@dataclass(frozen=True, slots=True)
class PublishedArtifact:
    artifact_reference: str
    artifact_kind: Literal["candidate", "standalone"]
    node_id: str
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
    utility_parameters: object
    declared_weight: float
    effective_weight: float
    match_cardinality: str
    missing_policy: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "utility_parameters",
            freeze_i_json(self.utility_parameters),
        )


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
    workflow_commit_revision: int
    workflow_digest: str
    contract_lock_digest: str
    execution_plan_digest: str
    catalog_contract_digest: str
    resolved_contracts: tuple[ExactContractReference, ...]
    resolved_contract_roots: tuple[ExactContractReference, ...]
    plan_nodes: tuple[PlanNodeEvidence, ...]
    selection_required: bool
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
    readiness_contract_digest: str
    observed_at: str
    conclusion: Literal["passing", "failing"]
    proof_source: str
    attestation_digest: str


@dataclass(frozen=True, slots=True)
class RunAdmitted:
    workflow_commit_id: str
    workflow_commit_revision: int


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
class ArtifactPublished:
    artifact: PublishedArtifact


@dataclass(frozen=True, slots=True)
class OutputsPublished:
    node_id: str
    result_identity: str
    node_result_manifest: ImmutableObjectReference
    outputs: tuple[PublishedOutput, ...]
    artifacts: tuple[PublishedArtifact, ...]
    nonempty_output_ports: tuple[str, ...]


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
    | ArtifactPublished
    | OutputsPublished
    | OperationAttemptTerminal
    | NodeAttemptTerminal
    | NodeDisposition
    | SelectionTerminal
    | RunTerminal
)


@dataclass(frozen=True, slots=True)
class ProposedFact:
    payload: FactPayload


@dataclass(frozen=True, slots=True)
class Fact:
    sequence: int
    recorded_at: str
    payload: FactPayload


@dataclass(frozen=True, slots=True)
class CommittedFactRange:
    first_sequence: int
    last_sequence: int
    facts: tuple[Fact, ...]


def validate_plan_evidence(nodes: tuple[PlanNodeEvidence, ...]) -> None:
    """Validate the closed typed plan evidence retained by a Run scope."""
    if type(nodes) is not tuple:
        raise ValueError("Run plan evidence is invalid")
    node_ids = tuple(node.node_id for node in nodes)
    if len(set(node_ids)) != len(node_ids):
        raise ValueError("Run plan evidence is invalid")
    for node in nodes:
        if (
            type(node) is not PlanNodeEvidence
            or not _valid_identifier(node.node_id)
            or type(node.dependencies) is not tuple
            or node.dependencies != tuple(sorted(set(node.dependencies)))
            or any(dependency not in node_ids for dependency in node.dependencies)
            or not _valid_digest(node.result_identity_plan_facts_digest)
            or node.execution_route not in {"direct", "adapter"}
            or type(node.selection_consumer) is not bool
        ):
            raise ValueError("Run plan evidence is invalid")
        _validate_reference(node.binding, expected_kind="binding")
        if node.node_type is not None:
            _validate_reference(node.node_type, expected_kind="node_type")
        if (
            type(node.required_input_sources) is not tuple
            or node.required_input_sources
            != tuple(
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
                or type(required_input.sources) is not tuple
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
                or type(output.accepted_media_types) is not tuple
                or not output.accepted_media_types
                or output.accepted_media_types
                != tuple(sorted(set(output.accepted_media_types)))
                or (
                    output.artifact_media_type is not None
                    and output.artifact_media_type
                    not in output.accepted_media_types
                )
            ):
                raise ValueError("Run plan Artifact output is invalid")
            _validate_reference(output.port_type, expected_kind="port_type")
            output_names.add(output.output_port)


def _validate_published_output(output: PublishedOutput) -> None:
    if (
        type(output) is not PublishedOutput
        or not _valid_identifier(output.node_id)
        or not _valid_identifier(output.output_port)
        or not _valid_digest(output.content_digest)
        or not _valid_digest(output.result_identity)
        or type(output.value_count) is not int
        or not 0 <= output.value_count <= 65_536
        or not _valid_digest(output.value_manifest_reference)
    ):
        raise ValueError("Run Ledger Typed Output is invalid")
    _validate_reference(output.port_type, expected_kind="port_type")


def _validate_artifact(artifact: PublishedArtifact) -> None:
    if (
        type(artifact) is not PublishedArtifact
        or artifact.artifact_kind not in {"candidate", "standalone"}
        or type(artifact.artifact_reference) is not str
        or not artifact.artifact_reference
        or not _valid_identifier(artifact.node_id)
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
        type(value) is not SelectionInput
        or not _valid_identifier(value.node_id)
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
    if (
        type(value) is not ContextSelectorEvidence
        or type(value.kind) is not str
    ):
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
        type(value) is not SelectionObjectiveEvidence
        or not _valid_identifier(value.objective_id)
        or not _valid_identifier(value.source_partition)
        or not isinstance(value.utility_parameters, Mapping)
        or not _valid_finite_number(value.declared_weight, positive=True)
        or not _valid_finite_number(value.effective_weight, positive=True)
        or float(value.effective_weight) > 1.0
        or value.match_cardinality != "exactly_one"
        or value.missing_policy != "error"
    ):
        raise ValueError("Selection Objective evidence is invalid")
    _validate_selection_input(value.candidate_input)
    _validate_selection_input(value.score_collection_input)
    _validate_reference(value.metric, expected_kind="metric")
    _validate_reference(value.method, expected_kind="method")
    _validate_reference(
        value.utility_transform,
        expected_kind="utility_transform",
    )
    _validate_selection_context(value.context_selector)
    freeze_i_json(value.utility_parameters)


def _validate_observation_selector(
    value: ObservationSelectorEvidence,
) -> None:
    if (
        type(value) is not ObservationSelectorEvidence
        or not _valid_identifier(value.selector_id)
        or not _valid_identifier(value.source_partition)
        or value.match_cardinality != "exactly_one"
        or value.missing_policy != "error"
    ):
        raise ValueError("Observation Selector evidence is invalid")
    _validate_selection_input(value.candidate_input)
    _validate_selection_input(value.score_collection_input)
    _validate_reference(value.metric, expected_kind="metric")
    _validate_reference(value.method, expected_kind="method")
    _validate_selection_context(value.context_selector)


def _validate_selection_result(value: SelectionResult) -> None:
    if (
        type(value) is not SelectionResult
        or not _valid_identifier(value.selection_node_id)
        or not _valid_identifier(value.selected_collection_id)
        or type(value.selected_candidate_ids) is not tuple
        or any(
            not _valid_identifier(candidate_id)
            for candidate_id in value.selected_candidate_ids
        )
        or value.selected_candidate_ids
        != tuple(dict.fromkeys(value.selected_candidate_ids))
        or type(value.objectives) is not tuple
        or type(value.observation_selectors) is not tuple
        or bool(value.objectives) == bool(value.observation_selectors)
    ):
        raise ValueError("Selection result is invalid")
    _validate_reference(value.selection_method, expected_kind="method")
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
            or type(payload.workflow_commit_revision) is not int
            or payload.workflow_commit_revision < 1
            or not all(
                _valid_digest(value)
                for value in (
                    payload.workflow_digest,
                    payload.contract_lock_digest,
                    payload.execution_plan_digest,
                    payload.catalog_contract_digest,
                )
            )
            or type(payload.resolved_contracts) is not tuple
            or type(payload.resolved_contract_roots) is not tuple
            or type(payload.selection_required) is not bool
            or type(payload.selection_terminal_keys) is not tuple
            or payload.selection_terminal_keys
            != tuple(dict.fromkeys(payload.selection_terminal_keys))
        ):
            raise ValueError("Run scope fact is invalid")
        for reference in (
            *payload.resolved_contracts,
            *payload.resolved_contract_roots,
        ):
            _validate_reference(reference)
        if payload.derived_from is not None:
            derived = payload.derived_from
            if (
                type(derived) is not DerivedRunReference
                or not _valid_identifier(derived.source_run_id)
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
        _validate_reference(payload.binding, expected_kind="binding")
        if (
            not _valid_timestamp(payload.catalog_observed_at)
            or type(payload.available) is not bool
        ):
            raise ValueError("Availability evidence is invalid")
        return
    if isinstance(payload, ReadinessAttested):
        _validate_reference(payload.binding, expected_kind="binding")
        if (
            not _valid_digest(payload.readiness_contract_digest)
            or not _valid_timestamp(payload.observed_at)
            or payload.conclusion not in {"passing", "failing"}
            or not _valid_identifier(payload.proof_source)
            or not _valid_digest(payload.attestation_digest)
        ):
            raise ValueError("Readiness evidence is invalid")
        return
    if isinstance(payload, RunAdmitted):
        if (
            not _valid_identifier(payload.workflow_commit_id)
            or type(payload.workflow_commit_revision) is not int
            or payload.workflow_commit_revision < 1
        ):
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
            or not _valid_digest(payload.engine_identity)
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
    if isinstance(payload, ArtifactPublished):
        _validate_artifact(payload.artifact)
        return
    if isinstance(payload, OutputsPublished):
        if (
            not _valid_identifier(payload.node_id)
            or not _valid_digest(payload.result_identity)
            or type(payload.node_result_manifest)
            is not ImmutableObjectReference
            or not _valid_digest(payload.node_result_manifest.content_digest)
            or type(payload.node_result_manifest.size) is not int
            or payload.node_result_manifest.size < 0
            or type(payload.outputs) is not tuple
            or type(payload.artifacts) is not tuple
            or payload.nonempty_output_ports
            != tuple(sorted(set(payload.nonempty_output_ports)))
        ):
            raise ValueError("Typed Output publication is invalid")
        for output in payload.outputs:
            _validate_published_output(output)
            if (
                output.node_id != payload.node_id
                or output.result_identity != payload.result_identity
            ):
                raise ValueError("Typed Output publication is inconsistent")
        for artifact in payload.artifacts:
            _validate_artifact(artifact)
            if artifact.node_id != payload.node_id:
                raise ValueError("Artifact publication is inconsistent")
        expected_nonempty = {
            output.output_port
            for output in payload.outputs
            if output.value_count > 0
        } | {artifact.output_port for artifact in payload.artifacts}
        if set(payload.nonempty_output_ports) != expected_nonempty:
            raise ValueError("Typed Output publication is inconsistent")
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
