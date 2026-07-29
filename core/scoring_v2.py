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
    PairwiseObservationContext,
    ProteinSequence,
    ProteinStructure,
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
class PairwiseContextSelector:
    """Canonical static profile for a runtime-resolved pairwise Context."""

    pairing_mode: str
    normalization: str
    subject_role: str = "subject"
    reference_role: str = "reference"
    kind: str = "pairwise"

    def __post_init__(self) -> None:
        if self.kind != "pairwise":
            raise SelectionError(
                "Pairwise Context selector kind must be pairwise"
            )
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
        if not isinstance(self.normalization, str) or not self.normalization:
            raise SelectionError(
                "Pairwise Context selector requires exact normalization"
            )

    @classmethod
    def from_public(
        cls,
        value: Mapping[str, Any],
    ) -> PairwiseContextSelector:
        return cls(
            pairing_mode=value["pairing_mode"],
            normalization=value["normalization"],
            subject_role=value["subject_role"],
            reference_role=value["reference_role"],
            kind=value["kind"],
        )

    def to_public(self) -> dict[str, str]:
        return {
            "kind": self.kind,
            "subject_role": self.subject_role,
            "reference_role": self.reference_role,
            "pairing_mode": self.pairing_mode,
            "normalization": self.normalization,
        }


@dataclass(frozen=True, slots=True)
class SelectionObjective:
    """One exact Workflow-owned intrinsic preference."""

    objective_id: str
    candidate_input: SelectionInput
    score_collection_input: SelectionInput
    metric: ExactContractReference
    method: ExactContractReference
    context_selector: (
        IntrinsicObservationContext | PairwiseContextSelector
    )
    utility_transform: ExactContractReference
    utility_parameters: Mapping[str, Any]
    weight: float
    source_partition: str = "default"
    match_cardinality: str = "exactly_one"
    missing_policy: str = "error"

    def __post_init__(self) -> None:
        try:
            canonical_json_bytes(self.weight)
            numeric_weight = float(self.weight)
        except (CatalogBuildError, OverflowError, TypeError, ValueError):
            numeric_weight = math.nan
        if (
            isinstance(self.weight, bool)
            or not isinstance(self.weight, (int, float))
            or not math.isfinite(numeric_weight)
            or numeric_weight < 0
            or (
                numeric_weight == 0
                and math.copysign(1.0, numeric_weight) < 0
            )
        ):
            raise SelectionError(
                "Selection Objective weight must be finite and non-negative"
            )
        if not isinstance(
            self.context_selector,
            (IntrinsicObservationContext, PairwiseContextSelector),
        ):
            raise SelectionError(
                "Selection Objective requires a controlled Context selector"
            )
        if (
            not isinstance(self.source_partition, str)
            or not self.source_partition
        ):
            raise SelectionError(
                "Selection Objective requires an exact source partition"
            )
        if self.match_cardinality != "exactly_one":
            raise SelectionError(
                "Selection Objective match cardinality must be exactly_one"
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
            context_selector=(
                IntrinsicObservationContext(
                    value["context_selector"]["kind"]
                )
                if value["context_selector"]["kind"] == "intrinsic"
                else PairwiseContextSelector.from_public(
                    value["context_selector"]
                )
            ),
            utility_transform=reference("utility_transform"),
            utility_parameters=value["utility_parameters"],
            weight=value["weight"],
            source_partition=value.get("source_partition", "default"),
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
            "source_partition": self.source_partition,
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

    def __post_init__(self) -> None:
        if not isinstance(self.provenance, Mapping):
            raise SelectionError("Selection provenance must be an object")
        try:
            frozen_provenance = _freeze_json(self.provenance)
        except CatalogBuildError as error:
            raise SelectionError(
                "Selection provenance must contain canonical I-JSON values"
            ) from error
        object.__setattr__(self, "provenance", frozen_provenance)

    def public_provenance(self) -> dict[str, Any]:
        return _thaw_json(self.provenance)


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
) -> tuple[Any, Any, Any, Mapping[str, Any]]:
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
    return metric, method, utility, _freeze_json(parameters)


def _subject_residue_count(subject: Any) -> int:
    data = subject.data
    if isinstance(data, ProteinSequence):
        return len(data.sequence)
    if isinstance(data, ProteinStructure):
        residue_keys = {
            (line[21:22], line[22:26], line[26:27])
            for line in data.pdb_string.splitlines()
            if line.startswith("ATOM  ") and len(line) >= 27
        }
        if residue_keys:
            return len(residue_keys)
    raise SelectionError(
        "Per-residue Metric requires an exact subject residue layout"
    )


