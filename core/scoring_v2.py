"""Typed Observations and explicit Utility-based selection."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
import math
import re
import struct
from types import MappingProxyType
from typing import TYPE_CHECKING, Any

from core.parameter_contract import (
    parameter_contract_violation,
    parameter_value_contract,
)
from core.port_types import (
    CatalogBuildError,
    ContractResolutionError,
    FrozenCatalog,
    PortValueError,
    canonical_json_bytes,
)
from datatypes import (
    CalibrationObservationContext,
    CandidateDataReference,
    CandidateCollection,
    ExactContractReference,
    IntrinsicObservationContext,
    PairwiseObservationContext,
    PairwiseCandidateMapping,
    ProteinSequence,
    ProteinStructure,
    ResidueAxisReference,
    ScoreCollection,
    ScoreObservation,
)
from datatypes.i_json import freeze_i_json, thaw_i_json
from datatypes.protein import validate_residue_layout

if TYPE_CHECKING:
    from core.operation import AdmittedPort


class SelectionError(ValueError):
    """A Selection Objective is unsafe or unsatisfied."""


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
            frozen_parameters = freeze_i_json(self.utility_parameters)
            canonical_json_bytes(frozen_parameters)
        except (CatalogBuildError, ValueError) as error:
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
            "utility_parameters": thaw_i_json(self.utility_parameters),
            "weight": self.weight,
            "match_cardinality": self.match_cardinality,
            "missing_policy": self.missing_policy,
        }


@dataclass(frozen=True, slots=True)
class ResolvedMetricFacts:
    """Scientific validation facts for one exact Metric Definition."""

    reference: ExactContractReference
    value_shape: str
    minimum: int | float
    maximum: int | float
    allow_null: bool
    require_finite: bool
    exact_binary32: bool
    requires_residue_axis: bool
    structure_alignment_evidence: Mapping[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class StructureAlignmentEvidenceAdmissionFacts:
    """Exact facts projected from one admitted alignment-evidence value."""

    subject: CandidateDataReference
    reference: CandidateDataReference
    evidence_content_digest: str
    subject_axis_content_digest: str
    reference_axis_content_digest: str
    evidence_method: ExactContractReference
    reference_axis_residue_count: int
    aligned_atom_count: int


@dataclass(frozen=True, slots=True)
class ResolvedSelectionObjective:
    """One Workflow objective with its Metric and Utility fully resolved."""

    objective: SelectionObjective
    metric: ResolvedMetricFacts
    utility_parameters: Mapping[str, Any]
    utility_transform: Callable[[Any, Mapping[str, Any]], Any] = field(
        repr=False,
        compare=False,
    )

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "utility_parameters",
            freeze_i_json(self.utility_parameters),
        )


@dataclass(frozen=True, slots=True)
class ResolvedObservationSelector:
    """One raw Observation selector with its Metric fully resolved."""

    selector: ObservationSelector
    metric: ResolvedMetricFacts


@dataclass(frozen=True, slots=True)
class SelectionResult:
    """Ranked Candidates plus the effective objective provenance."""

    candidates: CandidateCollection
    provenance: Mapping[str, Any] = field(compare=False)

    def __post_init__(self) -> None:
        if not isinstance(self.provenance, Mapping):
            raise SelectionError("Selection provenance must be an object")
        try:
            frozen_provenance = freeze_i_json(self.provenance)
            canonical_json_bytes(frozen_provenance)
        except (CatalogBuildError, ValueError) as error:
            raise SelectionError(
                "Selection provenance must contain canonical I-JSON values"
            ) from error
        object.__setattr__(self, "provenance", frozen_provenance)

    def public_provenance(self) -> dict[str, Any]:
        return thaw_i_json(self.provenance)


@dataclass(frozen=True, slots=True)
class CandidateUtilityProfile:
    """Exact dimensionless Utility vector for every Candidate."""

    candidates: CandidateCollection
    objective_ids: tuple[str, ...]
    utilities: Mapping[str, tuple[float, ...]]
    effective_weights: tuple[float, ...]
    provenance: Mapping[str, Any]

    def public_provenance(self) -> dict[str, Any]:
        return thaw_i_json(self.provenance)


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
    except ContractResolutionError as error:
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
            resolved[name] = thaw_i_json(supplied[name])
        elif "default" in contract:
            resolved[name] = thaw_i_json(contract["default"])
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
    return metric, method, utility, freeze_i_json(parameters)


def resolve_observation_selector(
    selector: ObservationSelector,
    catalog: FrozenCatalog,
) -> tuple[Any, Any]:
    """Resolve only the raw Metric and Method named by a selector."""
    metric = _require_exact_contract(catalog, "metric", selector.metric)
    method = _require_exact_contract(catalog, "method", selector.method)
    return metric, method


def _resolved_metric_facts(
    reference: ExactContractReference,
    metric: Any,
) -> ResolvedMetricFacts:
    descriptor = metric.descriptor
    value_shape = descriptor.get("value_shape")
    if value_shape not in {
        "scalar",
        "per_residue",
        "residue_vector",
        "residue_pair_matrix",
    }:
        raise SelectionError(
            f"Selection does not support Metric value shape {value_shape!r}"
        )
    canonical_range = descriptor.get("canonical_range")
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
    validation = descriptor.get("validation_contract")
    if not isinstance(validation, Mapping):
        raise SelectionError("Metric validation contract is malformed")
    alignment_evidence = validation.get("structure_alignment_evidence")
    required_alignment_context_fields = (
        "evidence_content_digest",
        "evidence_method",
        "subject_axis_content_digest",
        "reference_axis_content_digest",
        "normalization_length",
        "aligned_atom_count",
    )
    if alignment_evidence is not None and (
        not isinstance(alignment_evidence, Mapping)
        or set(alignment_evidence)
        != {
            "source_direction",
            "source_port",
            "normalization_length_source",
            "required_context_fields",
        }
        or alignment_evidence.get("source_direction") != "input"
        or not isinstance(alignment_evidence.get("source_port"), str)
        or not alignment_evidence.get("source_port")
        or alignment_evidence.get("normalization_length_source")
        not in {"aligned_atom_count", "reference_axis_residue_count"}
        or tuple(alignment_evidence.get("required_context_fields", ()))
        != required_alignment_context_fields
    ):
        raise SelectionError(
            "Metric structure-alignment evidence contract is malformed"
        )
    masking = validation.get("masking")
    aggregation = descriptor.get("aggregation_semantics")
    aggregated_residue_population = (
        value_shape == "scalar"
        and isinstance(aggregation, Mapping)
        and aggregation.get("kind") not in (None, "none")
        and type(aggregation.get("source_metric")) is str
        and bool(aggregation.get("source_metric"))
    )
    return ResolvedMetricFacts(
        reference=reference,
        value_shape=value_shape,
        minimum=minimum,
        maximum=maximum,
        allow_null=(
            isinstance(masking, Mapping)
            and masking.get("allow_null") is True
        ),
        require_finite=validation.get("finite") is True,
        exact_binary32=(
            validation.get("numeric_format") == "binary32"
            and validation.get("exact_round_trip") is True
        ),
        requires_residue_axis=(
            value_shape
            in {"per_residue", "residue_vector", "residue_pair_matrix"}
            or aggregated_residue_population
        ),
        structure_alignment_evidence=(
            None
            if alignment_evidence is None
            else freeze_i_json(alignment_evidence)
        ),
    )


def resolve_selection_objective_facts(
    objective: SelectionObjective,
    catalog: FrozenCatalog,
) -> ResolvedSelectionObjective:
    """Resolve Catalog knowledge before entering a Scientific Operation."""
    metric, _, _, parameters = resolve_selection_objective(objective, catalog)
    runtime = catalog.require_utility_transform(
        objective.utility_transform.contract_id,
        objective.utility_transform.contract_version,
    )
    return ResolvedSelectionObjective(
        objective=objective,
        metric=_resolved_metric_facts(objective.metric, metric),
        utility_parameters=parameters,
        utility_transform=runtime,
    )


def resolve_observation_selector_facts(
    selector: ObservationSelector,
    catalog: FrozenCatalog,
) -> ResolvedObservationSelector:
    """Resolve Catalog knowledge before entering a Scientific Operation."""
    metric, _ = resolve_observation_selector(selector, catalog)
    return ResolvedObservationSelector(
        selector=selector,
        metric=_resolved_metric_facts(selector.metric, metric),
    )


def resolve_metric_facts(
    reference: ExactContractReference,
    catalog: FrozenCatalog,
) -> ResolvedMetricFacts:
    """Resolve one exact Metric into immutable scientific validation facts."""
    metric = _require_exact_contract(catalog, "metric", reference)
    return _resolved_metric_facts(reference, metric)


def _validate_metric_value(
    metric: Any,
    value: object,
    *,
    residue_axis: ResidueAxisReference | None = None,
) -> None:
    reference = metric.reference()
    _validate_resolved_metric_value(
        _resolved_metric_facts(
            ExactContractReference(
                contract_kind=reference["contract_kind"],
                contract_id=reference["contract_id"],
                contract_version=reference["contract_version"],
                contract_digest=reference["contract_digest"],
            ),
            metric,
        ),
        value,
        residue_axis=residue_axis,
    )


def _validate_resolved_metric_value(
    metric: ResolvedMetricFacts,
    value: object,
    *,
    residue_axis: ResidueAxisReference | None = None,
) -> None:
    if metric.requires_residue_axis:
        if residue_axis is None:
            raise SelectionError(
                "Metric requires an exact scientific residue axis"
            )
        try:
            validate_residue_layout(
                residue_axis.layout,
                subject="Observation residue layout",
            )
        except (TypeError, ValueError) as error:
            raise SelectionError(str(error)) from error
    elif residue_axis is not None:
        raise SelectionError(
            "Metric does not declare a scientific residue-axis population"
        )

    if metric.value_shape == "scalar":
        values = (value,)
    elif metric.value_shape in {"per_residue", "residue_vector"}:
        if not isinstance(value, (list, tuple)):
            raise SelectionError(
                "Per-residue Metric value must be an ordered array"
            )
        values = tuple(value)
        if residue_axis is None or len(values) != residue_axis.layout.length:
            raise SelectionError(
                "Per-residue Metric value does not align with its exact "
                "residue layout"
            )
    elif metric.value_shape == "residue_pair_matrix":
        if not isinstance(value, (list, tuple)):
            raise SelectionError(
                "Residue-pair Metric value must be an ordered matrix"
            )
        residue_count = (
            residue_axis.layout.length if residue_axis is not None else None
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
            "Selection does not support Metric value shape "
            f"{metric.value_shape!r}"
        )
    for item in values:
        if item is None and metric.allow_null:
            continue
        if (
            isinstance(item, bool)
            or not isinstance(item, (int, float))
            or (metric.require_finite and not math.isfinite(item))
        ):
            raise SelectionError(
                "Metric value does not satisfy its validity/masking contract"
            )
        if item < metric.minimum or item > metric.maximum:
            raise SelectionError("Metric value is outside its canonical range")
        if metric.exact_binary32:
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
    type_id = _candidate_data_type_id(candidate.data)
    if type_id is None:
        raise SelectionError(
            "Candidate subject must carry a canonical scientific value"
        )
    matches = tuple(
        port_type
        for port_type in catalog.port_types
        if port_type.type_id == type_id
    )
    if len(matches) != 1:
        raise SelectionError(
            f"Active Port Type {type_id!r} does not resolve exactly once"
        )
    return matches[0].content_digest(candidate.data)


def _candidate_data_type_id(value: object) -> str | None:
    return {
        ProteinSequence: "protein.sequence",
        ProteinStructure: "protein.structure",
    }.get(type(value))


def _candidate_data_reference(
    candidate: Any,
    content_digest: str,
) -> CandidateDataReference:
    type_id = _candidate_data_type_id(candidate.data)
    if type_id is None:
        raise SelectionError(
            "Candidate subject has no canonical data type identity"
        )
    try:
        return CandidateDataReference(
            candidate_id=candidate.candidate_id,
            data_type_id=type_id,
            content_digest=content_digest,
        )
    except (TypeError, ValueError) as error:
        raise SelectionError(str(error)) from error


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
    inputs: Mapping[str, AdmittedPort],
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
        source_record = inputs.get(input_port)
        if source_record is None and absent_input_policy == "ignore":
            continue
        source = source_record.value if source_record is not None else None
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
    tuple[ResolvedSelectionObjective, ...],
    tuple[dict[str, Any], ...],
]:
    resolved = tuple(
        resolve_selection_objective_facts(objective, catalog)
        for objective in objectives
    )
    return _resolved_objective_contracts(resolved)


def _resolved_objective_contracts(
    resolved: Sequence[ResolvedSelectionObjective],
) -> tuple[
    tuple[SelectionObjective, ...],
    float,
    tuple[ResolvedSelectionObjective, ...],
    tuple[dict[str, Any], ...],
]:
    resolved_tuple = tuple(resolved)
    objective_tuple = tuple(item.objective for item in resolved_tuple)
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
    provenance: list[dict[str, Any]] = []
    for item in resolved_tuple:
        objective = item.objective
        effective_weight = float(objective.weight) / declared_total
        provenance.append(
            {
                "objective_id": objective.objective_id,
                "candidate_input": objective.candidate_input.to_public(),
                "score_collection_input": (
                    objective.score_collection_input.to_public()
                ),
                "source_partition": objective.source_partition,
                "metric": _reference_public("metric", objective.metric),
                "method": _reference_public("method", objective.method),
                "context_selector": objective.context_selector.to_public(),
                "utility_transform": _reference_public(
                    "utility_transform",
                    objective.utility_transform,
                ),
                "utility_parameters": thaw_i_json(item.utility_parameters),
                "declared_weight": objective.weight,
                "effective_weight": effective_weight,
                "match_cardinality": objective.match_cardinality,
                "missing_policy": objective.missing_policy,
            }
        )
    return (
        objective_tuple,
        declared_total,
        resolved_tuple,
        tuple(provenance),
    )


def selection_objective_provenance(
    objectives: Sequence[SelectionObjective],
    catalog: FrozenCatalog,
) -> dict[str, Any]:
    """Resolve exact objective contracts and normalized effective weights."""
    resolved = tuple(
        resolve_selection_objective_facts(objective, catalog)
        for objective in objectives
    )
    return selection_objective_provenance_from_facts(resolved)


def selection_objective_provenance_from_facts(
    objectives: Sequence[ResolvedSelectionObjective],
) -> dict[str, Any]:
    """Project canonical provenance from compile-resolved objectives."""
    _, _, _, provenance = _resolved_objective_contracts(objectives)
    return thaw_i_json(freeze_i_json({"objectives": provenance}))


def _result_identity_reference(
    reference: ExactContractReference,
) -> dict[str, str]:
    return {
        "contract_kind": reference.contract_kind,
        "contract_id": reference.contract_id,
        "contract_version": reference.contract_version,
    }


def selection_objective_identity_facts_from_facts(
    objectives: Sequence[ResolvedSelectionObjective],
    *,
    candidate_input_port: str,
    score_collection_input_port: str,
) -> tuple[dict[str, Any], ...]:
    """Project locator-free scientific facts for Result/output identity."""
    _, _, resolved, provenance = _resolved_objective_contracts(objectives)
    return tuple(
        {
            "candidate_input_port": candidate_input_port,
            "score_collection_input_port": score_collection_input_port,
            "source_partition": item.objective.source_partition,
            "metric": _result_identity_reference(item.objective.metric),
            "method": _result_identity_reference(item.objective.method),
            "context_selector": item.objective.context_selector.to_public(),
            "utility_transform": _result_identity_reference(
                item.objective.utility_transform
            ),
            "utility_parameters": fact["utility_parameters"],
            "declared_weight": fact["declared_weight"],
            "effective_weight": fact["effective_weight"],
            "match_cardinality": item.objective.match_cardinality,
            "missing_policy": item.objective.missing_policy,
        }
        for item, fact in zip(resolved, provenance, strict=True)
    )


def observation_selector_identity_facts_from_facts(
    selectors: Sequence[ResolvedObservationSelector],
    *,
    candidate_input_port: str,
    score_collection_input_port: str,
) -> tuple[dict[str, Any], ...]:
    """Project locator-free raw-observation facts for Result identity."""
    return tuple(
        {
            "candidate_input_port": candidate_input_port,
            "score_collection_input_port": score_collection_input_port,
            "source_partition": item.selector.source_partition,
            "metric": _result_identity_reference(item.selector.metric),
            "method": _result_identity_reference(item.selector.method),
            "context_selector": item.selector.context_selector.to_public(),
            "match_cardinality": item.selector.match_cardinality,
            "missing_policy": item.selector.missing_policy,
        }
        for item in selectors
    )


def resolve_candidate_utilities(
    *,
    candidate_inputs: Mapping[SelectionInput, CandidateCollection],
    score_collection_inputs: Mapping[SelectionInput, ScoreCollection],
    objectives: Sequence[SelectionObjective],
    catalog: FrozenCatalog,
) -> CandidateUtilityProfile:
    """Resolve exact dimensionless Utility vectors without scale inference."""
    resolved = tuple(
        resolve_selection_objective_facts(objective, catalog)
        for objective in objectives
    )
    candidate_references = {
        item.objective.candidate_input for item in resolved
    }
    if len(candidate_references) != 1:
        raise SelectionError(
            "Weighted objectives must use one exact Candidate input"
        )
    candidate_reference = next(iter(candidate_references))
    try:
        selected_candidates = candidate_inputs[candidate_reference]
    except KeyError as error:
        raise SelectionError(
            "Selection Candidate input is missing"
        ) from error
    candidate_data_references = {
        candidate.candidate_id: _candidate_data_reference(
            candidate,
            _candidate_content_digest(catalog, candidate),
        )
        for candidate in selected_candidates.items
    }
    return resolve_candidate_utilities_from_facts(
        candidate_inputs=candidate_inputs,
        score_collection_inputs=score_collection_inputs,
        objectives=resolved,
        candidate_data_references=candidate_data_references,
    )


def resolve_candidate_utilities_from_facts(
    *,
    candidate_inputs: Mapping[SelectionInput, CandidateCollection],
    score_collection_inputs: Mapping[SelectionInput, ScoreCollection],
    objectives: Sequence[ResolvedSelectionObjective],
    candidate_data_references: Mapping[str, CandidateDataReference],
) -> CandidateUtilityProfile:
    """Compute Utilities from pre-resolved scientific facts only."""
    (
        objective_tuple,
        declared_total,
        resolved,
        provenance,
    ) = _resolved_objective_contracts(objectives)
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
    utility_values = {
        candidate_id: [] for candidate_id in candidate_ids
    }
    for item in resolved:
        objective = item.objective
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
        for candidate_id in candidate_ids:
            observation = observations[candidate_id]
            expected_subject = candidate_data_references.get(candidate_id)
            if expected_subject is None:
                raise SelectionError(
                    "Selection lacks exact Candidate content identity"
                )
            if observation.subject != expected_subject:
                raise SelectionError(
                    "Observation subject does not match the exact Candidate "
                    "input"
                )
            if isinstance(
                objective.context_selector,
                PairwiseContextSelector,
            ):
                context = observation.context
                if not isinstance(context, PairwiseObservationContext):
                    raise SelectionError(
                        "Pairwise objective matched a non-pairwise Context"
                    )
                if (
                    context.subject.candidate != expected_subject
                ):
                    raise SelectionError(
                        "Pairwise Context subject identity or content digest "
                        "does not match the exact Candidate input"
                    )
            try:
                output = item.utility_transform(
                    observation.value,
                    item.utility_parameters,
                )
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
        provenance=freeze_i_json({"objectives": provenance}),
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
    return _selection_result(profile, limit)


def _selection_result(
    profile: CandidateUtilityProfile,
    limit: int,
) -> SelectionResult:
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


def resolve_structure_alignment_evidence_admission_facts(
    values: Sequence[object],
    value_content_digests: Sequence[str],
) -> tuple[StructureAlignmentEvidenceAdmissionFacts, ...]:
    """Project the exact cross-value facts required by score admission."""
    if len(values) != len(value_content_digests) or not values:
        raise PortValueError(
            "structure-alignment evidence admission is incomplete"
        )
    projected: list[StructureAlignmentEvidenceAdmissionFacts] = []
    pairs: set[tuple[CandidateDataReference, CandidateDataReference]] = set()
    digest_pattern = re.compile(r"^sha256:[0-9a-f]{64}$")
    for value, evidence_content_digest in zip(
        values,
        value_content_digests,
        strict=True,
    ):
        subject = getattr(value, "subject", None)
        reference = getattr(value, "reference", None)
        subject_axis_content_digest = getattr(
            value,
            "subject_axis_content_digest",
            None,
        )
        reference_axis_content_digest = getattr(
            value,
            "reference_axis_content_digest",
            None,
        )
        evidence_method = getattr(value, "method", None)
        normalization = getattr(value, "normalization", None)
        reference_axis_residue_count = getattr(
            normalization,
            "reference_axis_residue_count",
            None,
        )
        aligned_atom_count = getattr(
            normalization,
            "aligned_atom_count",
            None,
        )
        if (
            type(subject) is not CandidateDataReference
            or subject.data_type_id != "protein.structure"
            or type(reference) is not CandidateDataReference
            or reference.data_type_id != "protein.structure"
            or type(evidence_method) is not ExactContractReference
            or evidence_method.contract_kind != "method"
            or type(evidence_content_digest) is not str
            or digest_pattern.fullmatch(evidence_content_digest) is None
            or type(subject_axis_content_digest) is not str
            or digest_pattern.fullmatch(subject_axis_content_digest) is None
            or type(reference_axis_content_digest) is not str
            or digest_pattern.fullmatch(reference_axis_content_digest) is None
            or type(reference_axis_residue_count) is not int
            or reference_axis_residue_count < 1
            or type(aligned_atom_count) is not int
            or aligned_atom_count < 1
            or aligned_atom_count > reference_axis_residue_count
        ):
            raise PortValueError(
                "structure-alignment evidence admission facts are invalid"
            )
        pair = (subject, reference)
        if pair in pairs:
            raise PortValueError(
                "structure-alignment evidence repeats one exact Candidate pair"
            )
        pairs.add(pair)
        projected.append(
            StructureAlignmentEvidenceAdmissionFacts(
                subject=subject,
                reference=reference,
                evidence_content_digest=evidence_content_digest,
                subject_axis_content_digest=subject_axis_content_digest,
                reference_axis_content_digest=reference_axis_content_digest,
                evidence_method=evidence_method,
                reference_axis_residue_count=reference_axis_residue_count,
                aligned_atom_count=aligned_atom_count,
            )
        )
    return tuple(projected)


def _validate_structure_alignment_evidence_provenance(
    *,
    metric: ResolvedMetricFacts,
    observations: Sequence[ScoreObservation],
    evidence: tuple[StructureAlignmentEvidenceAdmissionFacts, ...],
) -> None:
    contract = metric.structure_alignment_evidence
    if contract is None:
        return
    if len(evidence) != len(observations):
        raise PortValueError(
            "Produced Observation alignment evidence provenance is incomplete"
        )
    by_pair = {
        (entry.subject, entry.reference): entry for entry in evidence
    }
    if len(by_pair) != len(evidence):
        raise PortValueError(
            "Produced Observation alignment evidence provenance is ambiguous"
        )
    observed_pairs: set[
        tuple[CandidateDataReference, CandidateDataReference]
    ] = set()
    normalization_source = contract["normalization_length_source"]
    for observation in observations:
        context = observation.context
        if type(context) is not PairwiseObservationContext:
            raise PortValueError(
                "Produced Observation alignment evidence provenance requires "
                "a pairwise Context"
            )
        pair = (context.subject.candidate, context.reference.candidate)
        admitted = by_pair.get(pair)
        if admitted is None or pair in observed_pairs:
            raise PortValueError(
                "Produced Observation alignment evidence provenance does not "
                "resolve exactly once"
            )
        observed_pairs.add(pair)
        expected_normalization_length = (
            admitted.aligned_atom_count
            if normalization_source == "aligned_atom_count"
            else admitted.reference_axis_residue_count
        )
        if (
            context.evidence_content_digest
            != admitted.evidence_content_digest
            or context.evidence_method != admitted.evidence_method
            or context.subject_axis_content_digest
            != admitted.subject_axis_content_digest
            or context.reference_axis_content_digest
            != admitted.reference_axis_content_digest
            or context.normalization_length
            != expected_normalization_length
            or context.aligned_atom_count != admitted.aligned_atom_count
        ):
            raise PortValueError(
                "Produced Observation alignment evidence provenance "
                "contradicts its admitted alignment"
            )
    if observed_pairs != set(by_pair):
        raise PortValueError(
            "Produced Observation alignment evidence provenance is not closed"
        )


def _directional_source_record(
    *,
    inputs: Mapping[str, AdmittedPort],
    outputs: Mapping[str, AdmittedPort],
    direction: object,
    port_name: object,
) -> AdmittedPort | None:
    if not isinstance(port_name, str):
        return None
    if direction == "input":
        return inputs.get(port_name)
    if direction == "output":
        return outputs.get(port_name)
    return None


def _directional_source_value(
    *,
    inputs: Mapping[str, AdmittedPort],
    outputs: Mapping[str, AdmittedPort],
    direction: object,
    port_name: object,
) -> Any:
    record = _directional_source_record(
        inputs=inputs,
        outputs=outputs,
        direction=direction,
        port_name=port_name,
    )
    return record.value if record is not None else None


def validate_produced_score_collection_from_facts(
    *,
    binding_descriptor: Mapping[str, Any],
    output_port: str,
    collection: ScoreCollection,
    inputs: Mapping[str, AdmittedPort],
    outputs: Mapping[str, AdmittedPort],
    metric_facts: Mapping[
        tuple[str, str, str, str],
        ResolvedMetricFacts,
    ],
) -> None:
    """Validate scoring output using only compile-resolved scientific facts."""
    declarations = [
        declaration
        for declaration in binding_descriptor.get(
            "produced_observations",
            (),
        )
        if declaration.get("output_port") == output_port
    ]
    if not declarations:
        propagation = binding_descriptor.get("observation_propagation")
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
    method_reference = binding_descriptor.get("method")
    for observation in observations:
        try:
            observed_method = _reference_public(
                "method",
                observation.method,
            )
        except SelectionError as error:
            raise PortValueError(str(error)) from error
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
        declaration = matches[0]
        method_direction = declaration.get("method_direction")
        method_port = declaration.get("method_port")
        if method_direction is None and method_port is None:
            allowed_methods = (method_reference,)
        elif method_direction in {"input", "output"} and isinstance(
            method_port, str
        ):
            method_record = _directional_source_record(
                inputs=inputs,
                outputs=outputs,
                direction=method_direction,
                port_name=method_port,
            )
            allowed_methods = tuple(
                _reference_public("method", reference)
                for reference in (
                    method_record.observation_methods
                    if method_record is not None
                    else ()
                )
            )
        else:
            raise PortValueError(
                "Produced Observation Method source declaration is incomplete"
            )
        if observed_method not in allowed_methods:
            raise PortValueError(
                "Binding emitted an Observation with an undeclared Method"
            )
    for declaration in declarations:
        subject_value = _directional_source_value(
            inputs=inputs,
            outputs=outputs,
            direction=declaration.get("subject_direction"),
            port_name=declaration.get("subject_port"),
        )
        subjects = _candidate_values(subject_value)
        subject_ids = tuple(
            candidate.candidate_id for candidate in subjects
        )
        if len(subject_ids) != len(set(subject_ids)):
            raise PortValueError(
                "Binding Produced Observation subject source has duplicates"
            )
        subject_direction = declaration.get("subject_direction")
        subject_port = declaration.get("subject_port")
        subject_record = _directional_source_record(
            inputs=inputs,
            outputs=outputs,
            direction=subject_direction,
            port_name=subject_port,
        )
        admitted_subjects = (
            subject_record.candidate_data
            if subject_record is not None
            else ()
        )
        if (
            len(admitted_subjects) != len(subjects)
            or len({item.candidate_id for item in admitted_subjects})
            != len(admitted_subjects)
            or {item.candidate_id for item in admitted_subjects}
            != set(subject_ids)
        ):
            raise PortValueError(
                "Binding Produced Observation subject identity evidence is "
                "incomplete or contradictory"
            )
        exact_subjects = {
            item.candidate_id: item for item in admitted_subjects
        }
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
        metric_key = (
            "metric",
            declared_metric["contract_id"],
            declared_metric["contract_version"],
            declared_metric["contract_digest"],
        )
        resolved_metric = metric_facts.get(metric_key)
        if resolved_metric is None:
            raise PortValueError(
                "Produced Observation Metric facts are unavailable"
            )
        evidence_contract = resolved_metric.structure_alignment_evidence
        evidence: tuple[StructureAlignmentEvidenceAdmissionFacts, ...] = ()
        if evidence_contract is not None:
            evidence_record = _directional_source_record(
                inputs=inputs,
                outputs=outputs,
                direction=evidence_contract["source_direction"],
                port_name=evidence_contract["source_port"],
            )
            if evidence_record is not None:
                evidence = resolve_structure_alignment_evidence_admission_facts(
                    tuple(item.value for item in evidence_record.values),
                    evidence_record.value_content_digests,
                )
        _validate_structure_alignment_evidence_provenance(
            metric=resolved_metric,
            observations=matching_observations,
            evidence=evidence,
        )
        axis_direction = declaration.get("axis_direction")
        axis_port = declaration.get("axis_port")
        if resolved_metric.requires_residue_axis:
            if axis_direction not in {"input", "output"} or not isinstance(
                axis_port, str
            ):
                raise PortValueError(
                    "Axis-requiring Metric lacks a declared exact axis Port"
                )
            axis_record = _directional_source_record(
                inputs=inputs,
                outputs=outputs,
                direction=axis_direction,
                port_name=axis_port,
            )
            projected_axes = (
                axis_record.scientific_axes
                if axis_record is not None
                else ()
            )
            if not projected_axes:
                raise PortValueError(
                    "Declared scientific axis Port projected no exact axes"
                )
            for observation in matching_observations:
                axis = observation.residue_axis
                if axis is None or sum(
                    candidate_axis == axis for candidate_axis in projected_axes
                ) != 1:
                    raise PortValueError(
                        "Observation residue axis does not resolve exactly once "
                        "from its declared scientific axis Port"
                    )
        elif axis_direction is not None or axis_port is not None:
            raise PortValueError(
                "Metric without an axis population declares an axis Port"
            )
        mismatched_subjects = [
            observation.candidate_id
            for observation in matching_observations
            if observation.subject
            != exact_subjects.get(observation.candidate_id)
        ]
        if mismatched_subjects:
            raise PortValueError(
                "Binding emitted an Observation whose exact subject does not "
                "match its declared Candidate source"
            )
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
                observation.context.reference.candidate
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
            expected_subject = exact_subjects[candidate_id]
            matches = [
                observation
                for observation in matching_observations
                if observation.subject == expected_subject
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
                    metric = metric_facts[
                        (
                            observation.metric.contract_kind,
                            observation.metric.contract_id,
                            observation.metric.contract_version,
                            observation.metric.contract_digest,
                        )
                    ]
                    _validate_resolved_metric_value(
                        metric,
                        observation.value,
                        residue_axis=observation.residue_axis,
                    )
                    if isinstance(
                        observation.context,
                        PairwiseObservationContext,
                    ):
                        context = observation.context
                        if context.subject.candidate != expected_subject:
                            raise SelectionError(
                                "Pairwise Context subject source does not "
                                "match the exact Candidate"
                            )
                        references = _candidate_values(
                            _directional_source_value(
                                inputs=inputs,
                                outputs=outputs,
                                direction=declaration.get(
                                    "reference_direction"
                                ),
                                port_name=declaration.get("reference_port"),
                            )
                        )
                        reference_record = _directional_source_record(
                            inputs=inputs,
                            outputs=outputs,
                            direction=declaration.get(
                                "reference_direction"
                            ),
                            port_name=declaration.get("reference_port"),
                        )
                        admitted_references = (
                            reference_record.candidate_data
                            if reference_record is not None
                            else ()
                        )
                        if len(admitted_references) != len(references):
                            raise SelectionError(
                                "Pairwise reference identity evidence is "
                                "incomplete"
                            )
                        reference_matches = [
                            reference
                            for reference in admitted_references
                            if reference == context.reference.candidate
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
                            pairing = _directional_source_value(
                                inputs=inputs,
                                outputs=outputs,
                                direction=declaration.get(
                                    "pairing_direction"
                                ),
                                port_name=declaration.get("pairing_port"),
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
                                    entry.subject
                                    == context.subject.candidate
                                    and entry.reference
                                    == context.reference.candidate
                                )
                            ]
                            if len(mapping_matches) != 1:
                                raise SelectionError(
                                    "Pairwise Context does not match one exact "
                                    "entry in its declared pairing source"
                                )
                except (KeyError, SelectionError) as error:
                    raise PortValueError(str(error)) from error


def _admit_scoring_validation_ports(
    *,
    catalog: FrozenCatalog,
    declarations: Sequence[Mapping[str, Any]],
    supplied_values: Mapping[str, Any],
) -> Mapping[str, AdmittedPort]:
    """Admit direct validation values to complete Port records once."""
    from core.value_admission import admitted_port_values

    declarations_by_name = {
        declaration["name"]: declaration
        for declaration in declarations
    }
    unknown = set(supplied_values) - set(declarations_by_name)
    if unknown:
        raise PortValueError(
            f"Score validation received unknown Ports: {sorted(unknown)!r}"
        )
    candidate_data_port_types = {
        definition.type_id: definition for definition in catalog.port_types
    }
    admitted: dict[str, AdmittedPort] = {}
    for port_name, raw_value in supplied_values.items():
        declaration = declarations_by_name[port_name]
        port_reference = declaration.get("port_type")
        if not isinstance(port_reference, Mapping):
            raise PortValueError(
                "Score validation Port Type is unavailable"
            )
        try:
            port_type = catalog.require_port_type(
                port_reference["contract_id"],
                port_reference["contract_version"],
            )
        except (KeyError, LookupError) as error:
            raise PortValueError(
                "Score validation Port Type cannot resolve"
            ) from error
        if port_type.reference() != dict(port_reference):
            raise PortValueError(
                "Score validation Port Type identity is not exact"
            )
        multiplicity = declaration.get("multiplicity")
        values = (
            tuple(raw_value)
            if multiplicity == "many"
            else (raw_value,)
        )

        admitted[port_name] = admitted_port_values(
            port_type=port_type,
            multiplicity=multiplicity,
            values=values,
            candidate_data_port_types=candidate_data_port_types,
        )
    return MappingProxyType(admitted)


def validate_produced_score_collection(
    *,
    catalog: FrozenCatalog,
    binding: Any,
    output_port: str,
    collection: ScoreCollection,
    inputs: Mapping[str, Any],
    outputs: Mapping[str, Any],
) -> None:
    """Resolve one Binding and validate complete admitted scoring records."""
    metric_facts: dict[
        tuple[str, str, str, str],
        ResolvedMetricFacts,
    ] = {}
    for declaration in binding.descriptor.get(
        "produced_observations",
        (),
    ):
        reference = ExactContractReference(**declaration["metric"])
        key = (
            reference.contract_kind,
            reference.contract_id,
            reference.contract_version,
            reference.contract_digest,
        )
        metric_facts[key] = resolve_metric_facts(reference, catalog)

    node_reference = binding.descriptor.get("node_type")
    if not isinstance(node_reference, Mapping):
        raise PortValueError("Binding Node Type reference is unavailable")
    try:
        node_type = catalog.require_contract(
            node_reference["contract_kind"],
            node_reference["contract_id"],
            node_reference["contract_version"],
        )
    except (KeyError, ContractResolutionError) as error:
        raise PortValueError(
            "Binding Node Type cannot resolve for score validation"
        ) from error
    node_descriptor = node_type.descriptor
    admitted_inputs = _admit_scoring_validation_ports(
        catalog=catalog,
        declarations=node_descriptor.get("inputs", ()),
        supplied_values=inputs,
    )
    supplied_outputs = dict(outputs)
    supplied_outputs[output_port] = collection
    admitted_outputs = _admit_scoring_validation_ports(
        catalog=catalog,
        declarations=node_descriptor.get("outputs", ()),
        supplied_values=supplied_outputs,
    )
    validate_produced_score_collection_from_facts(
        binding_descriptor=binding.descriptor,
        output_port=output_port,
        collection=collection,
        inputs=admitted_inputs,
        outputs=admitted_outputs,
        metric_facts=metric_facts,
    )
