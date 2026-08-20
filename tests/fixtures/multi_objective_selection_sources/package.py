"""Canonical fixed-3GB1 and paired-ESM3 selection fixture package."""

from __future__ import annotations

from collections.abc import Mapping
from contextlib import nullcontext
from typing import Any

from core import (
    AvailabilityDeclaration,
    AvailabilityResult,
    BehaviorReference,
    CandidatePairingIntent,
    CandidatePairingIntentEntry,
    ContractIdentity,
    DefinitionResource,
    ExecutionBindingDefinition,
    MethodDefinition,
    ModulePackageRegistration,
    OperationCall,
    OperationContext,
    ProducedObservationDefinition,
    ReadinessDeclaration,
    ReadinessResult,
    ScientificOperationFactory,
    UtilityTransformDefinition,
)
from core.port_types import PROTEIN_STRUCTURE_PORT_TYPE_VERSION
from datatypes import (
    Candidate,
    CandidateCollection,
    CandidateDataReference,
    PairwiseObservationContext,
    PairwiseCandidateMapping,
    PairwiseParticipant,
    ProteinStructure,
    ScoreCollection,
    ScoreObservation,
)
from tests.fixtures.exact_content_identity import exact_content_identity


PACKAGE_VERSION = "3.0.0"
METHOD_VERSION = "2.1.0"
METRIC_VERSION = "3.0.0"
UTILITY_VERSION = "3.0.0"
SOURCE_NODE_BINDING_VERSION = "4.0.0"
SCORER_NODE_BINDING_VERSION = "5.0.0"
SOURCE_NODE_TYPE = ContractIdentity(
    "node_type",
    "contract_test.multi_objective_selection_source",
    SOURCE_NODE_BINDING_VERSION,
)
SCORER_NODE_TYPE = ContractIdentity(
    "node_type",
    "contract_test.multi_objective_selection_scores",
    SCORER_NODE_BINDING_VERSION,
)
SOURCE_METHOD = ContractIdentity(
    "method",
    "contract_test.multi_objective_selection_source.candidates.method",
    METHOD_VERSION,
)
METHOD = ContractIdentity(
    "method",
    "contract_test.multi_objective_selection_source.method",
    METHOD_VERSION,
)
PAIRWISE_SELECTION_SCORE = ContractIdentity(
    "metric",
    "contract_test.multi_objective_selection_score",
    METRIC_VERSION,
)
FIXED_PARTITION = "canonical.selection_score.fixed_3gb1"
PAIRED_PARTITION = "canonical.selection_score.paired_esm3"
NORMALIZATION = "literal-unit-interval"
VALUES = {
    "delta": (0.5, 0.5),
    "charlie": (0.8, 0.4),
    "bravo": (0.6, 0.9),
    "alpha": (0.123456, 0.654321),
}
_STRUCTURE_CONTENT_IDENTITY = exact_content_identity(
    "protein.structure",
    "protein_structure",
    version=PROTEIN_STRUCTURE_PORT_TYPE_VERSION,
)


def _structure(label: str) -> ProteinStructure:
    coordinate = float(sum(label.encode("utf-8")) % 17)
    coordinate_record = (
        "ATOM      1  CA  ALA A   1    "
        f"{coordinate:8.3f}{0.0:8.3f}{0.0:8.3f}"
        "  1.00 20.00           C"
    ).ljust(80)
    return ProteinStructure(
        pdb_string=f"{coordinate_record}\nTER\nEND\n",
    )


class _Source:
    def __init__(
        self,
        run_resources: Any,
    ) -> None:
        self._run_resources = run_resources

    def execute(self, call: OperationCall) -> dict[str, Any]:
        inputs = call.inputs
        node_parameters = call.node_parameters
        binding_parameters = call.binding_parameters
        if inputs or node_parameters or binding_parameters:
            raise ValueError("canonical selection fixture accepts no inputs")
        invocation = (
            self._run_resources.engine_invocation()
            if self._run_resources is not None
            else nullcontext()
        )
        with invocation:
            return self._values()

    def _values(self) -> dict[str, Any]:
        candidates = CandidateCollection(
            collection_id="canonical-folded-candidates",
            item_type="protein.structure",
            items=[
                Candidate(
                    candidate_id,
                    _structure(candidate_id),
                    metadata={"fixture_key": candidate_id},
                )
                for candidate_id in VALUES
            ],
        )
        references = CandidateCollection(
            collection_id="canonical-selection-references",
            item_type="protein.structure",
            items=[
                Candidate(
                    "3gb1",
                    _structure("3gb1"),
                    metadata={"fixture_reference_kind": "fixed"},
                ),
                *[
                    Candidate(
                        f"esm3-{candidate_id}",
                        _structure(f"esm3-{candidate_id}"),
                        metadata={"fixture_subject_key": candidate_id},
                    )
                    for candidate_id in VALUES
                ],
            ],
        )
        pairing = CandidatePairingIntent(
            tuple(
                CandidatePairingIntentEntry(
                    subject_candidate_id=candidate_id,
                    reference_candidate_id=f"esm3-{candidate_id}",
                )
                for candidate_id in VALUES
            )
        )

        return {
            "candidates": candidates,
            "references": references,
            "pairing": pairing,
        }


