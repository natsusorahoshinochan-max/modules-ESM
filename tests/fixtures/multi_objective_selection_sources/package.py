"""Canonical fixed-3GB1 and paired-ESM3 selection fixture package."""

from __future__ import annotations

from collections.abc import Mapping
from contextlib import nullcontext
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
    ReadinessDeclaration,
    ReadinessResult,
    UtilityTransformDefinition,
)
from datatypes import (
    Candidate,
    CandidateCollection,
    ExactContractReference,
    PairwiseCandidateMapping,
    PairwiseCandidateMatch,
    PairwiseObservationContext,
    PairwiseParticipant,
    ProteinStructure,
    ScoreCollection,
    ScoreObservation,
)


VERSION = "2.1.0"
NODE_TYPE = ContractIdentity(
    "node_type",
    "contract_test.multi_objective_selection_source",
    VERSION,
)
METHOD = ContractIdentity(
    "method",
    "contract_test.multi_objective_selection_source.method",
    VERSION,
)
TM_SCORE = ContractIdentity(
    "metric",
    "structure_comparison.tm_score",
    VERSION,
)
FIXED_PARTITION = "canonical.tm_score.fixed_3gb1"
PAIRED_PARTITION = "canonical.tm_score.paired_esm3"
NORMALIZATION = "standard-reference-residue-count"
VALUES = {
    "delta": (0.5, 0.5),
    "charlie": (0.8, 0.4),
    "bravo": (0.6, 0.9),
    "alpha": (0.123456, 0.654321),
}


def _structure(label: str) -> ProteinStructure:
    coordinate = float(sum(label.encode("utf-8")) % 17)
    return ProteinStructure(
        pdb_string=(
            "ATOM      1  CA  ALA A   1    "
            f"{coordinate:8.3f}{0.0:8.3f}{0.0:8.3f}"
            "  1.00 20.00           C\nTER\nEND\n"
        ),
        source="contract-test",
    )