def _validate_metric_value(
    metric: Any,
    value: object,
    *,
    subject: Any | None = None,
) -> None:
    shape = metric.descriptor.get("value_shape")
    validation = metric.descriptor.get("validation_contract")
    if not isinstance(validation, Mapping):
        raise SelectionError("Metric validation contract is malformed")
    if shape == "scalar":
        values = (value,)
    elif shape in {"per_residue", "residue_vector"}:
        if not isinstance(value, (list, tuple)):
            raise SelectionError(
                "Per-residue Metric value must be an ordered array"
            )
        values = tuple(value)
        if subject is None or len(values) != _subject_residue_count(subject):
            raise SelectionError(
                "Per-residue Metric value does not align with its exact "
                "subject residue layout"
            )
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
    ):
        raise SelectionError("Metric canonical range is malformed")
    masking = validation.get("masking")
    allow_null = (
        isinstance(masking, Mapping)
        and masking.get("allow_null") is True
    )
    for item in values:
        if item is None and allow_null:
            continue
        if (
            isinstance(item, bool)
            or not isinstance(item, (int, float))
            or (validation.get("finite") is True and not math.isfinite(item))
        ):
            raise SelectionError(
                "Metric value does not satisfy its validity/masking contract"
            )
        if item < minimum or item > maximum:
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
        partitioned_identity = (entry.source_partition, *entry.identity)
        existing = encoded_values.get(partitioned_identity)
        if existing is not None:
            if existing != encoded:
                raise SelectionError(
                    "Score Collection contains conflicting values for one "
                    "Observation identity"
                )
            continue
        encoded_values[partitioned_identity] = encoded
        observations[partitioned_identity] = entry
    return tuple(observations.values())


def _context_matches_selector(
    context: object,
    selector: object,
) -> bool:
    if isinstance(selector, IntrinsicObservationContext):
        return context == selector
    return (
        isinstance(selector, PairwiseContextSelector)
        and isinstance(context, PairwiseObservationContext)
        and context.kind == selector.kind
        and context.subject.role == selector.subject_role
        and context.reference.role == selector.reference_role
        and context.pairing_mode == selector.pairing_mode
        and context.normalization == selector.normalization
    )


def _context_profile(context: object) -> dict[str, str]:
    if isinstance(context, IntrinsicObservationContext):
        return context.to_public()
    if isinstance(context, PairwiseObservationContext):
        return {
            "kind": context.kind,
            "subject_role": context.subject.role,
            "reference_role": context.reference.role,
            "pairing_mode": context.pairing_mode,
            "normalization": context.normalization,
        }
    raise SelectionError("Observation uses an unknown Context type")


def _candidate_content_digest(
    catalog: FrozenCatalog,
    candidate: Any,
) -> str:
    if isinstance(candidate.data, ProteinSequence):
        type_id = "protein.sequence"
    elif isinstance(candidate.data, ProteinStructure):
        type_id = "protein.structure"
    else:
        raise SelectionError(
            "Pairwise subject must carry a canonical protein value"
        )
    return catalog.require_port_type(type_id, "2.0.0").content_digest(
        candidate.data
    )


def _candidate_values(value: object) -> tuple[Any, ...]:
    if isinstance(value, CandidateCollection):
        return tuple(value.items)
    if (
        isinstance(value, (list, tuple))
        and all(isinstance(item, CandidateCollection) for item in value)
    ):
        return tuple(
            candidate
            for collection in value
            for candidate in collection.items
        )
    raise PortValueError(
        "Binding Produced Observation Candidate source is unavailable"
    )


def _observation_value_map(
    collection: ScoreCollection,
) -> dict[tuple[object, ...], bytes]:
    try:
        observations = _deduplicated_observations(collection)
    except (CatalogBuildError, SelectionError) as error:
        raise PortValueError(str(error)) from error
    result: dict[tuple[object, ...], bytes] = {}
    for observation in observations:
        try:
            encoded = canonical_json_bytes(observation.value)
        except CatalogBuildError as error:
            raise PortValueError(str(error)) from error
        result[
            (observation.source_partition, *observation.identity)
        ] = encoded
    return result


def _observation_matches_propagation_filter(
    observation: ScoreObservation,
    filters: Mapping[str, Any],
) -> bool:
    return (
        (
            filters.get("source_partition") is None
            or observation.source_partition
            == filters["source_partition"]
        )
        and (
            filters.get("metric") is None
            or _reference_public("metric", observation.metric)
            == filters["metric"]
        )
        and (
            filters.get("method") is None
            or _reference_public("method", observation.method)
            == filters["method"]
        )
        and (
            filters.get("context_profile") is None
            or _context_profile(observation.context)
            == filters["context_profile"]
        )
    )