class _Scorer:
    def __init__(
        self,
        run_resources: Any,
        *,
        metric: Any,
        method: Any,
    ) -> None:
        self._run_resources = run_resources
        self._metric = metric
        self._method = method

    def execute(self, call: OperationCall) -> dict[str, ScoreCollection]:
        if call.node_parameters or call.binding_parameters:
            raise ValueError("canonical selection scorer accepts no parameters")
        candidates = call.inputs["candidates"].value
        references = call.inputs["references"].value
        pairing = call.inputs["pairing"].value
        if (
            type(candidates) is not CandidateCollection
            or type(references) is not CandidateCollection
            or type(pairing) is not PairwiseCandidateMapping
        ):
            raise ValueError("canonical selection scorer requires exact inputs")

        candidate_references = {
            reference.candidate_id: reference
            for reference in call.inputs[
                "candidates"
            ].candidate_data
        }
        reference_references = {
            reference.candidate_id: reference
            for reference in call.inputs[
                "references"
            ].candidate_data
        }
        fixed_candidate = next(
            candidate
            for candidate in references.items
            if candidate.metadata.get("fixture_reference_kind") == "fixed"
        )
        fixed_reference = reference_references[fixed_candidate.candidate_id]
        paired_references = {
            entry.subject.candidate_id: entry.reference
            for entry in pairing.entries
        }

        def participant(
            role: str,
            candidate: CandidateDataReference,
        ) -> PairwiseParticipant:
            return PairwiseParticipant(role=role, candidate=candidate)

        observations: list[ScoreObservation] = []
        for candidate in candidates.items:
            fixture_key = candidate.metadata["fixture_key"]
            if not isinstance(fixture_key, str):
                raise ValueError("fixture Candidate key must be exact")
            fixed_value, paired_value = VALUES[fixture_key]
            subject = candidate_references[candidate.candidate_id]
            paired = paired_references[candidate.candidate_id]
            observations.extend(
                (
                    ScoreObservation(
                        subject=subject,
                        metric=self._metric,
                        method=self._method,
                        context=PairwiseObservationContext(
                            subject=participant("subject", subject),
                            reference=participant(
                                "reference",
                                fixed_reference,
                            ),
                            pairing_mode="fixed_reference",
                            normalization=NORMALIZATION,
                        ),
                        value=fixed_value,
                        source_partition=FIXED_PARTITION,
                    ),
                    ScoreObservation(
                        subject=subject,
                        metric=self._metric,
                        method=self._method,
                        context=PairwiseObservationContext(
                            subject=participant("subject", subject),
                            reference=participant("reference", paired),
                            pairing_mode="per_subject_counterpart",
                            normalization=NORMALIZATION,
                        ),
                        value=paired_value,
                        source_partition=PAIRED_PARTITION,
                    ),
                )
            )
        invocation = (
            self._run_resources.engine_invocation()
            if self._run_resources is not None
            else nullcontext()
        )
        with invocation:
            return {
                "scores": ScoreCollection(
                    collection_id="canonical-selection-scores",
                    entries=observations,
                )
            }


def _build_source(context: OperationContext) -> _Source:
    return _Source(context.resources)


def _build_scorer(context: OperationContext) -> _Scorer:
    return _Scorer(
        context.resources,
        metric=context.produced_observations[0].metric,
        method=context.method,
    )


def _identity(value: object, parameters: Mapping[str, Any]) -> float:
    if parameters:
        raise ValueError("selection-score identity Utility accepts no parameters")
    result = float(value)
    if not 0 <= result <= 1:
        raise ValueError("selection-score identity Utility requires [0, 1]")
    return result


def _utility(transform_id: str, pairing_mode: str) -> UtilityTransformDefinition:
    return UtilityTransformDefinition(
        transform_id=transform_id,
        version=UTILITY_VERSION,
        compatible_input_contract={
            "metric": PAIRWISE_SELECTION_SCORE,
            "method": METHOD,
            "context_profile": {
                "kind": "pairwise",
                "subject_role": "subject",
                "reference_role": "reference",
                "pairing_mode": pairing_mode,
                "normalization": NORMALIZATION,
            },
        },
        parameters={},
        behavior=BehaviorReference(
            f"{transform_id}/transform",
            UTILITY_VERSION,
            {"mapping": "identity"},
        ),
        transform=_identity,
    )


