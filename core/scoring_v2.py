"""Typed Observations and explicit Utility-based selection."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
import math
import struct
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
    CalibrationObservationContext,
    CandidateCollection,
    ExactContractReference,
    IntrinsicObservationContext,
    PairwiseObservationContext,
    PairwiseCandidateMapping,
    ProteinSequence,
    ProteinStructure,
    ScoreCollection,
    ScoreObservation,
)


class SelectionError(ValueError):
    """A Selection Objective is unsafe or unsatisfied."""


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
class ObservationSelector:
    """One exact raw Observation source consumed without Utility."""

    selector_id: str
    candidate_input: SelectionInput
    score_collection_input: SelectionInput
    metric: ExactContractReference
    method: ExactContractReference
    context_selector: (
        IntrinsicObservationContext
        | CalibrationObservationContext
        | PairwiseContextSelector
    )
    source_partition: str = "default"
    match_cardinality: str = "exactly_one"
    missing_policy: str = "error"

    def __post_init__(self) -> None:
        if not isinstance(
            self.context_selector,
            (
                IntrinsicObservationContext,
                CalibrationObservationContext,
                PairwiseContextSelector,
            ),
        ):
            raise SelectionError(
                "Observation Selector requires a controlled Context selector"
            )
        if not isinstance(self.source_partition, str) or not self.source_partition:
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

    @classmethod
    def from_public(cls, value: Mapping[str, Any]) -> ObservationSelector:
        def reference(name: str) -> ExactContractReference:
            raw = value[name]
            return ExactContractReference(
                contract_kind=raw["contract_kind"],
                contract_id=raw["contract_id"],
                contract_version=raw["contract_version"],
                contract_digest=raw["contract_digest"],
            )

        context = value["context_selector"]
        if context["kind"] == "intrinsic":
            context_selector: object = IntrinsicObservationContext(
                context["kind"]
            )
        elif context["kind"] == "calibration":
            context_selector = CalibrationObservationContext(
                calibration_metric=context["calibration_metric"],
                calibration_value=context["calibration_value"],
                calibration_unit=context["calibration_unit"],
                population_id=context["population_id"],
                kind=context["kind"],
            )
        else:
            context_selector = PairwiseContextSelector.from_public(context)
        return cls(
            selector_id=value["selector_id"],
            candidate_input=SelectionInput.from_public(
                value["candidate_input"]
            ),
            score_collection_input=SelectionInput.from_public(
                value["score_collection_input"]
            ),
            metric=reference("metric"),
            method=reference("method"),
            context_selector=context_selector,
            source_partition=value.get("source_partition", "default"),
            match_cardinality=value["match_cardinality"],
            missing_policy=value["missing_policy"],
        )

    def to_public(self) -> dict[str, Any]:
        return {
            "selector_id": self.selector_id,
            "candidate_input": self.candidate_input.to_public(),
            "score_collection_input": self.score_collection_input.to_public(),
            "source_partition": self.source_partition,
            "metric": _reference_public("metric", self.metric),
            "method": _reference_public("method", self.method),
            "context_selector": self.context_selector.to_public(),
            "match_cardinality": self.match_cardinality,
            "missing_policy": self.missing_policy,
        }


@dataclass(frozen=True, slots=True)
class SelectionObjective:
    """One exact Workflow-owned preference."""

    objective_id: str
    candidate_input: SelectionInput
    score_collection_input: SelectionInput
    metric: ExactContractReference
    method: ExactContractReference
    context_selector: (
        IntrinsicObservationContext
        | CalibrationObservationContext
        | PairwiseContextSelector
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
            or numeric_weight <= 0
        ):
            raise SelectionError(
                "Selection Objective weight must be finite and strictly positive"
            )
        if not isinstance(
            self.context_selector,
            (
                IntrinsicObservationContext,
                CalibrationObservationContext,
                PairwiseContextSelector,
            ),
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
                "Selection Objective missing policy must be error"
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
                else (
                    CalibrationObservationContext(
                        calibration_metric=value["context_selector"][
                            "calibration_metric"
                        ],
                        calibration_value=value["context_selector"][
                            "calibration_value"
                        ],
                        calibration_unit=value["context_selector"][
                            "calibration_unit"
                        ],
                        population_id=value["context_selector"][
                            "population_id"
                        ],
                        kind=value["context_selector"]["kind"],
                    )
                    if value["context_selector"]["kind"] == "calibration"
                    else PairwiseContextSelector.from_public(
                        value["context_selector"]
                    )
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


@dataclass(frozen=True, slots=True)
class CandidateUtilityProfile:
    """Exact dimensionless Utility vector for every Candidate."""

    candidates: CandidateCollection
    objective_ids: tuple[str, ...]
    utilities: Mapping[str, tuple[float, ...]]
    effective_weights: tuple[float, ...]
    provenance: Mapping[str, Any]

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


def resolve_observation_selector(
    selector: ObservationSelector,
    catalog: FrozenCatalog,
) -> tuple[Any, Any]:
    """Resolve only the raw Metric and Method named by a selector."""
    metric = _require_exact_contract(catalog, "metric", selector.metric)
    method = _require_exact_contract(catalog, "method", selector.method)
    return metric, method


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
    elif shape == "residue_pair_matrix":
        if not isinstance(value, (list, tuple)):
            raise SelectionError(
                "Residue-pair Metric value must be an ordered matrix"
            )
        residue_count = (
            _subject_residue_count(subject)
            if subject is not None
            else None
        )
        if residue_count is None or len(value) != residue_count:
            raise SelectionError(
                "Residue-pair Metric value does not align with its exact "
                "subject residue layout"
            )
        rows = tuple(value)
        if any(
            not isinstance(row, (list, tuple))
            or len(row) != residue_count
            for row in rows
        ):
            raise SelectionError(
                "Residue-pair Metric value must be a square residue matrix"
            )
        values = tuple(item for row in rows for item in row)
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
    exact_binary32 = (
        validation.get("numeric_format") == "binary32"
        and validation.get("exact_round_trip") is True
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
        if exact_binary32:
            try:
                round_trip = struct.unpack(
                    "!f",
                    struct.pack("!f", float(item)),
                )[0]
            except OverflowError as error:
                raise SelectionError(
                    "Metric value is not exactly representable as binary32"
                ) from error
            if (
                round_trip != item
                or (
                    item == 0
                    and math.copysign(1.0, round_trip)
                    != math.copysign(1.0, item)
                )
            ):
                raise SelectionError(
                    "Metric value is not exactly representable as binary32"
                )


def _deduplicated_observations(
    collection: ScoreCollection,
) -> tuple[ScoreObservation, ...]:
    observations: dict[tuple[object, ...], ScoreObservation] = {}
    encoded_values: dict[tuple[object, ...], bytes] = {}
    for entry in collection.entries:
        if type(entry) is not ScoreObservation:
            raise SelectionError("Score Collection contains an unknown entry")
        try:
            encoded = canonical_json_bytes(entry.value)
        except CatalogBuildError as error:
            raise SelectionError(
                "Observation value must be canonical I-JSON"
            ) from error
        identity = entry.identity
        existing = encoded_values.get(identity)
        if existing is not None:
            if existing != encoded:
                raise SelectionError(
                    "Score Collection contains conflicting values for one "
                    "Observation identity"
                )
            if (
                observations[identity].source_partition
                != entry.source_partition
            ):
                raise SelectionError(
                    "Score Collection contains an Observation identity "
                    "partition collision"
                )
            continue
        encoded_values[identity] = encoded
        observations[identity] = entry
    return tuple(observations.values())


def _context_matches_selector(
    context: object,
    selector: object,
) -> bool:
    if isinstance(
        selector,
        (IntrinsicObservationContext, CalibrationObservationContext),
    ):
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


def resolve_objective_observations(
    *,
    candidates: CandidateCollection,
    collection: ScoreCollection,
    objective: SelectionObjective | ObservationSelector,
    out_of_scope_policy: str = "ignore",
    duplicate_policy: str = "deduplicate_identical",
) -> Mapping[str, ScoreObservation]:
    """Resolve one exact runtime Observation per Candidate or fail closed."""
    if out_of_scope_policy not in {"error", "ignore"}:
        raise SelectionError("selection out-of-scope policy is unsupported")
    if duplicate_policy not in {"error", "deduplicate_identical"}:
        raise SelectionError("selection duplicate policy is unsupported")
    candidate_ids = [candidate.candidate_id for candidate in candidates.items]
    if len(candidate_ids) != len(set(candidate_ids)):
        raise SelectionError(
            "Selection Candidate input has duplicate identities"
        )
    candidate_set = set(candidate_ids)
    seen: dict[tuple[object, ...], bytes] = {}
    matched: dict[str, list[ScoreObservation]] = {
        candidate_id: [] for candidate_id in candidate_ids
    }
    for entry in collection.entries:
        if type(entry) is not ScoreObservation:
            raise SelectionError("Score Collection contains an unknown entry")
        in_scope = (
            entry.candidate_id in candidate_set
            and entry.source_partition == objective.source_partition
            and entry.metric == objective.metric
            and entry.method == objective.method
            and _context_matches_selector(
                entry.context,
                objective.context_selector,
            )
        )
        if not in_scope:
            if out_of_scope_policy == "error":
                raise SelectionError(
                    "selection received an out-of-scope observation"
                )
            continue
        try:
            encoded = canonical_json_bytes(entry.value)
        except CatalogBuildError as error:
            raise SelectionError(
                "Observation value must be canonical I-JSON"
            ) from error
        previous = seen.get(entry.identity)
        if previous is not None:
            if previous != encoded:
                raise SelectionError(
                    "selection has a conflicting observation identity"
                )
            if duplicate_policy == "error":
                raise SelectionError(
                    "selection has a duplicate observation identity"
                )
            continue
        seen[entry.identity] = encoded
        matched[entry.candidate_id].append(entry)
    resolved: dict[str, ScoreObservation] = {}
    selection_id = getattr(
        objective,
        "objective_id",
        getattr(objective, "selector_id", ""),
    )
    for candidate_id in candidate_ids:
        matches = matched[candidate_id]
        if not matches:
            raise SelectionError(
                f"Selector {selection_id!r} has a missing "
                f"observation for Candidate {candidate_id!r}"
            )
        if len(matches) != 1:
            raise SelectionError(
                f"Selector {selection_id!r} requires exactly "
                "one observation per Candidate"
            )
        resolved[candidate_id] = matches[0]
    return MappingProxyType(resolved)


def _context_profile(context: object) -> dict[str, Any]:
    if isinstance(context, IntrinsicObservationContext):
        return context.to_public()
    if isinstance(context, CalibrationObservationContext):
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
    return catalog.require_port_type(type_id, "2.1.0").content_digest(
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
    if propagation.get("schema_version") != "2.1.0":
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
    absent_input_policy = propagation.get(
        "absent_input_policy",
        "reject",
    )
    if absent_input_policy not in {"reject", "ignore"}:
        raise PortValueError(
            "Binding Observation propagation absent input policy is malformed"
        )
    for input_port in input_ports:
        source = inputs.get(input_port)
        if source is None and absent_input_policy == "ignore":
            continue
        if not isinstance(source, ScoreCollection):
            raise PortValueError(
                "Binding Observation propagation input is unavailable"
            )
        source_maps.append(_observation_value_map(source))
        source_observations.extend(_deduplicated_observations(source))
    if not source_maps:
        raise PortValueError(
            "Binding Observation propagation has no connected input"
        )
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


def _resolve_objective_contracts(
    objectives: Sequence[SelectionObjective],
    catalog: FrozenCatalog,
) -> tuple[
    tuple[SelectionObjective, ...],
    float,
    tuple[tuple[SelectionObjective, Any, Any, Any, Mapping[str, Any]], ...],
    tuple[dict[str, Any], ...],
]:
    objective_tuple = tuple(objectives)
    if not objective_tuple:
        raise SelectionError("Selection requires at least one objective")
    objective_ids = [objective.objective_id for objective in objective_tuple]
    if len(objective_ids) != len(set(objective_ids)):
        raise SelectionError("Selection Objective IDs must be unique")
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
    resolved: list[
        tuple[SelectionObjective, Any, Any, Any, Mapping[str, Any]]
    ] = []
    provenance: list[dict[str, Any]] = []
    for objective in objective_tuple:
        metric, method, utility, parameters = resolve_selection_objective(
            objective,
            catalog,
        )
        effective_weight = float(objective.weight) / declared_total
        resolved.append((objective, metric, method, utility, parameters))
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
                "context_selector": objective.context_selector.to_public(),
                "utility_transform": utility.reference(),
                "utility_parameters": _thaw_json(parameters),
                "declared_weight": objective.weight,
                "effective_weight": effective_weight,
                "match_cardinality": objective.match_cardinality,
                "missing_policy": objective.missing_policy,
            }
        )
    return (
        objective_tuple,
        declared_total,
        tuple(resolved),
        tuple(provenance),
    )


def selection_objective_provenance(
    objectives: Sequence[SelectionObjective],
    catalog: FrozenCatalog,
) -> dict[str, Any]:
    """Resolve exact objective contracts and normalized effective weights."""
    _, _, _, provenance = _resolve_objective_contracts(objectives, catalog)
    return _thaw_json(_freeze_json({"objectives": provenance}))


def resolve_candidate_utilities(
    *,
    candidate_inputs: Mapping[SelectionInput, CandidateCollection],
    score_collection_inputs: Mapping[SelectionInput, ScoreCollection],
    objectives: Sequence[SelectionObjective],
    catalog: FrozenCatalog,
) -> CandidateUtilityProfile:
    """Resolve exact dimensionless Utility vectors without scale inference."""
    (
        objective_tuple,
        declared_total,
        resolved,
        provenance,
    ) = _resolve_objective_contracts(objectives, catalog)
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
    utility_values = {
        candidate_id: [] for candidate_id in candidate_ids
    }
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
        normalized_collection = ScoreCollection(
            collection_id=collection.collection_id,
            entries=list(_deduplicated_observations(collection)),
        )
        observations = resolve_objective_observations(
            candidates=candidates,
            collection=normalized_collection,
            objective=objective,
        )
        runtime = catalog.require_utility_transform(
            objective.utility_transform.contract_id,
            objective.utility_transform.contract_version,
        )
        for candidate_id in candidate_ids:
            observation = observations[candidate_id]
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
            utility_values[candidate_id].append(float(output))
    return CandidateUtilityProfile(
        candidates=candidates,
        objective_ids=tuple(
            objective.objective_id for objective in objective_tuple
        ),
        utilities=MappingProxyType(
            {
                candidate_id: tuple(values)
                for candidate_id, values in utility_values.items()
            }
        ),
        effective_weights=tuple(
            float(objective.weight) / declared_total
            for objective in objective_tuple
        ),
        provenance=_freeze_json({"objectives": provenance}),
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


def select_candidates(
    *,
    candidate_inputs: Mapping[SelectionInput, CandidateCollection],
    score_collection_inputs: Mapping[SelectionInput, ScoreCollection],
    objectives: Sequence[SelectionObjective],
    catalog: FrozenCatalog,
    limit: int,
) -> SelectionResult:
    """Rank Candidates using only exact registered dimensionless Utilities."""
    if type(limit) is not int or limit < 1:
        raise SelectionError("Selection limit must be a positive integer")
    profile = resolve_candidate_utilities(
        candidate_inputs=candidate_inputs,
        score_collection_inputs=score_collection_inputs,
        objectives=objectives,
        catalog=catalog,
    )
    ranked = rank_candidates_by_weighted_utility(profile)
    selected = ranked[: min(limit, len(ranked))]
    return SelectionResult(
        CandidateCollection(
            collection_id=f"{profile.candidates.collection_id}.selected",
            item_type=profile.candidates.item_type,
            items=list(selected),
        ),
        profile.provenance,
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
                        if (
                            context.pairing_mode
                            == "per_subject_counterpart"
                        ):
                            pairing_source = (
                                inputs
                                if declaration.get("pairing_direction")
                                == "input"
                                else outputs
                                if declaration.get("pairing_direction")
                                == "output"
                                else None
                            )
                            pairing = (
                                pairing_source.get(
                                    declaration.get("pairing_port")
                                )
                                if pairing_source is not None
                                else None
                            )
                            if not isinstance(
                                pairing,
                                PairwiseCandidateMapping,
                            ):
                                raise SelectionError(
                                    "Pairwise Candidate pairing source is "
                                    "unavailable"
                                )
                            mapping_matches = [
                                entry
                                for entry in pairing.entries
                                if (
                                    entry.subject_candidate_id
                                    == context.subject.candidate_id
                                    and entry.subject_content_digest
                                    == context.subject.content_digest
                                    and entry.reference_candidate_id
                                    == context.reference.candidate_id
                                    and entry.reference_content_digest
                                    == context.reference.content_digest
                                )
                            ]
                            if len(mapping_matches) != 1:
                                raise SelectionError(
                                    "Pairwise Context does not match one exact "
                                    "entry in its declared pairing source"
                                )
                except SelectionError as error:
                    raise PortValueError(str(error)) from error