def _validate_propagated_score_collection(
    *,
    propagation: Mapping[str, Any],
    output_port: str,
    collection: ScoreCollection,
    inputs: Mapping[str, Any],
) -> bool:
    if propagation.get("output_port") != output_port:
        return False
    if propagation.get("schema_version") != "2.0.0":
        raise PortValueError(
            "Binding Observation propagation schema version is unsupported"
        )
    mode = propagation.get("mode")
    input_ports = propagation.get("input_ports")
    if (
        mode not in {"pass_through", "union", "filter"}
        or not isinstance(input_ports, (list, tuple))
        or not input_ports
        or (mode in {"pass_through", "filter"} and len(input_ports) != 1)
        or (mode == "union" and len(input_ports) < 2)
    ):
        raise PortValueError(
            "Binding Observation propagation contract is malformed"
        )
    source_maps: list[dict[tuple[object, ...], bytes]] = []
    source_observations: list[ScoreObservation] = []
    for input_port in input_ports:
        source = inputs.get(input_port)
        if not isinstance(source, ScoreCollection):
            raise PortValueError(
                "Binding Observation propagation input is unavailable"
            )
        source_maps.append(_observation_value_map(source))
        source_observations.extend(_deduplicated_observations(source))
    expected: dict[tuple[object, ...], bytes] = {}
    for source_map in source_maps:
        for identity, value in source_map.items():
            existing = expected.get(identity)
            if existing is not None and existing != value:
                raise PortValueError(
                    "Observation propagation sources conflict"
                )
            expected[identity] = value
    observed = _observation_value_map(collection)
    if mode in {"pass_through", "union"}:
        if observed != expected:
            raise PortValueError(
                "Observation propagation cannot omit, invent, or repartition "
                "entries"
            )
        return True
    filters = propagation.get("filter")
    if not isinstance(filters, Mapping):
        raise PortValueError(
            "Filter propagation requires a closed exact filter"
        )
    filtered_entries = [
        observation
        for observation in source_observations
        if _observation_matches_propagation_filter(
            observation,
            filters,
        )
    ]
    filtered_expected = _observation_value_map(
        ScoreCollection(
            collection_id="controlled-filter-expected",
            entries=filtered_entries,
        )
    )
    if observed != filtered_expected:
        raise PortValueError(
            "Observation propagation output is not the exact filter result"
        )
    return True


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
    try:
        declared_total = math.fsum(
            float(objective.weight) for objective in objective_tuple
        )
    except (OverflowError, ValueError):
        declared_total = math.inf
    if not math.isfinite(declared_total) or declared_total <= 0:
        raise SelectionError(
            "Selection requires a finite positive total objective weight"
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
    candidates_by_id = {
        candidate.candidate_id: candidate
        for candidate in candidates.items
    }

    resolved: list[
        tuple[SelectionObjective, Any, Any, Any, Mapping[str, Any]]
    ] = []
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
                "candidate_input": objective.candidate_input.to_public(),
                "score_collection_input": (
                    objective.score_collection_input.to_public()
                ),
                "source_partition": objective.source_partition,
                "metric": metric.reference(),
                "method": method.reference(),
                "context_selector": (
                    objective.context_selector.to_public()
                ),
                "utility_transform": utility.reference(),
                "utility_parameters": _thaw_json(parameters),
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
                and observation.source_partition
                == objective.source_partition
                and observation.metric == objective.metric
                and observation.method == objective.method
                and _context_matches_selector(
                    observation.context,
                    objective.context_selector,
                )
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
            if isinstance(
                objective.context_selector,
                PairwiseContextSelector,
            ):
                context = observation.context
                if not isinstance(context, PairwiseObservationContext):
                    raise SelectionError(
                        "Pairwise objective matched a non-pairwise Context"
                    )
                subject = candidates_by_id[candidate_id]
                if (
                    context.subject.candidate_id != candidate_id
                    or context.subject.content_digest
                    != _candidate_content_digest(catalog, subject)
                ):
                    raise SelectionError(
                        "Pairwise Context subject identity or content digest "
                        "does not match the exact Candidate input"
                    )
            _validate_metric_value(
                metric,
                observation.value,
                subject=candidates_by_id[candidate_id],
            )
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
        _freeze_json({"objectives": provenance}),
    )


