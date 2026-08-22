"""Selection outcome projection consumed by Run Runtime closure."""

from __future__ import annotations

from collections.abc import Mapping
import re
from typing import Any
import uuid

from core.execution.ledger import (
    ContextSelectorEvidence,
    ObservationSelectorEvidence,
    SelectionObjectiveEvidence,
    SelectionResult,
    StructuredError,
)
from core.operation import AdmittedPort
from core.scoring.selection import (
    PairwiseContextSelector,
    SelectionError,
    observation_selector_provenance_from_facts,
    selection_objective_provenance_from_facts,
)
from core.workflow.plan import ExecutionPlanNode
from datatypes.candidate import CandidateCollection
from datatypes.exact_reference import ExactContractReference
from datatypes.observation import (
    CalibrationObservationContext,
    IntrinsicObservationContext,
)


_PUBLIC_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:/+-]*$")


def _selection_error(error: BaseException) -> StructuredError:
    error_type = type(error).__name__
    if (
        len(error_type) > 128
        or _PUBLIC_IDENTIFIER.fullmatch(error_type) is None
    ):
        error_type = "Exception"
    details = (
        {"reason": str(error)}
        if isinstance(error, SelectionError)
        else {"exception_type": error_type}
    )
    return StructuredError(
        code="selection_failed",
        message="Workflow selection failed safely",
        retryable=False,
        correlation_id=f"incident-{uuid.uuid4().hex}",
        details=details,
    )


def _exact_reference(reference: Any) -> ExactContractReference:
    return ExactContractReference(
        contract_kind=reference.contract_kind,
        contract_id=reference.contract_id,
        contract_version=reference.contract_version,
        contract_digest=reference.contract_digest,
    )


def _context_selector_evidence(value: object) -> ContextSelectorEvidence:
    if isinstance(value, IntrinsicObservationContext):
        return ContextSelectorEvidence(kind="intrinsic")
    if isinstance(value, CalibrationObservationContext):
        return ContextSelectorEvidence(
            kind="calibration",
            calibration_metric=value.calibration_metric,
            calibration_value=value.calibration_value,
            calibration_unit=value.calibration_unit,
            population_id=value.population_id,
        )
    if isinstance(value, PairwiseContextSelector):
        return ContextSelectorEvidence(
            kind="pairwise",
            subject_role=value.subject_role,
            reference_role=value.reference_role,
            pairing_mode=value.pairing_mode,
            normalization=value.normalization,
        )
    raise TypeError("Selection Context selector is not current")


def selection_consumer_result(
    node: ExecutionPlanNode,
    values: Mapping[tuple[str, str], AdmittedPort],
) -> SelectionResult:
    """Project one declared selection Node's actual typed output."""
    resolved_objectives = node._runtime.selection_objectives
    resolved_selectors = node._runtime.observation_selectors
    if resolved_selectors:
        candidate_references = {
            selector.candidate_input for selector in resolved_selectors
        }
    else:
        candidate_references = {
            objective.candidate_input for objective in resolved_objectives
        }
    if len(candidate_references) != 1:
        raise SelectionError(
            "Selection consumer objectives do not share one Candidate input"
        )
    output_port = node._runtime.selection_candidate_output_port
    resolved = (
        values.get((node.node_id, output_port))
        if isinstance(output_port, str)
        else None
    )
    if (
        resolved is None
        or resolved.multiplicity != "one"
        or type(resolved.value) is not CandidateCollection
    ):
        raise SelectionError(
            "Selection consumer output did not resolve to one exact "
            "CandidateCollection"
        )
    selected = resolved.value
    candidate_reference = next(iter(candidate_references))
    if resolved_selectors:
        observation_selectors = tuple(
            ObservationSelectorEvidence(
                selector_id=selector.selector_id,
                candidate_input=selector.candidate_input,
                score_collection_input=selector.score_collection_input,
                source_partition=selector.source_partition,
                metric=selector.metric,
                method=selector.method,
                context_selector=_context_selector_evidence(
                    selector.context_selector
                ),
                match_cardinality=selector.match_cardinality,
                missing_policy=selector.missing_policy,
            )
            for selector in observation_selector_provenance_from_facts(
                resolved_selectors
            )
        )
        objectives: tuple[SelectionObjectiveEvidence, ...] = ()
    else:
        provenance = selection_objective_provenance_from_facts(
            resolved_objectives
        )
        objectives = tuple(
            SelectionObjectiveEvidence(
                objective_id=objective.objective_id,
                candidate_input=objective.candidate_input,
                score_collection_input=objective.score_collection_input,
                source_partition=objective.source_partition,
                metric=objective.metric,
                method=objective.method,
                context_selector=_context_selector_evidence(
                    objective.context_selector
                ),
                utility_transform=objective.utility_transform,
                utility_parameters=dict(objective.utility_parameters),
                declared_weight=objective.declared_weight,
                effective_weight=objective.effective_weight,
                match_cardinality=objective.match_cardinality,
                missing_policy=objective.missing_policy,
            )
            for objective in provenance.objectives
        )
        observation_selectors = ()
    return SelectionResult(
        selection_node_id=node.node_id,
        selection_method=_exact_reference(node.method),
        candidate_input=candidate_reference,
        selected_collection_id=selected.collection_id,
        selected_candidate_ids=tuple(
            candidate.candidate_id for candidate in selected.items
        ),
        objectives=objectives,
        observation_selectors=observation_selectors,
    )