MODULE_PACKAGE = ModulePackageRegistration(
    schema_version="2.1.0",
    package_id="contract_test.multi_objective_selection_sources",
    package_version=PACKAGE_VERSION,
    package_module=__package__,
    node_definitions=(
        DefinitionResource("source.yaml"),
        DefinitionResource("scorer.yaml"),
    ),
    metric_definitions=(DefinitionResource("metric.yaml"),),
    methods=(
        MethodDefinition(
            method_id=SOURCE_METHOD.contract_id,
            version=METHOD_VERSION,
            algorithm_identity={
                "name": "canonical-literal-candidate-source",
            },
            model_identity={"kind": "none"},
            checkpoint_identity={"kind": "none"},
            featurization_identity={"kind": "literal-fixture"},
            source_identity={"kind": "contract-test"},
            scale_contract={"kind": "candidate-collection"},
        ),
        MethodDefinition(
            method_id=METHOD.contract_id,
            version=METHOD_VERSION,
            algorithm_identity={
                "name": "canonical-literal-pairwise-selection-score-source",
            },
            model_identity={"kind": "none"},
            checkpoint_identity={"kind": "none"},
            featurization_identity={"kind": "literal-fixture"},
            source_identity={"kind": "contract-test"},
            scale_contract={"kind": "literal-unit-interval"},
        ),
    ),
    bindings=(
        ExecutionBindingDefinition(
            binding_id="contract_test.multi_objective_selection_source.direct",
            version=SOURCE_NODE_BINDING_VERSION,
            node_type=SOURCE_NODE_TYPE,
            method=SOURCE_METHOD,
            binding_parameters={},
            execution_route="direct",
            factory=ScientificOperationFactory(
                behavior=BehaviorReference(
                    "contract_test.multi_objective_selection_source/factory",
                    SOURCE_NODE_BINDING_VERSION,
                    {},
                ),
                build=_build_source,
            ),
            availability=AvailabilityDeclaration(
                behavior=BehaviorReference(
                    "contract_test.multi_objective_selection_source/availability",
                    SOURCE_NODE_BINDING_VERSION,
                    {},
                ),
                prerequisites={},
                check=AvailabilityResult.available,
            ),
            readiness=ReadinessDeclaration(
                behavior=BehaviorReference(
                    "contract_test.multi_objective_selection_source/readiness",
                    SOURCE_NODE_BINDING_VERSION,
                    {},
                ),
                prerequisites={},
                check=lambda environment: ReadinessResult(True),
            ),
            deterministic=True,
            cacheable=True,
            implementation_identity={
                "name": "canonical-multi-objective-selection-source",
                "source": "contract-test",
            },
        ),
        ExecutionBindingDefinition(
            binding_id="contract_test.multi_objective_selection_scores.direct",
            version=SCORER_NODE_BINDING_VERSION,
            node_type=SCORER_NODE_TYPE,
            method=METHOD,
            binding_parameters={},
            execution_route="direct",
            factory=ScientificOperationFactory(
                behavior=BehaviorReference(
                    "contract_test.multi_objective_selection_scores/factory",
                    SCORER_NODE_BINDING_VERSION,
                    {},
                ),
                build=_build_scorer,
            ),
            availability=AvailabilityDeclaration(
                behavior=BehaviorReference(
                    "contract_test.multi_objective_selection_scores/availability",
                    SCORER_NODE_BINDING_VERSION,
                    {},
                ),
                prerequisites={},
                check=AvailabilityResult.available,
            ),
            readiness=ReadinessDeclaration(
                behavior=BehaviorReference(
                    "contract_test.multi_objective_selection_scores/readiness",
                    SCORER_NODE_BINDING_VERSION,
                    {},
                ),
                prerequisites={},
                check=lambda environment: ReadinessResult(True),
            ),
            deterministic=True,
            cacheable=True,
            implementation_identity={
                "name": "canonical-multi-objective-selection-scores",
                "source": "contract-test",
                "candidate_score_join": "exact-candidate-data-reference",
            },
            produced_observations=(
                ProducedObservationDefinition(
                    output_port="scores",
                    metric=PAIRWISE_SELECTION_SCORE,
                    context_profile={
                        "kind": "pairwise",
                        "subject_role": "subject",
                        "reference_role": "reference",
                        "pairing_mode": "fixed_reference",
                        "normalization": NORMALIZATION,
                    },
                    subject_grain="candidate",
                    source_role="subject",
                    subject_direction="input",
                    subject_port="candidates",
                    guaranteed_multiplicity="one",
                    output_partition=FIXED_PARTITION,
                    reference_direction="input",
                    reference_port="references",
                ),
                ProducedObservationDefinition(
                    output_port="scores",
                    metric=PAIRWISE_SELECTION_SCORE,
                    context_profile={
                        "kind": "pairwise",
                        "subject_role": "subject",
                        "reference_role": "reference",
                        "pairing_mode": "per_subject_counterpart",
                        "normalization": NORMALIZATION,
                    },
                    subject_grain="candidate",
                    source_role="subject",
                    subject_direction="input",
                    subject_port="candidates",
                    guaranteed_multiplicity="one",
                    output_partition=PAIRED_PARTITION,
                    reference_direction="input",
                    reference_port="references",
                    pairing_direction="input",
                    pairing_port="pairing",
                ),
            ),
        ),
    ),
    utility_transforms=(
        _utility(
            "contract_test.multi_objective_selection_score."
            "fixed_3gb1.identity",
            "fixed_reference",
        ),
        _utility(
            "contract_test.multi_objective_selection_score."
            "paired_esm3.identity",
            "per_subject_counterpart",
        ),
    ),
)
