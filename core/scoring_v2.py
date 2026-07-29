"""Typed intrinsic Observations and explicit Utility-based selection."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
import math
from types import MappingProxyType
from typing import Any

from core.parameter_contract import (
    parameter_contract_violation,
    parameter_value_contract,
)
from core.port_types import (
    CatalogBuildError,
    FrozenCatalog,
    PortValueError,
    canonical_json_bytes,
)
from datatypes import (
    CandidateCollection,
    ExactContractReference,
    IntrinsicObservationContext,
    Score,
    ScoreCollection,
    ScoreObservation,
)


class SelectionError(ValueError):
    """An intrinsic Selection Objective is unsafe or unsatisfied."""


def _freeze_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        if not all(isinstance(name, str) for name in value):
            raise CatalogBuildError("JSON object keys must be strings")
        return MappingProxyType(
            {name: _freeze_json(item) for name, item in value.items()}
        )
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_json(item) for item in value)
    canonical_json_bytes(value)
    return value


def _thaw_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {name: _thaw_json(item) for name, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw_json(item) for item in value]
    return value


@dataclass(frozen=True, slots=True)
class SelectionInput:
    """One exact Workflow Node output consumed by an objective."""

    node_id: str
    output_port: str

    @classmethod
    def from_public(cls, value: Mapping[str, Any]) -> SelectionInput:
        return cls(
            node_id=value["node_id"],
            output_port=value["output_port"],
        )

    def to_public(self) -> dict[str, str]:
        return {
            "node_id": self.node_id,
            "output_port": self.output_port,
        }


@dataclass(frozen=True, slots=True)
class SelectionObjective:
    """One exact Workflow-owned intrinsic preference."""

    objective_id: str
    candidate_input: SelectionInput
    score_collection_input: SelectionInput
    metric: ExactContractReference
    method: ExactContractReference
    context_selector: IntrinsicObservationContext
    utility_transform: ExactContractReference
    utility_parameters: Mapping[str, Any]
    weight: float
    match_cardinality: str = "exactly_one"
    missing_policy: str = "error"

    def __post_init__(self) -> None:
        if (
            isinstance(self.weight, bool)
            or not isinstance(self.weight, (int, float))
            or not math.isfinite(self.weight)
            or self.weight < 0
            or (
                self.weight == 0
                and math.copysign(1.0, self.weight) < 0
            )
        ):
            raise SelectionError(
                "Selection Objective weight must be finite and non-negative"
            )
        if self.context_selector != IntrinsicObservationContext():
            raise SelectionError(
                "Ticket 10 Selection Objectives require intrinsic Context"
            )
        if self.match_cardinality != "exactly_one":
            raise SelectionError(
                "Intrinsic Selection Objective match cardinality must be "
                "exactly_one"
            )
        if self.missing_policy != "error":
            raise SelectionError(
                "Intrinsic Selection Objective missing policy must be error"
            )
        if not isinstance(self.utility_parameters, Mapping):
            raise SelectionError("Utility parameters must be an object")
        try:
            frozen_parameters = _freeze_json(self.utility_parameters)
        except CatalogBuildError as error:
            raise SelectionError(
                "Utility parameters must contain canonical I-JSON values"
            ) from error
        object.__setattr__(self, "utility_parameters", frozen_parameters)

    @classmethod
    def from_public(
        cls,
        value: Mapping[str, Any],
    ) -> SelectionObjective:
        def reference(name: str) -> ExactContractReference:
            raw = value[name]
            return ExactContractReference(
                contract_kind=raw["contract_kind"],
                contract_id=raw["contract_id"],
                contract_version=raw["contract_version"],
                contract_digest=raw["contract_digest"],
            )

        return cls(
            objective_id=value["objective_id"],
            candidate_input=SelectionInput.from_public(
                value["candidate_input"]
            ),
            score_collection_input=SelectionInput.from_public(
                value["score_collection_input"]
            ),
            metric=reference("metric"),
            method=reference("method"),
            context_selector=IntrinsicObservationContext(
                value["context_selector"]["kind"]
            ),
            utility_transform=reference("utility_transform"),
            utility_parameters=value["utility_parameters"],
            weight=value["weight"],
            match_cardinality=value["match_cardinality"],
            missing_policy=value["missing_policy"],
        )

    def to_public(self) -> dict[str, Any]:
        return {
            "objective_id": self.objective_id,
            "candidate_input": self.candidate_input.to_public(),
            "score_collection_input": (
                self.score_collection_input.to_public()
            ),
            "metric": _reference_public("metric", self.metric),
            "method": _reference_public("method", self.method),
            "context_selector": self.context_selector.to_public(),
            "utility_transform": _reference_public(
                "utility_transform",
                self.utility_transform,
            ),
            "utility_parameters": _thaw_json(self.utility_parameters),
            "weight": self.weight,
            "match_cardinality": self.match_cardinality,
            "missing_policy": self.missing_policy,
        }


@dataclass(frozen=True, slots=True)
class SelectionResult:
    """Ranked Candidates plus the effective objective provenance."""

    candidates: CandidateCollection
    provenance: Mapping[str, Any] = field(compare=False)


def _reference_public(
    contract_kind: str,
    reference: ExactContractReference,
) -> dict[str, str]:
    if reference.contract_kind != contract_kind:
        raise SelectionError(
            f"Expected {contract_kind} reference, received "
            f"{reference.contract_kind}"
        )
    return {
        "contract_kind": reference.contract_kind,
        "contract_id": reference.contract_id,
        "contract_version": reference.contract_version,
        "contract_digest": reference.contract_digest,
    }


def _require_exact_contract(
    catalog: FrozenCatalog,
    contract_kind: str,
    reference: ExactContractReference,
) -> Any:
    if reference.contract_kind != contract_kind:
        raise SelectionError(
            f"Expected {contract_kind} reference, received "
            f"{reference.contract_kind}"
        )
    try:
        contract = catalog.require_contract(
            contract_kind,
            reference.contract_id,
            reference.contract_version,
        )
    except CatalogBuildError as error:
        raise SelectionError(
            f"Unknown {contract_kind} {reference.contract_id}@"
            f"{reference.contract_version}"
        ) from error
    if contract.contract_digest != reference.contract_digest:
        raise SelectionError(
            f"{contract_kind} contract digest does not match the Catalog"
        )
    return contract


def _resolved_utility_parameters(
    declaration: Mapping[str, Any],
    supplied: Mapping[str, Any],
) -> dict[str, Any]:
    unknown = sorted(set(supplied) - set(declaration))
    if unknown:
        raise SelectionError(
            f"Utility parameters contain undeclared names: {unknown}"
        )
    resolved: dict[str, Any] = {}
    for name, contract in declaration.items():
        if not isinstance(contract, Mapping):
            raise SelectionError(
                f"Utility parameter declaration {name!r} is malformed"
            )
        if name in supplied:
            resolved[name] = _thaw_json(supplied[name])
        elif "default" in contract:
            resolved[name] = _thaw_json(contract["default"])
        elif contract.get("required") is True:
            raise SelectionError(f"Utility parameter {name!r} is required")
        else:
            continue
        violation = parameter_contract_violation(
            resolved[name],
            parameter_value_contract(contract),
            path=(name,),
        )
        if violation is not None:
            _, reason = violation
            raise SelectionError(
                f"Utility parameter {name!r} {reason}"
            )
    return resolved


def resolve_selection_objective(
    objective: SelectionObjective,
    catalog: FrozenCatalog,
) -> tuple[Any, Any, Any, dict[str, Any]]:
    metric = _require_exact_contract(catalog, "metric", objective.metric)
    method = _require_exact_contract(catalog, "method", objective.method)
    utility = _require_exact_contract(
        catalog,
        "utility_transform",
        objective.utility_transform,
    )
    compatible = utility.descriptor.get("compatible_input_contract")
    if not isinstance(compatible, Mapping):
        raise SelectionError(
            "Utility Transform compatible input contract is malformed"
        )
    expected = {
        "metric": metric.reference(),
        "method": method.reference(),
        "context_profile": objective.context_selector.to_public(),
    }
    if any(compatible.get(name) != value for name, value in expected.items()):
        raise SelectionError(
            "Utility Transform is incompatible with the exact Metric, "
            "Method, or Context"
        )
    parameter_declaration = utility.descriptor.get("parameters")
    if not isinstance(parameter_declaration, Mapping):
        raise SelectionError("Utility Transform parameter contract is malformed")
    parameters = _resolved_utility_parameters(
        parameter_declaration,
        objective.utility_parameters,
    )
    return metric, method, utility, parameters


def _validate_metric_value(metric: Any, value: object) -> None:
    shape = metric.descriptor.get("value_shape")
    if shape == "scalar":
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
        ):
            raise SelectionError("Scalar Metric value must be finite numeric")
    else:
        raise SelectionError(
            f"Selection does not support Metric value shape {shape!r}"
        )
    canonical_range = metric.descriptor.get("canonical_range")
    if not isinstance(canonical_range, Mapping):
        raise SelectionError("Metric canonical range is malformed")
    minimum = canonical_range.get("minimum")
    maximum = canonical_range.get("maximum")
    if (
        not isinstance(minimum, (int, float))
        or isinstance(minimum, bool)
        or not isinstance(maximum, (int, float))
        or isinstance(maximum, bool)
        or value < minimum
        or value > maximum
    ):
        raise SelectionError("Metric value is outside its canonical range")


def _deduplicated_observations(
    collection: ScoreCollection,
) -> tuple[ScoreObservation, ...]:
    observations: dict[tuple[object, ...], ScoreObservation] = {}
    encoded_values: dict[tuple[object, ...], bytes] = {}
    for entry in collection.entries:
        if isinstance(entry, Score):
            raise SelectionError(
                "Selection rejects ambiguous legacy score_id entries"
            )
        if not isinstance(entry, ScoreObservation):
            raise SelectionError("Score Collection contains an unknown entry")
        try:
            encoded = canonical_json_bytes(entry.value)
        except CatalogBuildError as error:
            raise SelectionError(
                "Observation value must be canonical I-JSON"
            ) from error
        existing = encoded_values.get(entry.identity)
        if existing is not None:
            if existing != encoded:
                raise SelectionError(
                    "Score Collection contains conflicting values for one "
                    "Observation identity"
                )
            continue
        encoded_values[entry.identity] = encoded
        observations[entry.identity] = entry
    return tuple(observations.values())


def select_candidates(
    *,
    candidate_inputs: Mapping[SelectionInput, CandidateCollection],
    score_collection_inputs: Mapping[SelectionInput, ScoreCollection],
    objectives: Sequence[SelectionObjective],
    catalog: FrozenCatalog,
    limit: int,
) -> SelectionResult:
    """Rank Candidates using only exact registered dimensionless Utilities."""
    objective_tuple = tuple(objectives)
    if not objective_tuple:
        raise SelectionError("Selection requires at least one objective")
    objective_ids = [objective.objective_id for objective in objective_tuple]
    if len(objective_ids) != len(set(objective_ids)):
        raise SelectionError("Selection Objective IDs must be unique")
    if type(limit) is not int or limit < 1:
        raise SelectionError("Selection limit must be a positive integer")
    declared_total = sum(objective.weight for objective in objective_tuple)
    if declared_total <= 0:
        raise SelectionError(
            "Selection requires at least one positive objective weight"
        )
    candidate_references = {
        objective.candidate_input for objective in objective_tuple
    }
    if len(candidate_references) != 1:
        raise SelectionError(
            "Weighted objectives must use one exact Candidate input"
        )
    candidate_reference = next(iter(candidate_references))
    try:
        candidates = candidate_inputs[candidate_reference]
    except KeyError as error:
        raise SelectionError("Selection Candidate input is missing") from error
    candidate_ids = [candidate.candidate_id for candidate in candidates.items]
    if len(candidate_ids) != len(set(candidate_ids)):
        raise SelectionError("Selection Candidate input has duplicate identities")

    resolved: list[tuple[SelectionObjective, Any, Any, Any, dict[str, Any]]] = []
    provenance: list[dict[str, Any]] = []
    for objective in objective_tuple:
        metric, method, utility, parameters = resolve_selection_objective(
            objective,
            catalog,
        )
        effective_weight = objective.weight / declared_total
        resolved.append(
            (objective, metric, method, utility, parameters)
        )
        provenance.append(
            {
                "objective_id": objective.objective_id,
                "metric": metric.reference(),
                "method": method.reference(),
                "context_selector": (
                    objective.context_selector.to_public()
                ),
                "utility_transform": utility.reference(),
                "utility_parameters": parameters,
                "declared_weight": objective.weight,
                "effective_weight": effective_weight,
                "match_cardinality": objective.match_cardinality,
                "missing_policy": objective.missing_policy,
            }
        )

    weighted_values = {candidate_id: 0.0 for candidate_id in candidate_ids}
    for objective, metric, method, _, parameters in resolved:
        try:
            collection = score_collection_inputs[
                objective.score_collection_input
            ]
        except KeyError as error:
            raise SelectionError(
                f"Objective {objective.objective_id!r} Score Collection "
                "input is missing"
            ) from error
        observations = _deduplicated_observations(collection)
        runtime = catalog.require_utility_transform(
            objective.utility_transform.contract_id,
            objective.utility_transform.contract_version,
        )
        for candidate_id in candidate_ids:
            matches = [
                observation
                for observation in observations
                if observation.candidate_id == candidate_id
                and observation.metric == objective.metric
                and observation.method == objective.method
                and observation.context == objective.context_selector
            ]
            if not matches:
                raise SelectionError(
                    f"Objective {objective.objective_id!r} has a missing "
                    f"observation for Candidate {candidate_id!r}"
                )
            if len(matches) != 1:
                raise SelectionError(
                    f"Objective {objective.objective_id!r} requires exactly "
                    "one observation per Candidate"
                )
            observation = matches[0]
            _validate_metric_value(metric, observation.value)
            try:
                output = runtime(observation.value, parameters)
            except Exception as error:
                raise SelectionError(
                    "Utility Transform failed without publishing a selection"
                ) from error
            if (
                isinstance(output, bool)
                or not isinstance(output, (int, float))
                or not math.isfinite(output)
                or not 0 <= output <= 1
            ):
                raise SelectionError(
                    "Utility Transform output must be finite and within [0, 1]"
                )
            weighted_values[candidate_id] += (
                float(output) * objective.weight / declared_total
            )

    input_order = {
        candidate_id: index for index, candidate_id in enumerate(candidate_ids)
    }
    ranked = sorted(
        candidates.items,
        key=lambda candidate: (
            -weighted_values[candidate.candidate_id],
            input_order[candidate.candidate_id],
        ),
    )
    selected = ranked[: min(limit, len(ranked))]
    return SelectionResult(
        CandidateCollection(
            collection_id=f"{candidates.collection_id}.selected",
            item_type=candidates.item_type,
            items=list(selected),
        ),
        MappingProxyType({"objectives": provenance}),
    )


def validate_produced_score_collection(
    *,
    catalog: FrozenCatalog,
    binding: Any,
    output_port: str,
    collection: ScoreCollection,
    expected_candidate_ids: Sequence[str] = (),
) -> None:
    """Validate one scoring Binding output against its closed declaration."""
    declarations = [
        declaration
        for declaration in binding.descriptor.get(
            "produced_observations",
            (),
        )
        if declaration.get("output_port") == output_port
    ]
    if not declarations:
        if any(isinstance(item, ScoreObservation) for item in collection.entries):
            raise PortValueError(
                "Binding emitted an undeclared typed Score Observation"
            )
        return
    if any(isinstance(item, Score) for item in collection.entries):
        raise PortValueError(
            "Binding with Produced Observations cannot emit legacy score_id"
        )
    try:
        observations = _deduplicated_observations(collection)
    except (CatalogBuildError, SelectionError) as error:
        raise PortValueError(str(error)) from error
    method_reference = binding.descriptor.get("method")
    for observation in observations:
        try:
            observed_method = _reference_public(
                "method",
                observation.method,
            )
        except SelectionError as error:
            raise PortValueError(str(error)) from error
        if observed_method != method_reference:
            raise PortValueError(
                "Binding emitted an Observation with an undeclared Method"
            )
        try:
            observed_metric = _reference_public(
                "metric",
                observation.metric,
            )
        except SelectionError as error:
            raise PortValueError(str(error)) from error
        matches = [
            declaration
            for declaration in declarations
            if declaration.get("metric") == observed_metric
            and declaration.get("context_profile")
            == observation.context.to_public()
            and declaration.get("subject_grain") == "candidate"
            and declaration.get("source_role") == "subject"
        ]
        if len(matches) != 1:
            raise PortValueError(
                "Binding emitted an Observation outside its closed Produced "
                "Observation Interface"
            )
        try:
            metric = _require_exact_contract(
                catalog,
                "metric",
                observation.metric,
            )
            _validate_metric_value(metric, observation.value)
        except SelectionError as error:
            raise PortValueError(str(error)) from error

    subject_ids = tuple(dict.fromkeys(expected_candidate_ids))
    if not subject_ids:
        subject_ids = tuple(
            dict.fromkeys(
                observation.candidate_id for observation in observations
            )
        )
    for declaration in declarations:
        for candidate_id in subject_ids:
            matches = [
                observation
                for observation in observations
                if observation.candidate_id == candidate_id
                and _reference_public("metric", observation.metric)
                == declaration.get("metric")
                and observation.context.to_public()
                == declaration.get("context_profile")
            ]
            multiplicity = declaration.get("guaranteed_multiplicity")
            if multiplicity == "one" and len(matches) != 1:
                raise PortValueError(
                    "Binding violated guaranteed one Observation per subject"
                )
            if multiplicity == "one_or_more" and not matches:
                raise PortValueError(
                    "Binding violated guaranteed one-or-more Observations"
                )
