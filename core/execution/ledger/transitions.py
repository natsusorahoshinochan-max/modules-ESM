"""Typed Run Evidence Ledger transitions and immutable Run plan evidence."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from datatypes.exact_reference import ExactContractReference

if TYPE_CHECKING:
    from core.execution.ledger.facts import (
        DerivedRunReference,
        ImmutableObjectReference,
        PublishedArtifact,
        PublishedOutput,
        SelectionTerminal,
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
    node_type: ExactContractReference
    binding: ExactContractReference
    method: ExactContractReference
    execution_route: Literal["direct", "adapter"]
    artifact_outputs: tuple[ArtifactOutputEvidence, ...] = ()
    selection_consumer: bool = False


@dataclass(frozen=True, slots=True)
class RunScopeBinding:
    """Complete immutable Run scope selected before Ledger admission."""

    workflow_commit_id: str
    derived_from: DerivedRunReference | None = None


@dataclass(frozen=True, slots=True)
class ReadinessAttestation:
    """One complete run-scoped Readiness conclusion for a Binding."""

    binding: ExactContractReference
    observed_at: str
    conclusion: Literal["passing", "failing"]
    proof_source: str


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
class RunClosure:
    """The complete normal Selection and Run Closure conclusion."""

    selections: tuple[SelectionTerminal, ...] = ()


@dataclass(frozen=True, slots=True)
class LedgerAcknowledgement:
    """The durable logical range acknowledged for one typed transition."""

    first_sequence: int
    last_sequence: int
    cursor: RunCursor