def validate_produced_score_collection(
    *,
    catalog: FrozenCatalog,
    binding: Any,
    output_port: str,
    collection: ScoreCollection,
    inputs: Mapping[str, Any],
    outputs: Mapping[str, Any],
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
        propagation = binding.descriptor.get("observation_propagation")
        if isinstance(propagation, Mapping) and (
            _validate_propagated_score_collection(
                propagation=propagation,
                output_port=output_port,
                collection=collection,
                inputs=inputs,
            )
        ):
            return
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
            == _context_profile(observation.context)
            and declaration.get("output_partition", "default")
            == observation.source_partition
            and declaration.get("subject_grain") == "candidate"
            and declaration.get("source_role") == "subject"
        ]
        if len(matches) != 1:
            raise PortValueError(
                "Binding emitted an Observation outside its closed Produced "
                "Observation Interface"
            )
    for declaration in declarations:
        source = (
            inputs
            if declaration.get("subject_direction") == "input"
            else outputs
            if declaration.get("subject_direction") == "output"
            else None
        )
        subject_value = (
            source.get(declaration.get("subject_port"))
            if source is not None
            else None
        )
        subjects = _candidate_values(subject_value)
        subject_ids = tuple(
            candidate.candidate_id for candidate in subjects
        )
        if len(subject_ids) != len(set(subject_ids)):
            raise PortValueError(
                "Binding Produced Observation subject source has duplicates"
            )
        declared_metric = declaration.get("metric")
        declared_context = declaration.get("context_profile")
        declared_partition = declaration.get("output_partition", "default")
        matching_observations = [
            observation
            for observation in observations
            if _reference_public("metric", observation.metric)
            == declared_metric
            and _context_profile(observation.context) == declared_context
            and observation.source_partition == declared_partition
        ]
        ghost_subjects = sorted(
            {
                observation.candidate_id
                for observation in matching_observations
            }
            - set(subject_ids)
        )
        if ghost_subjects:
            raise PortValueError(
                "Binding emitted an Observation outside its declared subject "
                "source"
            )
        if (
            isinstance(declared_context, Mapping)
            and declared_context.get("kind") == "pairwise"
        ):
            reference_identities = {
                (
                    observation.context.reference.candidate_id,
                    observation.context.reference.content_digest,
                )
                for observation in matching_observations
                if isinstance(
                    observation.context,
                    PairwiseObservationContext,
                )
            }
            pairing_mode = declared_context.get("pairing_mode")
            if (
                pairing_mode == "fixed_reference"
                and matching_observations
                and len(reference_identities) != 1
            ):
                raise PortValueError(
                    "fixed-reference pairing requires one exact reference "
                    "Candidate for the whole partition"
                )
            if (
                pairing_mode == "per_subject_counterpart"
                and matching_observations
                and len(reference_identities) != len(matching_observations)
            ):
                raise PortValueError(
                    "per-subject pairing requires one distinct exact "
                    "counterpart per subject"
                )
        for candidate_id in subject_ids:
            matches = [
                observation
                for observation in matching_observations
                if observation.candidate_id == candidate_id
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
            for observation in matches:
                try:
                    metric = _require_exact_contract(
                        catalog,
                        "metric",
                        observation.metric,
                    )
                    subject = next(
                        candidate
                        for candidate in subjects
                        if candidate.candidate_id == candidate_id
                    )
                    _validate_metric_value(
                        metric,
                        observation.value,
                        subject=subject,
                    )
                    if isinstance(
                        observation.context,
                        PairwiseObservationContext,
                    ):
                        context = observation.context
                        if (
                            context.subject.candidate_id
                            != subject.candidate_id
                            or context.subject.content_digest
                            != _candidate_content_digest(catalog, subject)
                        ):
                            raise SelectionError(
                                "Pairwise Context subject source does not "
                                "match the exact Candidate"
                            )
                        reference_source = (
                            inputs
                            if declaration.get("reference_direction")
                            == "input"
                            else outputs
                            if declaration.get("reference_direction")
                            == "output"
                            else None
                        )
                        references = _candidate_values(
                            reference_source.get(
                                declaration.get("reference_port")
                            )
                            if reference_source is not None
                            else None
                        )
                        reference_matches = [
                            candidate
                            for candidate in references
                            if candidate.candidate_id
                            == context.reference.candidate_id
                            and _candidate_content_digest(catalog, candidate)
                            == context.reference.content_digest
                        ]
                        if len(reference_matches) != 1:
                            raise SelectionError(
                                "Pairwise Context reference source does not "
                                "contain one exact Candidate counterpart"
                            )
                except SelectionError as error:
                    raise PortValueError(str(error)) from error