class _Source:
    def __init__(self, catalog: Any, run_resources: Any) -> None:
        self._catalog = catalog
        self._run_resources = run_resources

    def execute(
        self,
        *,
        inputs: Mapping[str, Any],
        node_parameters: Mapping[str, Any],
        binding_parameters: Mapping[str, Any],
    ) -> dict[str, Any]:
        if inputs or node_parameters or binding_parameters:
            raise ValueError("canonical selection fixture accepts no inputs")
        invocation = (
            self._run_resources.engine_invocation(
                engine_identity="canonical-selection-fixture"
            )
            if self._run_resources is not None
            else nullcontext()
        )
        with invocation:
            return self._values()

    def _values(self) -> dict[str, Any]:
        metric = ExactContractReference(
            **self._catalog.require_contract(
                "metric",
                TM_SCORE.contract_id,
                VERSION,
            ).reference()
        )
        method = ExactContractReference(
            **self._catalog.require_contract(
                "method",
                METHOD.contract_id,
                VERSION,
            ).reference()
        )
        candidates = CandidateCollection(
            collection_id="canonical-folded-candidates",
            item_type="protein.structure",
            items=[
                Candidate(candidate_id, _structure(candidate_id))
                for candidate_id in VALUES
            ],
        )
        references = CandidateCollection(
            collection_id="canonical-selection-references",
            item_type="protein.structure",
            items=[
                Candidate("3gb1", _structure("3gb1")),
                *[
                    Candidate(
                        f"esm3-{candidate_id}",
                        _structure(f"esm3-{candidate_id}"),
                    )
                    for candidate_id in VALUES
                ],
            ],
        )
        candidate_digest = self._catalog.require_port_type(
            "protein.structure",
            VERSION,
        ).content_digest
        candidates_by_id = {
            candidate.candidate_id: candidate for candidate in candidates.items
        }
        references_by_id = {
            candidate.candidate_id: candidate for candidate in references.items
        }
        pairing = PairwiseCandidateMapping(
            entries=[
                PairwiseCandidateMatch(
                    subject_candidate_id=candidate_id,
                    subject_content_digest=candidate_digest(
                        candidates_by_id[candidate_id].data
                    ),
                    reference_candidate_id=f"esm3-{candidate_id}",
                    reference_content_digest=candidate_digest(
                        references_by_id[f"esm3-{candidate_id}"].data
                    ),
                )
                for candidate_id in VALUES
            ]
        )

        def participant(role: str, candidate: Candidate) -> PairwiseParticipant:
            return PairwiseParticipant(
                role=role,
                candidate_id=candidate.candidate_id,
                content_digest=candidate_digest(candidate.data),
            )

        observations: list[ScoreObservation] = []
        for candidate_id, (fixed_value, paired_value) in VALUES.items():
            subject = candidates_by_id[candidate_id]
            fixed = references_by_id["3gb1"]
            paired = references_by_id[f"esm3-{candidate_id}"]
            observations.extend(
                (
                    ScoreObservation(
                        candidate_id=candidate_id,
                        metric=metric,
                        method=method,
                        context=PairwiseObservationContext(
                            subject=participant("subject", subject),
                            reference=participant("reference", fixed),
                            pairing_mode="fixed_reference",
                            normalization=NORMALIZATION,
                        ),
                        value=fixed_value,
                        source_partition=FIXED_PARTITION,
                    ),
                    ScoreObservation(
                        candidate_id=candidate_id,
                        metric=metric,
                        method=method,
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
        return {
            "candidates": candidates,
            "references": references,
            "pairing": pairing,
            "scores": ScoreCollection(
                collection_id="canonical-selection-scores",
                entries=observations,
            ),
        }


def _build(**kwargs: object) -> _Source:
    return _Source(
        kwargs["frozen_catalog"],
        kwargs["run_resources"],
    )


def _identity(value: object, parameters: Mapping[str, Any]) -> float:
    if parameters:
        raise ValueError("TM-score identity Utility accepts no parameters")
    result = float(value)
    if not 0 <= result <= 1:
        raise ValueError("TM-score identity Utility requires [0, 1]")
    return result


def _utility(transform_id: str, pairing_mode: str) -> UtilityTransformDefinition:
    return UtilityTransformDefinition(
        transform_id=transform_id,
        version=VERSION,
        compatible_input_contract={
            "metric": TM_SCORE,
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
            VERSION,
            {"mapping": "identity"},
        ),
        transform=_identity,
    )


MODULE_PACKAGE = ModulePackageRegistration(
    schema_version="2.1.0",
    package_id="contract_test.multi_objective_selection_sources",
    package_version=VERSION,
    package_module=__package__,
    node_definitions=(DefinitionResource("source.yaml"),),
    methods=(
        MethodDefinition(
            method_id=METHOD.contract_id,
            version=VERSION,
            algorithm_identity={
                "name": "canonical-literal-pairwise-tm-score-source",
            },
            model_identity={"kind": "none"},
            checkpoint_identity={"kind": "none"},
            featurization_identity={"kind": "literal-fixture"},
            source_identity={"kind": "contract-test"},
            scale_contract={"kind": "tm-score-unit-interval"},
        ),
    ),
    bindings=(
        ExecutionBindingDefinition(
            binding_id="contract_test.multi_objective_selection_source.direct",
            version=VERSION,
            node_type=NODE_TYPE,
            method=METHOD,
            binding_parameters={},
            execution_route="direct",
            factory=LazyImplementationFactory(
                behavior=BehaviorReference(
                    "contract_test.multi_objective_selection_source/factory",
                    VERSION,
                    {},
                ),
                build=_build,
            ),
            availability=AvailabilityDeclaration(
                behavior=BehaviorReference(
                    "contract_test.multi_objective_selection_source/availability",
                    VERSION,
                    {},
                ),
                prerequisites={},
                check=AvailabilityResult.available,
            ),
            readiness=ReadinessDeclaration(
                behavior=BehaviorReference(
                    "contract_test.multi_objective_selection_source/readiness",
                    VERSION,
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
            produced_observations=(
                ProducedObservationDefinition(
                    output_port="scores",
                    metric=TM_SCORE,
                    context_profile={
                        "kind": "pairwise",
                        "subject_role": "subject",
                        "reference_role": "reference",
                        "pairing_mode": "fixed_reference",
                        "normalization": NORMALIZATION,
                    },
                    subject_grain="candidate",
                    source_role="subject",
                    subject_direction="output",
                    subject_port="candidates",
                    guaranteed_multiplicity="one",
                    output_partition=FIXED_PARTITION,
                    reference_direction="output",
                    reference_port="references",
                ),
                ProducedObservationDefinition(
                    output_port="scores",
                    metric=TM_SCORE,
                    context_profile={
                        "kind": "pairwise",
                        "subject_role": "subject",
                        "reference_role": "reference",
                        "pairing_mode": "per_subject_counterpart",
                        "normalization": NORMALIZATION,
                    },
                    subject_grain="candidate",
                    source_role="subject",
                    subject_direction="output",
                    subject_port="candidates",
                    guaranteed_multiplicity="one",
                    output_partition=PAIRED_PARTITION,
                    reference_direction="output",
                    reference_port="references",
                    pairing_direction="output",
                    pairing_port="pairing",
                ),
            ),
        ),
    ),
    utility_transforms=(
        _utility(
            "contract_test.tm_score.fixed_3gb1.identity",
            "fixed_reference",
        ),
        _utility(
            "contract_test.tm_score.paired_esm3.identity",
            "per_subject_counterpart",
        ),
    ),
)
