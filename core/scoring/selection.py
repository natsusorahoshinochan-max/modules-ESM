"""Typed Selection interface over compiler-resolved scientific facts."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
import math
from types import MappingProxyType
from typing import Any, TypeAlias

from core.parameters.model import AdmittedParameterValues
from core.catalog.port_contract import (
    canonical_json_bytes,
)
from datatypes.candidate import (
    CandidateCollection,
    CandidateDataReference,
)
from datatypes.exact_reference import ExactContractReference
from datatypes.i_json import freeze_i_json, i_json_values_equal, thaw_i_json
from datatypes.observation import (
    CalibrationObservationContext,
    IntrinsicObservationContext,
    PairwiseObservationContext,
    ScoreCollection,
    ScoreObservation,
)


class SelectionError(ValueError):
    """A Selection Objective is scientifically unsatisfied."""


@dataclass(frozen=True, slots=True)
class SelectionInput:
    """One exact Workflow Node output consumed by Selection."""

    node_id: str
    output_port: str

@dataclass(frozen=True, slots=True)
class PairwiseContextSelector:
    """Canonical static profile for a runtime-resolved pairwise Context."""

    pairing_mode: str
    normalization: str
    subject_role: str = "subject"
    reference_role: str = "reference"
    kind: str = "pairwise"

    def __post_init__(self) -> None:
        if self.kind != "pairwise":
            raise SelectionError("Pairwise Context selector kind must be pairwise")
        if self.subject_role != "subject":
            raise SelectionError(
                "Pairwise Context selector subject role must be subject"
            )
        if self.reference_role != "reference":
            raise SelectionError(
                "Pairwise Context selector reference role must be reference"
            )
        if self.pairing_mode not in {
            "fixed_reference",
            "per_subject_counterpart",
        }:
            raise SelectionError(
                "Pairwise Context selector uses an unknown pairing mode"
            )
        if not self.normalization:
            raise SelectionError(
                "Pairwise Context selector requires exact normalization"
            )

ContextSelector: TypeAlias = (
    IntrinsicObservationContext
    | CalibrationObservationContext
    | PairwiseContextSelector
)


@dataclass(frozen=True, slots=True)
class ObservationSelector:
    """One exact raw Observation source consumed without Utility."""

    selector_id: str
    candidate_input: SelectionInput
    score_collection_input: SelectionInput
    metric: ExactContractReference
    method: ExactContractReference
    context_selector: ContextSelector
    source_partition: str
    match_cardinality: str = "exactly_one"
    missing_policy: str = "error"

    def __post_init__(self) -> None:
        if not self.source_partition:
            raise SelectionError(
                "Observation Selector requires an exact source partition"
            )
        if self.match_cardinality != "exactly_one":
            raise SelectionError(
                "Observation Selector match cardinality must be exactly_one"
            )
        if self.missing_policy != "error":
            raise SelectionError(
                "Observation Selector missing policy must be error"
            )

@dataclass(frozen=True, slots=True)
class SelectionObjective:
    """One exact Workflow-owned preference."""

    objective_id: str
    candidate_input: SelectionInput
    score_collection_input: SelectionInput
    metric: ExactContractReference
    method: ExactContractReference
    context_selector: ContextSelector
    utility_transform: ExactContractReference
    utility_parameters: Mapping[str, Any]
    weight: float
    source_partition: str
    match_cardinality: str = "exactly_one"
    missing_policy: str = "error"

    def __post_init__(self) -> None:
        try:
            numeric_weight = float(self.weight)
        except OverflowError:
            numeric_weight = math.inf
        if not math.isfinite(numeric_weight) or numeric_weight <= 0:
            raise SelectionError(
                "Selection Objective weight must be finite and strictly positive"
            )
        if not self.source_partition:
            raise SelectionError(
                "Selection Objective requires an exact source partition"
            )
        if self.match_cardinality != "exactly_one":
            raise SelectionError(
                "Selection Objective match cardinality must be exactly_one"
            )
        if self.missing_policy != "error":
            raise SelectionError(
                "Selection Objective missing policy must be error"
            )
        frozen_parameters = freeze_i_json(self.utility_parameters)
        canonical_json_bytes(frozen_parameters)
        object.__setattr__(self, "utility_parameters", frozen_parameters)

@dataclass(frozen=True, slots=True)
class ResolvedUtilityTransform:
    """One compiler-resolved exact Utility Transform and admitted parameters."""

    reference: ExactContractReference
    parameters: AdmittedParameterValues
    apply: Callable[[Any, Mapping[str, Any]], Any] = field(
        repr=False,
        compare=False,
    )


@dataclass(frozen=True, slots=True)
class ResolvedSelectionObjective:
    """Selection facts resolved once by the Workflow Compiler."""

    objective_id: str
    candidate_input: SelectionInput
    score_collection_input: SelectionInput
    source_partition: str
    metric: ExactContractReference
    method: ExactContractReference
    context_selector: ContextSelector
    utility: ResolvedUtilityTransform
    weight: float
    match_cardinality: str
    missing_policy: str


@dataclass(frozen=True, slots=True)
class ResolvedObservationSelector:
    """Raw Observation facts resolved once by the Workflow Compiler."""

    selector_id: str
    candidate_input: SelectionInput
    score_collection_input: SelectionInput
    source_partition: str
    metric: ExactContractReference
    method: ExactContractReference
    context_selector: ContextSelector
    match_cardinality: str
    missing_policy: str


@dataclass(frozen=True, slots=True)
class SelectionObjectiveProvenance:
    """Typed scientific provenance for one effective objective."""

    objective_id: str
    candidate_input: SelectionInput
    score_collection_input: SelectionInput
    source_partition: str
    metric: ExactContractReference
    method: ExactContractReference
    context_selector: ContextSelector
    utility_transform: ExactContractReference
    utility_parameters: AdmittedParameterValues
    declared_weight: float
    effective_weight: float
    match_cardinality: str
    missing_policy: str


@dataclass(frozen=True, slots=True)
class ObservationSelectorProvenance:
    """Typed scientific provenance for one raw Observation selector."""

    selector_id: str
    candidate_input: SelectionInput
    score_collection_input: SelectionInput
    source_partition: str
    metric: ExactContractReference
    method: ExactContractReference
    context_selector: ContextSelector
    match_cardinality: str
    missing_policy: str


@dataclass(frozen=True, slots=True)
class SelectionProvenance:
    """Typed effective provenance for one Selection conclusion."""

    objectives: tuple[SelectionObjectiveProvenance, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "objectives", tuple(self.objectives))


@dataclass(frozen=True, slots=True)
class SelectionObjectiveIdentityFacts:
    """Typed locator-free Result identity facts for one objective."""

    candidate_input_port: str
    score_collection_input_port: str
    source_partition: str
    metric: ExactContractReference
    method: ExactContractReference
    context_selector: ContextSelector
    utility_transform: ExactContractReference
    utility_parameters: AdmittedParameterValues
    declared_weight: float
    effective_weight: float
    match_cardinality: str
    missing_policy: str


@dataclass(frozen=True, slots=True)
class ObservationSelectorIdentityFacts:
    """Typed locator-free Result identity facts for one raw selector."""

    candidate_input_port: str
    score_collection_input_port: str
    source_partition: str
    metric: ExactContractReference
    method: ExactContractReference
    context_selector: ContextSelector
    match_cardinality: str
    missing_policy: str


def _exact_reference_canonical(
    reference: ExactContractReference,
) -> dict[str, str]:
    return {
        "contract_kind": reference.contract_kind,
        "contract_id": reference.contract_id,
        "contract_version": reference.contract_version,
        "contract_digest": reference.contract_digest,
    }


def _identity_reference_canonical(
    reference: ExactContractReference,
) -> dict[str, str]:
    return {
        "contract_kind": reference.contract_kind,
        "contract_id": reference.contract_id,
        "contract_version": reference.contract_version,
    }


def selection_input_canonical(value: SelectionInput) -> dict[str, str]:
    return {"node_id": value.node_id, "output_port": value.output_port}


def context_selector_canonical(value: ContextSelector) -> dict[str, Any]:
    if isinstance(value, IntrinsicObservationContext):
        return {"kind": value.kind}
    if isinstance(value, CalibrationObservationContext):
        return {
            "kind": value.kind,
            "calibration_metric": value.calibration_metric,
            "calibration_value": value.calibration_value,
            "calibration_unit": value.calibration_unit,
            "population_id": value.population_id,
        }
    return {
        "kind": value.kind,
        "subject_role": value.subject_role,
        "reference_role": value.reference_role,
        "pairing_mode": value.pairing_mode,
        "normalization": value.normalization,
    }


def observation_selector_canonical(
    value: ObservationSelector | ObservationSelectorProvenance,
) -> dict[str, Any]:
    return {
        "selector_id": value.selector_id,
        "candidate_input": selection_input_canonical(value.candidate_input),
        "score_collection_input": selection_input_canonical(
            value.score_collection_input
        ),
        "source_partition": value.source_partition,
        "metric": _exact_reference_canonical(value.metric),
        "method": _exact_reference_canonical(value.method),
        "context_selector": context_selector_canonical(value.context_selector),
        "match_cardinality": value.match_cardinality,
        "missing_policy": value.missing_policy,
    }


def selection_objective_canonical(
    value: SelectionObjective,
) -> dict[str, Any]:
    return {
        "objective_id": value.objective_id,
        "candidate_input": selection_input_canonical(value.candidate_input),
        "score_collection_input": selection_input_canonical(
            value.score_collection_input
        ),
        "source_partition": value.source_partition,
        "metric": _exact_reference_canonical(value.metric),
        "method": _exact_reference_canonical(value.method),
        "context_selector": context_selector_canonical(value.context_selector),
        "utility_transform": _exact_reference_canonical(
            value.utility_transform
        ),
        "utility_parameters": thaw_i_json(value.utility_parameters),
        "weight": value.weight,
        "match_cardinality": value.match_cardinality,
        "missing_policy": value.missing_policy,
    }


def objective_provenance_canonical(
    value: SelectionObjectiveProvenance,
) -> dict[str, Any]:
    return {
        "objective_id": value.objective_id,
        "candidate_input": selection_input_canonical(value.candidate_input),
        "score_collection_input": selection_input_canonical(
            value.score_collection_input
        ),
        "source_partition": value.source_partition,
        "metric": _exact_reference_canonical(value.metric),
        "method": _exact_reference_canonical(value.method),
        "context_selector": context_selector_canonical(value.context_selector),
        "utility_transform": _exact_reference_canonical(
            value.utility_transform
        ),
        "utility_parameters": thaw_i_json(value.utility_parameters),
        "declared_weight": value.declared_weight,
        "effective_weight": value.effective_weight,
        "match_cardinality": value.match_cardinality,
        "missing_policy": value.missing_policy,
    }


def selection_provenance_canonical(
    value: SelectionProvenance,
) -> dict[str, Any]:
    return {
        "objectives": [
            objective_provenance_canonical(objective)
            for objective in value.objectives
        ]
    }


def selection_objective_identity_canonical(
    fact: SelectionObjectiveIdentityFacts,
) -> dict[str, Any]:
    return {
        "candidate_input_port": fact.candidate_input_port,
        "score_collection_input_port": fact.score_collection_input_port,
        "source_partition": fact.source_partition,
        "metric": _identity_reference_canonical(fact.metric),
        "method": _identity_reference_canonical(fact.method),
        "context_selector": context_selector_canonical(
            fact.context_selector
        ),
        "utility_transform": _identity_reference_canonical(
            fact.utility_transform
        ),
        "utility_parameters": thaw_i_json(fact.utility_parameters),
        "declared_weight": fact.declared_weight,
        "effective_weight": fact.effective_weight,
        "match_cardinality": fact.match_cardinality,
        "missing_policy": fact.missing_policy,
    }


def observation_selector_identity_canonical(
    fact: ObservationSelectorIdentityFacts,
) -> dict[str, Any]:
    return {
        "candidate_input_port": fact.candidate_input_port,
        "score_collection_input_port": fact.score_collection_input_port,
        "source_partition": fact.source_partition,
        "metric": _identity_reference_canonical(fact.metric),
        "method": _identity_reference_canonical(fact.method),
        "context_selector": context_selector_canonical(
            fact.context_selector
        ),
        "match_cardinality": fact.match_cardinality,
        "missing_policy": fact.missing_policy,
    }


@dataclass(frozen=True, slots=True)
class SelectionResult:
    """Ranked Candidates plus the effective objective provenance."""

    candidates: CandidateCollection
    provenance: SelectionProvenance = field(compare=False)


@dataclass(frozen=True, slots=True)
class CandidateUtilityProfile:
    """Exact dimensionless Utility vector for every Candidate."""

    candidates: CandidateCollection
    objective_ids: tuple[str, ...]
    utilities: Mapping[str, tuple[float, ...]]
    effective_weights: tuple[float, ...]
    provenance: SelectionProvenance


def _context_matches_selector(context: object, selector: ContextSelector) -> bool:
    if isinstance(
        selector,
        (IntrinsicObservationContext, CalibrationObservationContext),
    ):
        return context == selector
    return (
        isinstance(context, PairwiseObservationContext)
        and context.kind == selector.kind
        and context.subject.role == selector.subject_role
        and context.reference.role == selector.reference_role
        and context.pairing_mode == selector.pairing_mode
        and context.normalization == selector.normalization
    )


SelectionSource: TypeAlias = ResolvedSelectionObjective | ResolvedObservationSelector


def resolve_objective_observations(
    *,
    candidates: CandidateCollection,
    collection: ScoreCollection,
    objective: SelectionSource,
    out_of_scope_policy: str,
    duplicate_policy: str,
) -> Mapping[str, ScoreObservation]:
    """Resolve one exact runtime Observation per Candidate."""
    candidate_ids = [candidate.candidate_id for candidate in candidates.items]
    candidate_set = set(candidate_ids)
    seen: dict[tuple[object, ...], object] = {}
    matched: dict[str, list[ScoreObservation]] = {
        candidate_id: [] for candidate_id in candidate_ids
    }
    for entry in collection.entries:
        in_scope = (
            entry.candidate_id in candidate_set
            and entry.source_partition == objective.source_partition
            and entry.metric == objective.metric
            and entry.method == objective.method
            and _context_matches_selector(entry.context, objective.context_selector)
        )
        if not in_scope:
            if out_of_scope_policy == "error":
                raise SelectionError(
                    "selection received an out-of-scope observation"
                )
            continue
        if entry.identity in seen:
            if not i_json_values_equal(seen[entry.identity], entry.value):
                raise SelectionError(
                    "selection has a conflicting observation identity"
                )
            if duplicate_policy == "error":
                raise SelectionError(
                    "selection has a duplicate observation identity"
                )
            continue
        seen[entry.identity] = entry.value
        matched[entry.candidate_id].append(entry)
    resolved: dict[str, ScoreObservation] = {}
    selection_id = (
        objective.objective_id
        if isinstance(objective, ResolvedSelectionObjective)
        else objective.selector_id
    )
    for candidate_id in candidate_ids:
        matches = matched[candidate_id]
        if not matches:
            raise SelectionError(
                f"Selector {selection_id!r} has a missing observation for "
                f"Candidate {candidate_id!r}"
            )
        if len(matches) != 1:
            raise SelectionError(
                f"Selector {selection_id!r} requires exactly one observation "
                "per Candidate"
            )
        resolved[candidate_id] = matches[0]
    return MappingProxyType(resolved)


def _resolved_objective_contracts(
    objectives: Sequence[ResolvedSelectionObjective],
) -> tuple[
    tuple[ResolvedSelectionObjective, ...],
    float,
    tuple[SelectionObjectiveProvenance, ...],
]:
    resolved = tuple(objectives)
    try:
        declared_total = math.fsum(float(item.weight) for item in resolved)
    except OverflowError:
        declared_total = math.inf
    if not math.isfinite(declared_total) or declared_total <= 0:
        raise SelectionError(
            "Selection requires a finite positive total objective weight"
        )
    provenance = tuple(
        SelectionObjectiveProvenance(
            objective_id=item.objective_id,
            candidate_input=item.candidate_input,
            score_collection_input=item.score_collection_input,
            source_partition=item.source_partition,
            metric=item.metric,
            method=item.method,
            context_selector=item.context_selector,
            utility_transform=item.utility.reference,
            utility_parameters=item.utility.parameters,
            declared_weight=item.weight,
            effective_weight=float(item.weight) / declared_total,
            match_cardinality=item.match_cardinality,
            missing_policy=item.missing_policy,
        )
        for item in resolved
    )
    return resolved, declared_total, provenance


def selection_objective_provenance_from_facts(
    objectives: Sequence[ResolvedSelectionObjective],
) -> SelectionProvenance:
    """Return typed provenance from compile-resolved objectives."""
    _, _, provenance = _resolved_objective_contracts(objectives)
    return SelectionProvenance(provenance)


def observation_selector_provenance_from_facts(
    selectors: Sequence[ResolvedObservationSelector],
) -> tuple[ObservationSelectorProvenance, ...]:
    """Return typed provenance from compile-resolved selectors."""
    return tuple(
        ObservationSelectorProvenance(
            selector_id=item.selector_id,
            candidate_input=item.candidate_input,
            score_collection_input=item.score_collection_input,
            source_partition=item.source_partition,
            metric=item.metric,
            method=item.method,
            context_selector=item.context_selector,
            match_cardinality=item.match_cardinality,
            missing_policy=item.missing_policy,
        )
        for item in selectors
    )


def selection_objective_identity_facts_from_facts(
    objectives: Sequence[ResolvedSelectionObjective],
    *,
    candidate_input_port: str,
    score_collection_input_port: str,
) -> tuple[SelectionObjectiveIdentityFacts, ...]:
    """Project locator-free scientific facts for Result/output identity."""
    resolved, _, provenance = _resolved_objective_contracts(objectives)
    return tuple(
        SelectionObjectiveIdentityFacts(
            candidate_input_port=candidate_input_port,
            score_collection_input_port=score_collection_input_port,
            source_partition=item.source_partition,
            metric=item.metric,
            method=item.method,
            context_selector=item.context_selector,
            utility_transform=item.utility.reference,
            utility_parameters=fact.utility_parameters,
            declared_weight=fact.declared_weight,
            effective_weight=fact.effective_weight,
            match_cardinality=item.match_cardinality,
            missing_policy=item.missing_policy,
        )
        for item, fact in zip(resolved, provenance, strict=True)
    )


def observation_selector_identity_facts_from_facts(
    selectors: Sequence[ResolvedObservationSelector],
    *,
    candidate_input_port: str,
    score_collection_input_port: str,
) -> tuple[ObservationSelectorIdentityFacts, ...]:
    """Project locator-free raw-observation facts for Result identity."""
    return tuple(
        ObservationSelectorIdentityFacts(
            candidate_input_port=candidate_input_port,
            score_collection_input_port=score_collection_input_port,
            source_partition=item.source_partition,
            metric=item.metric,
            method=item.method,
            context_selector=item.context_selector,
            match_cardinality=item.match_cardinality,
            missing_policy=item.missing_policy,
        )
        for item in selectors
    )


def resolve_candidate_utilities_from_facts(
    *,
    candidate_inputs: Mapping[SelectionInput, CandidateCollection],
    score_collection_inputs: Mapping[SelectionInput, ScoreCollection],
    objectives: Sequence[ResolvedSelectionObjective],
    candidate_data_references: Mapping[str, CandidateDataReference],
) -> CandidateUtilityProfile:
    """Compute Utilities from compiler-resolved scientific facts only."""
    resolved, declared_total, provenance = _resolved_objective_contracts(
        objectives
    )
    candidates = candidate_inputs[resolved[0].candidate_input]
    candidate_ids = [candidate.candidate_id for candidate in candidates.items]
    utility_values = {candidate_id: [] for candidate_id in candidate_ids}
    for item in resolved:
        collection = score_collection_inputs[item.score_collection_input]
        observations = resolve_objective_observations(
            candidates=candidates,
            collection=collection,
            objective=item,
            out_of_scope_policy="ignore",
            duplicate_policy="deduplicate_identical",
        )
        for candidate_id in candidate_ids:
            observation = observations[candidate_id]
            expected_subject = candidate_data_references[candidate_id]
            if observation.subject != expected_subject:
                raise SelectionError(
                    "Observation subject does not match the exact Candidate input"
                )
            if isinstance(item.context_selector, PairwiseContextSelector):
                context = observation.context
                if context.subject.candidate != expected_subject:
                    raise SelectionError(
                        "Pairwise Context subject identity or content digest "
                        "does not match the exact Candidate input"
                    )
            output = item.utility.apply(observation.value, item.utility.parameters)
            if (
                isinstance(output, bool)
                or not isinstance(output, (int, float))
                or not math.isfinite(output)
                or not 0 <= output <= 1
            ):
                raise SelectionError(
                    "Utility Transform output must be finite and within [0, 1]"
                )
            utility_values[candidate_id].append(float(output))
    return CandidateUtilityProfile(
        candidates=candidates,
        objective_ids=tuple(item.objective_id for item in resolved),
        utilities=MappingProxyType(
            {
                candidate_id: tuple(values)
                for candidate_id, values in utility_values.items()
            }
        ),
        effective_weights=tuple(
            float(item.weight) / declared_total for item in resolved
        ),
        provenance=SelectionProvenance(provenance),
    )


def weighted_utility_totals(
    profile: CandidateUtilityProfile,
) -> Mapping[str, float]:
    """Combine one exact Utility profile with its normalized weights."""
    return MappingProxyType(
        {
            candidate_id: math.fsum(
                utility * weight
                for utility, weight in zip(
                    utilities,
                    profile.effective_weights,
                    strict=True,
                )
            )
            for candidate_id, utilities in profile.utilities.items()
        }
    )


def rank_candidates_by_weighted_utility(
    profile: CandidateUtilityProfile,
) -> tuple[Any, ...]:
    """Order original Candidates by weighted Utility and stable identity."""
    totals = weighted_utility_totals(profile)
    return tuple(
        sorted(
            profile.candidates.items,
            key=lambda candidate: (
                -totals[candidate.candidate_id],
                candidate.candidate_id,
            ),
        )
    )
