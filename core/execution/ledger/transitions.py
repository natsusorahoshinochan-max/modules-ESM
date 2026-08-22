"""Typed Run Evidence Ledger transitions and immutable Run plan evidence."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from core.operation import EngineInvocationProvenance
from datatypes.exact_reference import ExactContractReference

if TYPE_CHECKING:
    from core.execution.ledger.facts import (
        DerivedRunReference,
        ImmutableObjectReference,
        PublishedArtifact,
        PublishedOutput,
        SelectionResult,
        StructuredError,
    )
    from core.execution.ledger.projections import RunCursor


@dataclass(frozen=True, slots=True)
class PlanValueSourceEvidence:
    node_id: str
    output_port: str


@dataclass(frozen=True, slots=True)
class PlanRequiredInputEvidence:
    input_port: str
    sources: tuple[PlanValueSourceEvidence, ...]


@dataclass(frozen=True, slots=True)
class ArtifactOutputEvidence:
    output_port: str
    artifact_kind: Literal["candidate", "standalone"]
    artifact_media_type: str | None
    port_type: ExactContractReference
    accepted_media_types: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PlanNodeEvidence:
    node_id: str
    dependencies: tuple[str, ...]
    required_input_sources: tuple[PlanRequiredInputEvidence, ...]
    result_identity_plan_facts_digest: str
    binding: ExactContractReference
    execution_route: Literal["direct", "adapter"]
    node_type: ExactContractReference | None = None
    artifact_outputs: tuple[ArtifactOutputEvidence, ...] = ()
    selection_consumer: bool = False


@dataclass(frozen=True, slots=True)
class RunScopeBinding:
    """Complete immutable Run scope selected before Ledger admission."""

    workflow_commit_id: str
    workflow_commit_revision: int
    workflow_digest: str
    contract_lock_digest: str
    execution_plan_digest: str
    catalog_contract_digest: str
    resolved_contracts: tuple[ExactContractReference, ...]
    resolved_contract_roots: tuple[ExactContractReference, ...]
    derived_from: DerivedRunReference | None = None


@dataclass(frozen=True, slots=True)
class AvailabilityBinding:
    """One exact Binding Availability snapshot selected for this Run."""

    binding: ExactContractReference
    catalog_observed_at: str
    available: bool


@dataclass(frozen=True, slots=True)
class RunAdmission:
    """The exact Workflow Commit admitted into one bound Run scope."""

    workflow_commit_id: str
    workflow_commit_revision: int


@dataclass(frozen=True, slots=True)
class RunStart:
    """The execution start of one admitted Run."""

    started_at: str


@dataclass(frozen=True, slots=True)
class ReadinessAttestation:
    """One complete run-scoped Readiness conclusion for an exact Binding."""

    binding: ExactContractReference
    readiness_contract_digest: str
    observed_at: str
    conclusion: Literal["passing", "failing"]
    proof_source: str


@dataclass(frozen=True, slots=True)
class EngineInvocationStart:
    """One complete typed entry into a declared scientific engine seam."""

    invocation_id: str
    operation_attempt_id: str
    engine_role: str
    engine_identity: str
    parent_invocation_id: str | None = None
    provenance: EngineInvocationProvenance | None = None


@dataclass(frozen=True, slots=True)
class NodeAttemptStart:
    """One scheduled Node Execution Attempt start."""

    node_id: str
    node_attempt_id: str


@dataclass(frozen=True, slots=True)
class OperationAttemptStart:
    """One Operation Attempt start under a Node Execution Attempt."""

    node_attempt_id: str
    operation_attempt_id: str


@dataclass(frozen=True, slots=True)
class EngineInvocationConclusion:
    """One complete terminal conclusion for a started Engine Invocation."""

    invocation_id: str
    status: Literal[
        "succeeded",
        "failed",
        "cancelled",
        "interrupted",
        "outcome_unknown",
    ]
    error: StructuredError | None = None


@dataclass(frozen=True, slots=True)
class NodeSuccessPublication:
    """Complete successful Node Outcome Publication selected by runtime."""

    node_id: str
    node_attempt_id: str
    operation_attempt_id: str | None
    resolution: Literal["executed", "cache_replayed"]
    result_identity: str
    node_result_manifest: ImmutableObjectReference
    outputs: tuple[PublishedOutput, ...]
    artifacts: tuple[PublishedArtifact, ...]
    nonempty_output_ports: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class NodeFailurePublication:
    """Complete failed Node Outcome Publication selected by runtime."""

    node_id: str
    node_attempt_id: str
    operation_attempt_id: str | None
    resolution: Literal["executed", "cache_replayed"]
    error: StructuredError
    failure_origin: Literal[
        "attempt",
        "binding",
        "operation",
        "publication",
    ]


@dataclass(frozen=True, slots=True)
class NodeTerminationPublication:
    """Complete cancelled or interrupted Node outcome at its causal depth."""

    node_id: str
    status: Literal["cancelled", "interrupted", "outcome_unknown"]
    node_attempt_id: str
    operation_attempt_id: str | None = None
    operation_status: Literal[
        "succeeded",
        "cancelled",
        "interrupted",
        "outcome_unknown",
    ] | None = None
    resolution: Literal["executed", "cache_replayed"] = "executed"
    error: StructuredError | None = None


@dataclass(frozen=True, slots=True)
class UnstartedNodeConclusion:
    """One complete disposition for a Node with no Execution Attempt."""

    node_id: str
    outcome: Literal["blocked", "cancelled", "interrupted"]
    blocked_by: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class SelectionSuccess:
    """One successful Selection conclusion chosen for Run Closure."""

    result: SelectionResult


@dataclass(frozen=True, slots=True)
class SelectionFailure:
    """One failed Selection conclusion chosen for Run Closure."""

    error: StructuredError


SelectionConclusion = SelectionSuccess | SelectionFailure


@dataclass(frozen=True, slots=True)
class RunClosure:
    """The complete normal Selection and Run Closure conclusion."""

    selections: tuple[SelectionConclusion, ...] = ()


LedgerTransition = (
    RunScopeBinding
    | AvailabilityBinding
    | RunAdmission
    | RunStart
    | ReadinessAttestation
    | NodeAttemptStart
    | OperationAttemptStart
    | EngineInvocationStart
    | EngineInvocationConclusion
    | NodeSuccessPublication
    | NodeFailurePublication
    | NodeTerminationPublication
    | UnstartedNodeConclusion
    | RunClosure
)


@dataclass(frozen=True, slots=True)
class LedgerAcknowledgement:
    """The durable logical range acknowledged for one typed transition."""

    first_sequence: int
    last_sequence: int
    cursor: RunCursor
