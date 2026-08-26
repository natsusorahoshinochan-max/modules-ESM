"""Independent partitioned Candidate and Observation sources."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from core.catalog.declarations import (
    AvailabilityDeclaration,
    AvailabilityResult,
    ContractIdentity,
    ExecutionBindingDefinition,
    MethodDefinition,
    ModulePackageRegistration,
    ProducedObservationDefinition,
    ReadinessDeclaration,
    ScientificOperationFactory,
    UtilityTransformDefinition,
)
from core.catalog.definition_resource import (
    DefinitionResource,
)
from core.catalog.port_contract import (
    BehaviorReference,
)
from core.operation import (
    BindingEnvironment,
    CandidatePairingIntent,
    CandidatePairingIntentEntry,
    OperationCall,
    OperationContext,
    ReadinessResult,
)
from datatypes.candidate import (
    Candidate,
    CandidateCollection,
    CandidateDataReference,
)
from datatypes.observation import (
    IntrinsicObservationContext,
    ScoreCollection,
    ScoreObservation,
)
from datatypes.sequence import ProteinSequence
from tests.fixtures.exact_content_identity import exact_content_identity


METRIC = ContractIdentity(
    "metric",
    "contract_test.collection_ops_value")
_SEQUENCE_CONTENT_IDENTITY = exact_content_identity(
    "protein.sequence",
    "protein_sequence",
)


class _Source:
    def __init__(
        self,
        *,
        resources: Any,
        partition: str,
    ) -> None:
        self._resources = resources
        self._partition = partition

    def execute(self, call: OperationCall) -> dict[str, Any]:
        inputs = call.inputs
        node_parameters = call.node_parameters
        binding_parameters = call.binding_parameters
        if inputs or binding_parameters:
            raise ValueError("collection source accepts no connected inputs")
        count = node_parameters["candidate_count"]
        with self._resources.engine_invocation():
            candidates = [
                Candidate(
                    candidate_id=(
                        f"{self._partition}-candidate-{sample_index}"
                    ),
                    data=ProteinSequence(
                        "ACD" if self._partition == "a" else "ACE"
                    ),
                    parent_ids=(
                        [
                            f"{self._partition}-candidate-"
                            f"{sample_index - 1}"
                        ]
                        if sample_index > 0
                        else []
                    ),
                    metadata={
                        "fixture_partition": self._partition,
                        "sample_index": sample_index,
                    },
                )
                for sample_index in range(count)
            ]
        return {
            "candidates": CandidateCollection(
                collection_id=f"{self._partition}-candidates",
                item_type="protein.sequence",
                items=candidates,
            ),
        }


class _LineageSource:
    def __init__(self, *, resources: Any) -> None:
        self._resources = resources

    def execute(self, call: OperationCall) -> dict[str, Any]:
        if call.inputs or call.binding_parameters:
            raise ValueError("lineage source accepts no connected inputs")
        count = call.node_parameters["candidate_count"]
        with self._resources.engine_invocation():
            parents = [
                Candidate(
                    candidate_id=f"lineage-parent-{sample_index}",
                    data=ProteinSequence("ACD"),
                )
                for sample_index in range(count)
            ]
            references = list(reversed([
                Candidate(
                    candidate_id=f"lineage-reference-{sample_index}",
                    data=ProteinSequence("ACE"),
                    parent_ids=[f"lineage-parent-{sample_index}"],
                )
                for sample_index in range(count)
            ]))
            subjects = [
                Candidate(
                    candidate_id=f"lineage-subject-{sample_index}",
                    data=ProteinSequence("ACF"),
                    parent_ids=[f"lineage-parent-{sample_index}"],
                )
                for sample_index in range(count)
            ]
        return {
            "parents": CandidateCollection(
                collection_id="rebind-parents",
                item_type="protein.sequence",
                items=parents,
            ),
            "references": CandidateCollection(
                collection_id="rebind-references",
                item_type="protein.sequence",
                items=references,
            ),
            "subjects": CandidateCollection(
                collection_id="rebind-subjects",
                item_type="protein.sequence",
                items=subjects,
            ),
            "parent_pairing": CandidatePairingIntent(
                tuple(
                    CandidatePairingIntentEntry(
                        subject_candidate_id=parent.candidate_id,
                        reference_candidate_id=reference.candidate_id,
                    )
                    for parent, reference in zip(
                        parents,
                        references,
                        strict=True,
                    )
                )
            ),
        }


class _Scorer:
    def __init__(
        self,
        *,
        value: float,
        source_partition: str,
        metric: Any,
        method: Any,
    ) -> None:
        self._value = value
        self._source_partition = source_partition
        self._metric = metric
        self._method = method

    def execute(self, call: OperationCall) -> dict[str, Any]:
        inputs = call.inputs
        node_parameters = call.node_parameters
        binding_parameters = call.binding_parameters
        candidate_input = inputs.get("candidates")
        candidates = None if candidate_input is None else candidate_input.value
        if (
            type(candidates) is not CandidateCollection
            or node_parameters
            or binding_parameters
        ):
            raise ValueError("fixture scorer requires exact Candidates")
        admitted = call.inputs.get("candidates")
        if admitted is None:
            raise ValueError("fixture scorer requires admitted Candidates")
        subjects: tuple[CandidateDataReference, ...] = admitted.candidate_data
        if tuple(subject.candidate_id for subject in subjects) != tuple(
            candidate.candidate_id for candidate in candidates.items
        ):
            raise ValueError(
                "fixture scorer Candidate references must match its input"
            )
        return {
            "scores": ScoreCollection(
                collection_id="fixture-scores",
                entries=[
                    ScoreObservation(
                        subject=subject,
                        metric=self._metric,
                        method=self._method,
                        context=IntrinsicObservationContext(),
                        value=self._value,
                        source_partition=self._source_partition,
                    )
                    for subject in subjects
                ],
            )
        }


class _LegacyScores:
    def execute(self, call: OperationCall) -> dict[str, Any]:
        inputs = call.inputs
        node_parameters = call.node_parameters
        binding_parameters = call.binding_parameters
        if inputs or node_parameters or binding_parameters:
            raise ValueError("legacy fixture accepts no values")
        return {
            "scores": ScoreCollection(
                collection_id="legacy-scores",
                entries=[object()],
            )
        }


def _available() -> AvailabilityResult:
    return AvailabilityResult.available()


def _ready(check_input: BindingEnvironment) -> ReadinessResult:
    del check_input
    return ReadinessResult(True)


def _source_method(partition: str) -> MethodDefinition:
    return MethodDefinition(
        method_id=f"contract_test.collection_ops_source.{partition}.method",
        algorithm_identity={
            "name": "deterministic-partition-source",
            "partition": partition,
        },
        model_identity={"kind": "none"},
        featurization_identity={"kind": "identity"},
        scale_contract={"kind": "identity"},
    )


def _source_binding(partition: str) -> ExecutionBindingDefinition:
    method = ContractIdentity(
        "method",
        f"contract_test.collection_ops_source.{partition}.method")

    def build(context: OperationContext) -> _Source:
        return _Source(
            resources=context.resources,
            partition=partition,
        )

    return ExecutionBindingDefinition(
        binding_id=f"contract_test.collection_ops_source.{partition}",
        node_type=ContractIdentity(
            "node_type",
            "contract_test.collection_ops_source"),
        method=method,
        binding_parameters={},
        execution_route="direct",
        factory=ScientificOperationFactory(
            behavior=BehaviorReference(
                f"contract_test.collection_ops_source/{partition}/factory",
                {"execution_route": "direct"},
            ),
            build=build,
        ),
        availability=AvailabilityDeclaration(
            behavior=BehaviorReference(
                f"contract_test.collection_ops_source/{partition}/availability",
                {"observation": "startup"},
            ),
            prerequisites={},
            check=_available,
        ),
        readiness=ReadinessDeclaration(
            behavior=BehaviorReference(
                f"contract_test.collection_ops_source/{partition}/readiness",
                {"observation": "per-run"},
            ),
            prerequisites={},
            check=_ready,
        ),
        deterministic=True,
        cacheable=True)


def _lineage_method() -> MethodDefinition:
    return MethodDefinition(
        method_id="contract_test.collection_ops_lineage_source.method",
        algorithm_identity={"name": "closed-lineage-source"},
        model_identity={"kind": "none"},
        featurization_identity={"kind": "identity"},
        scale_contract={"kind": "identity"},
    )


def _lineage_binding() -> ExecutionBindingDefinition:
    def build(context: OperationContext) -> _LineageSource:
        return _LineageSource(resources=context.resources)

    behavior_prefix = "contract_test.collection_ops_lineage_source"
    return ExecutionBindingDefinition(
        binding_id=f"{behavior_prefix}.direct",
        node_type=ContractIdentity(
            "node_type",
            behavior_prefix),
        method=ContractIdentity(
            "method",
            f"{behavior_prefix}.method"),
        binding_parameters={},
        execution_route="direct",
        factory=ScientificOperationFactory(
            behavior=BehaviorReference(
                f"{behavior_prefix}/factory",
                {"execution_route": "direct"},
            ),
            build=build,
        ),
        availability=AvailabilityDeclaration(
            behavior=BehaviorReference(
                f"{behavior_prefix}/availability",
                {"observation": "startup"},
            ),
            prerequisites={},
            check=_available,
        ),
        readiness=ReadinessDeclaration(
            behavior=BehaviorReference(
                f"{behavior_prefix}/readiness",
                {"observation": "per-run"},
            ),
            prerequisites={},
            check=_ready,
        ),
        deterministic=True,
        cacheable=True)


def _scorer_method() -> MethodDefinition:
    return MethodDefinition(
        method_id="contract_test.collection_ops_scorer.method",
        algorithm_identity={"name": "controlled-fixture-observation"},
        model_identity={"kind": "none"},
        featurization_identity={"kind": "identity"},
        scale_contract={"kind": "identity"},
    )


def _legacy_method() -> MethodDefinition:
    return MethodDefinition(
        method_id="contract_test.collection_ops_legacy_scores.method",
        algorithm_identity={"name": "legacy-subject-free-fixture"},
        model_identity={"kind": "none"},
        featurization_identity={"kind": "identity"},
        scale_contract={"kind": "identity"},
    )


def _scorer_binding(
    binding_name: str,
    *,
    value: float,
    source_partition: str,
) -> ExecutionBindingDefinition:
    def build(context: OperationContext) -> _Scorer:
        return _Scorer(
            value=value,
            source_partition=source_partition,
            metric=context.produced_observations[0].metric,
            method=context.method,
        )

    return ExecutionBindingDefinition(
        binding_id=f"contract_test.collection_ops_scorer.{binding_name}",
        node_type=ContractIdentity(
            "node_type",
            "contract_test.collection_ops_scorer"),
        method=ContractIdentity(
            "method",
            "contract_test.collection_ops_scorer.method"),
        binding_parameters={},
        execution_route="direct",
        factory=ScientificOperationFactory(
            behavior=BehaviorReference(
                f"contract_test.collection_ops_scorer/{binding_name}",
                {
                    "value": value,
                    "source_partition": source_partition,
                },
            ),
            build=build,
        ),
        availability=AvailabilityDeclaration(
            behavior=BehaviorReference(
                f"contract_test.collection_ops_scorer/{binding_name}/availability",
                {"observation": "startup"},
            ),
            prerequisites={},
            check=_available,
        ),
        readiness=ReadinessDeclaration(
            behavior=BehaviorReference(
                f"contract_test.collection_ops_scorer/{binding_name}/readiness",
                {"observation": "per-run"},
            ),
            prerequisites={},
            check=_ready,
        ),
        deterministic=True,
        cacheable=True,
        produced_observations=(
            ProducedObservationDefinition(
                output_port="scores",
                metric=METRIC,
                context_profile={"kind": "intrinsic"},
                subject_grain="candidate",
                source_role="subject",
                subject_direction="input",
                subject_port="candidates",
                guaranteed_multiplicity="one",
                output_partition=source_partition,
            ),
        ),
    )


def _legacy_binding() -> ExecutionBindingDefinition:
    def build(context: OperationContext) -> _LegacyScores:
        del context
        return _LegacyScores()

    return ExecutionBindingDefinition(
        binding_id="contract_test.collection_ops_legacy_scores.direct",
        node_type=ContractIdentity(
            "node_type",
            "contract_test.collection_ops_legacy_scores"),
        method=ContractIdentity(
            "method",
            "contract_test.collection_ops_legacy_scores.method"),
        binding_parameters={},
        execution_route="direct",
        factory=ScientificOperationFactory(
            behavior=BehaviorReference(
                "contract_test.collection_ops_legacy_scores/factory",
                {"execution_route": "direct"},
            ),
            build=build,
        ),
        availability=AvailabilityDeclaration(
            behavior=BehaviorReference(
                "contract_test.collection_ops_legacy_scores/availability",
                {"observation": "startup"},
            ),
            prerequisites={},
            check=_available,
        ),
        readiness=ReadinessDeclaration(
            behavior=BehaviorReference(
                "contract_test.collection_ops_legacy_scores/readiness",
                {"observation": "per-run"},
            ),
            prerequisites={},
            check=_ready,
        ),
        deterministic=True,
        cacheable=True)


def _identity(value: object, parameters: Mapping[str, Any]) -> float:
    if parameters:
        raise ValueError("fixture identity takes no parameters")
    return float(value)


def _utility(partition: str) -> UtilityTransformDefinition:
    return UtilityTransformDefinition(
        transform_id=f"contract_test.collection_ops_identity.{partition}",
        compatible_input_contract={
            "metric": METRIC,
            "method": ContractIdentity(
                "method",
                "contract_test.collection_ops_scorer.method"),
            "context_profile": {"kind": "intrinsic"},
        },
        parameters={},
        behavior=BehaviorReference(
            f"contract_test.collection_ops_identity/{partition}",
            {},
        ),
        transform=_identity,
    )


MODULE_PACKAGE = ModulePackageRegistration(
    package_id="contract_test.collection_ops_sources",
    package_module=__package__,
    node_definitions=(
        DefinitionResource("source.yaml"),
        DefinitionResource("lineage_source.yaml"),
        DefinitionResource("scorer.yaml"),
        DefinitionResource("legacy_scores.yaml"),
    ),
    metric_definitions=(DefinitionResource("metric.yaml"),),
    methods=(
        _source_method("a"),
        _source_method("b"),
        _lineage_method(),
        _scorer_method(),
        _legacy_method(),
    ),
    bindings=(
        _source_binding("a"),
        _source_binding("b"),
        _lineage_binding(),
        _scorer_binding(
            "a",
            value=0.25,
            source_partition="contract_test.partition.a",
        ),
        _scorer_binding(
            "b",
            value=0.75,
            source_partition="contract_test.partition.b",
        ),
        _scorer_binding(
            "low",
            value=0.25,
            source_partition="contract_test.partition.shared",
        ),
        _scorer_binding(
            "high",
            value=0.75,
            source_partition="contract_test.partition.shared",
        ),
        _scorer_binding(
            "collision",
            value=0.25,
            source_partition="contract_test.partition.other",
        ),
        _legacy_binding(),
    ),
    utility_transforms=(_utility("a"), _utility("b")),
)
