"""Independent partitioned Candidate and Observation sources."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from core import (
    AvailabilityDeclaration,
    AvailabilityResult,
    BehaviorReference,
    ContractIdentity,
    DefinitionResource,
    ExecutionBindingDefinition,
    LazyImplementationFactory,
    MethodDefinition,
    ModulePackageRegistration,
    ProducedObservationDefinition,
    ReadinessCheckInput,
    ReadinessDeclaration,
    ReadinessResult,
    UtilityTransformDefinition,
)
from datatypes import (
    Candidate,
    CandidateCollection,
    ExactContractReference,
    IntrinsicObservationContext,
    ProteinSequence,
    PairwiseCandidateMapping,
    PairwiseCandidateMatch,
    ScoreCollection,
    ScoreObservation,
)


VERSION = "2.1.0"
METRIC = ContractIdentity(
    "metric",
    "contract_test.collection_ops_value",
    VERSION,
)


class _Source:
    def __init__(
        self,
        *,
        resources: Any,
        catalog: Any,
        partition: str,
    ) -> None:
        self._resources = resources
        self._catalog = catalog
        self._partition = partition
        self._metric = ExactContractReference(
            **catalog.require_contract(
                "metric",
                METRIC.contract_id,
                VERSION,
            ).reference()
        )
        self._method = ExactContractReference(
            **catalog.require_contract(
                "method",
                f"contract_test.collection_ops_source.{partition}.method",
                VERSION,
            ).reference()
        )

    def execute(
        self,
        *,
        inputs: Mapping[str, Any],
        node_parameters: Mapping[str, Any],
        binding_parameters: Mapping[str, Any],
    ) -> dict[str, Any]:
        if inputs or binding_parameters:
            raise ValueError("collection source accepts no connected inputs")
        count = node_parameters["candidate_count"]
        candidates: list[Candidate] = []
        children: list[Candidate] = []
        observations: list[ScoreObservation] = []
        codec = self._catalog.require_port_type(
            "protein.sequence",
            VERSION,
        )
        rebind_parents = [
            Candidate(
                candidate_id=f"rebind-parent-{sample_index}",
                data=ProteinSequence("ACD"),
            )
            for sample_index in range(count)
        ]
        rebind_references = [
            Candidate(
                candidate_id=f"rebind-reference-{sample_index}",
                data=ProteinSequence("ACE"),
            )
            for sample_index in range(count)
        ]
        rebind_subjects = [
            Candidate(
                candidate_id=f"rebind-subject-{sample_index}",
                data=ProteinSequence("ACF"),
                parent_ids=[f"rebind-parent-{sample_index}"],
            )
            for sample_index in range(count)
        ]
        with self._resources.engine_invocation(
            engine_identity=(
                f"contract_test.collection_ops_source/{self._partition}"
            ),
        ):
            for sample_index in range(count):
                candidate_id = (
                    f"{self._partition}-candidate-{sample_index}"
                )
                candidate = Candidate(
                    candidate_id=candidate_id,
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
                candidates.append(candidate)
                children.append(
                    Candidate(
                        candidate_id=(
                            f"{self._partition}-child-{sample_index}"
                        ),
                        data=ProteinSequence(
                            "ACD" if self._partition == "a" else "ACE"
                        ),
                        parent_ids=[candidate_id],
                        metadata={
                            "fixture_partition": self._partition,
                            "sample_index": sample_index,
                        },
                    )
                )
                observations.append(
                    ScoreObservation(
                        candidate_id=candidate_id,
                        metric=self._metric,
                        method=self._method,
                        context=IntrinsicObservationContext(),
                        value=0.25 if self._partition == "a" else 0.75,
                        source_partition=(
                            f"contract_test.partition.{self._partition}"
                        ),
                    )
                )
        return {
            "candidates": CandidateCollection(
                collection_id=f"{self._partition}-candidates",
                item_type="protein.sequence",
                items=candidates,
            ),
            "scores": ScoreCollection(
                collection_id=f"{self._partition}-scores",
                entries=observations,
            ),
            "children": CandidateCollection(
                collection_id=f"{self._partition}-children",
                item_type="protein.sequence",
                items=children,
            ),
            "pairing": PairwiseCandidateMapping([
                PairwiseCandidateMatch(
                    subject_candidate_id=(
                        f"{self._partition}-candidate-{sample_index}"
                    ),
                    subject_content_digest=codec.content_digest(
                        ProteinSequence(
                            "ACD" if self._partition == "a" else "ACE"
                        )
                    ),
                    reference_candidate_id=f"b-candidate-{sample_index}",
                    reference_content_digest=codec.content_digest(
                        ProteinSequence("ACE")
                    ),
                )
                for sample_index in range(count)
            ]),
            "rebind_parents": CandidateCollection(
                collection_id="rebind-parents",
                item_type="protein.sequence",
                items=rebind_parents,
            ),
            "rebind_references": CandidateCollection(
                collection_id="rebind-references",
                item_type="protein.sequence",
                items=rebind_references,
            ),
            "rebind_subjects": CandidateCollection(
                collection_id="rebind-subjects",
                item_type="protein.sequence",
                items=rebind_subjects,
            ),
            "rebind_pairing": PairwiseCandidateMapping([
                PairwiseCandidateMatch(
                    subject_candidate_id=parent.candidate_id,
                    subject_content_digest=codec.content_digest(parent.data),
                    reference_candidate_id=reference.candidate_id,
                    reference_content_digest=codec.content_digest(
                        reference.data
                    ),
                )
                for parent, reference in zip(
                    rebind_parents,
                    rebind_references,
                    strict=True,
                )
            ]),
        }


class _Scorer:
    def __init__(
        self,
        *,
        catalog: Any,
        value: float,
        source_partition: str,
    ) -> None:
        self._value = value
        self._source_partition = source_partition
        self._metric = ExactContractReference(
            **catalog.require_contract(
                "metric",
                METRIC.contract_id,
                VERSION,
            ).reference()
        )
        self._method = ExactContractReference(
            **catalog.require_contract(
                "method",
                "contract_test.collection_ops_scorer.method",
                VERSION,
            ).reference()
        )

    def execute(
        self,
        *,
        inputs: Mapping[str, Any],
        node_parameters: Mapping[str, Any],
        binding_parameters: Mapping[str, Any],
    ) -> dict[str, Any]:
        candidates = inputs.get("candidates")
        if (
            type(candidates) is not CandidateCollection
            or node_parameters
            or binding_parameters
        ):
            raise ValueError("fixture scorer requires exact Candidates")
        return {
            "scores": ScoreCollection(
                collection_id="fixture-scores",
                entries=[
                    ScoreObservation(
                        candidate_id=candidate.candidate_id,
                        metric=self._metric,
                        method=self._method,
                        context=IntrinsicObservationContext(),
                        value=self._value,
                        source_partition=self._source_partition,
                    )
                    for candidate in candidates.items
                ],
            )
        }


class _LegacyScores:
    def execute(
        self,
        *,
        inputs: Mapping[str, Any],
        node_parameters: Mapping[str, Any],
        binding_parameters: Mapping[str, Any],
    ) -> dict[str, Any]:
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


def _ready(check_input: ReadinessCheckInput) -> ReadinessResult:
    del check_input
    return ReadinessResult(True)


def _method(partition: str) -> MethodDefinition:
    return MethodDefinition(
        method_id=f"contract_test.collection_ops_source.{partition}.method",
        version=VERSION,
        algorithm_identity={
            "name": "deterministic-partition-source",
            "partition": partition,
        },
        model_identity={"kind": "none"},
        checkpoint_identity={"kind": "none"},
        featurization_identity={"kind": "identity"},
        source_identity={"kind": "contract-test"},
        scale_contract={"kind": "identity"},
    )


def _binding(partition: str) -> ExecutionBindingDefinition:
    method = ContractIdentity(
        "method",
        f"contract_test.collection_ops_source.{partition}.method",
        VERSION,
    )

    def build(**kwargs: object) -> _Source:
        return _Source(
            resources=kwargs["run_resources"],
            catalog=kwargs["frozen_catalog"],
            partition=partition,
        )

    return ExecutionBindingDefinition(
        binding_id=f"contract_test.collection_ops_source.{partition}",
        version=VERSION,
        node_type=ContractIdentity(
            "node_type",
            "contract_test.collection_ops_source",
            VERSION,
        ),
        method=method,
        binding_parameters={},
        execution_route="direct",
        factory=LazyImplementationFactory(
            behavior=BehaviorReference(
                f"contract_test.collection_ops_source/{partition}/factory",
                VERSION,
                {"execution_route": "direct"},
            ),
            build=build,
        ),
        availability=AvailabilityDeclaration(
            behavior=BehaviorReference(
                f"contract_test.collection_ops_source/{partition}/availability",
                VERSION,
                {"observation": "startup"},
            ),
            prerequisites={},
            check=_available,
        ),
        readiness=ReadinessDeclaration(
            behavior=BehaviorReference(
                f"contract_test.collection_ops_source/{partition}/readiness",
                VERSION,
                {"observation": "per-run"},
            ),
            prerequisites={},
            check=_ready,
        ),
        deterministic=True,
        cacheable=True,
        implementation_identity={
            "name": f"contract_test.collection_ops_source.{partition}",
            "source": "contract-test",
        },
        produced_observations=(
            ProducedObservationDefinition(
                output_port="scores",
                metric=METRIC,
                context_profile={"kind": "intrinsic"},
                subject_grain="candidate",
                source_role="subject",
                subject_direction="output",
                subject_port="candidates",
                guaranteed_multiplicity="one",
                output_partition=(
                    f"contract_test.partition.{partition}"
                ),
            ),
        ),
    )


def _scorer_method() -> MethodDefinition:
    return MethodDefinition(
        method_id="contract_test.collection_ops_scorer.method",
        version=VERSION,
        algorithm_identity={"name": "controlled-fixture-observation"},
        model_identity={"kind": "none"},
        checkpoint_identity={"kind": "none"},
        featurization_identity={"kind": "identity"},
        source_identity={"kind": "contract-test"},
        scale_contract={"kind": "identity"},
    )


def _legacy_method() -> MethodDefinition:
    return MethodDefinition(
        method_id="contract_test.collection_ops_legacy_scores.method",
        version=VERSION,
        algorithm_identity={"name": "legacy-subject-free-fixture"},
        model_identity={"kind": "none"},
        checkpoint_identity={"kind": "none"},
        featurization_identity={"kind": "identity"},
        source_identity={"kind": "contract-test"},
        scale_contract={"kind": "identity"},
    )


def _scorer_binding(
    binding_name: str,
    *,
    value: float,
    source_partition: str,
) -> ExecutionBindingDefinition:
    def build(**kwargs: object) -> _Scorer:
        return _Scorer(
            catalog=kwargs["frozen_catalog"],
            value=value,
            source_partition=source_partition,
        )

    return ExecutionBindingDefinition(
        binding_id=f"contract_test.collection_ops_scorer.{binding_name}",
        version=VERSION,
        node_type=ContractIdentity(
            "node_type",
            "contract_test.collection_ops_scorer",
            VERSION,
        ),
        method=ContractIdentity(
            "method",
            "contract_test.collection_ops_scorer.method",
            VERSION,
        ),
        binding_parameters={},
        execution_route="direct",
        factory=LazyImplementationFactory(
            behavior=BehaviorReference(
                f"contract_test.collection_ops_scorer/{binding_name}",
                VERSION,
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
                VERSION,
                {"observation": "startup"},
            ),
            prerequisites={},
            check=_available,
        ),
        readiness=ReadinessDeclaration(
            behavior=BehaviorReference(
                f"contract_test.collection_ops_scorer/{binding_name}/readiness",
                VERSION,
                {"observation": "per-run"},
            ),
            prerequisites={},
            check=_ready,
        ),
        deterministic=True,
        cacheable=True,
        implementation_identity={
            "name": f"contract_test.collection_ops_scorer.{binding_name}",
            "source": "contract-test",
        },
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
    def build(**kwargs: object) -> _LegacyScores:
        del kwargs
        return _LegacyScores()

    return ExecutionBindingDefinition(
        binding_id="contract_test.collection_ops_legacy_scores.direct",
        version=VERSION,
        node_type=ContractIdentity(
            "node_type",
            "contract_test.collection_ops_legacy_scores",
            VERSION,
        ),
        method=ContractIdentity(
            "method",
            "contract_test.collection_ops_legacy_scores.method",
            VERSION,
        ),
        binding_parameters={},
        execution_route="direct",
        factory=LazyImplementationFactory(
            behavior=BehaviorReference(
                "contract_test.collection_ops_legacy_scores/factory",
                VERSION,
                {"execution_route": "direct"},
            ),
            build=build,
        ),
        availability=AvailabilityDeclaration(
            behavior=BehaviorReference(
                "contract_test.collection_ops_legacy_scores/availability",
                VERSION,
                {"observation": "startup"},
            ),
            prerequisites={},
            check=_available,
        ),
        readiness=ReadinessDeclaration(
            behavior=BehaviorReference(
                "contract_test.collection_ops_legacy_scores/readiness",
                VERSION,
                {"observation": "per-run"},
            ),
            prerequisites={},
            check=_ready,
        ),
        deterministic=True,
        cacheable=True,
        implementation_identity={
            "name": "contract_test.collection_ops_legacy_scores.direct",
            "source": "contract-test",
        },
    )


def _identity(value: object, parameters: Mapping[str, Any]) -> float:
    if parameters:
        raise ValueError("fixture identity takes no parameters")
    return float(value)


def _utility(partition: str) -> UtilityTransformDefinition:
    return UtilityTransformDefinition(
        transform_id=f"contract_test.collection_ops_identity.{partition}",
        version=VERSION,
        compatible_input_contract={
            "metric": METRIC,
            "method": ContractIdentity(
                "method",
                f"contract_test.collection_ops_source.{partition}.method",
                VERSION,
            ),
            "context_profile": {"kind": "intrinsic"},
        },
        parameters={},
        behavior=BehaviorReference(
            f"contract_test.collection_ops_identity/{partition}",
            VERSION,
            {},
        ),
        transform=_identity,
    )


MODULE_PACKAGE = ModulePackageRegistration(
    schema_version="2.1.0",
    package_id="contract_test.collection_ops_sources",
    package_version=VERSION,
    package_module=__package__,
    node_definitions=(
        DefinitionResource("source.yaml"),
        DefinitionResource("scorer.yaml"),
        DefinitionResource("legacy_scores.yaml"),
    ),
    metric_definitions=(DefinitionResource("metric.yaml"),),
    methods=(
        _method("a"),
        _method("b"),
        _scorer_method(),
        _legacy_method(),
    ),
    bindings=(
        _binding("a"),
        _binding("b"),
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
