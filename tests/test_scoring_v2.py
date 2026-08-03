"""Ticket 10 acceptance at the agreed v2 scoring and compiler seams."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone

from fastapi.testclient import TestClient
import pytest
from starlette.websockets import WebSocketDisconnect

from core import (
    BehaviorReference,
    CatalogContract,
    FrozenCatalog,
    OperationCall,
    PortTypeDefinition,
    ReadinessDeclaration,
    ReadinessResult,
    SelectionError,
    SelectionInput,
    SelectionObjective,
    SelectionResult,
    ScientificOperationFactory,
    builtin_frozen_catalog,
    build_frozen_catalog,
    compile_workflow,
    relock_workflow,
    select_candidates,
    validate_produced_score_collection,
)
from core.port_types import PortValueError
from core.scoring_v2 import (
    ResolvedMetricFacts,
    validate_produced_score_collection_from_facts,
)
from core.server import create_app
from core.workflow_v2 import (
    WorkflowCompileError,
    WorkflowDocumentError,
    parse_workflow_document,
)
from protein_workbench_public import (
    validate_event,
    validate_response,
    validate_schema,
)
from datatypes import (
    Candidate,
    CandidateCollection,
    CandidateDataReference,
    ExactContractReference,
    IntrinsicObservationContext,
    ProteinSequence,
    ProteinStructure,
    ResidueAxisReference,
    ResidueLayout,
    ScoreCollection,
    ScoreObservation,
)
from tests.fixtures.public_v2 import wait_for_testclient_run_terminal
from modules.selection.package import MODULE_PACKAGE as SELECTION_PACKAGE
from modules.structure_prediction.port_types import CONFIDENCE_FACTS_PORT_TYPE


def _contract(
    kind: str,
    contract_id: str,
    descriptor: dict,
) -> CatalogContract:
    return CatalogContract(
        contract_kind=kind,  # type: ignore[arg-type]
        contract_id=contract_id,
        contract_version="2.1.0",
        descriptor={
            "schema_namespace": "protein-workbench-contract/v2",
            "contract_kind": kind,
            "contract_id": contract_id,
            "contract_version": "2.1.0",
            **descriptor,
        },
    )


def _scoring_catalog() -> tuple[FrozenCatalog, dict[str, CatalogContract]]:
    builtin = builtin_frozen_catalog()
    selection_catalog = build_frozen_catalog((SELECTION_PACKAGE,))
    candidates_type = builtin.require_port_type("candidate.collection", "3.0.0")
    scores_type = builtin.require_port_type("score.collection", "4.0.0")
    metric_quality = _contract(
        "metric",
        "quality",
        {
            "title": "Quality",
            "description": "Intrinsic candidate quality",
            "value_shape": "scalar",
            "unit": "dimensionless",
            "direction": "higher_is_better",
            "canonical_range": {"minimum": 0, "maximum": 100},
            "granularity": "candidate",
            "aggregation_semantics": {"kind": "none"},
            "observation_context_schema": {"kind": "intrinsic"},
            "validation_contract": {"finite": True},
        },
    )
    metric_novelty = _contract(
        "metric",
        "novelty",
        {
            **{
                key: value
                for key, value in metric_quality.descriptor.items()
                if key
                not in {
                    "contract_id",
                    "contract_kind",
                    "contract_version",
                    "schema_namespace",
                }
            },
            "title": "Novelty",
            "description": "Intrinsic candidate novelty",
        },
    )
    method_a = _contract(
        "method",
        "method.a",
        {
            "algorithm_identity": {"name": "algorithm-a"},
            "model_identity": {"name": "model-a"},
            "checkpoint_identity": {"kind": "none"},
            "featurization_identity": {"name": "features-a"},
            "source_identity": {"name": "fixture"},
            "scale_contract": {"kind": "canonical"},
        },
    )
    method_b = _contract(
        "method",
        "method.b",
        {
            **{
                key: value
                for key, value in method_a.descriptor.items()
                if key
                not in {
                    "contract_id",
                    "contract_kind",
                    "contract_version",
                    "schema_namespace",
                }
            },
            "algorithm_identity": {"name": "algorithm-b"},
            "model_identity": {"name": "model-b"},
        },
    )
    linear_quality = _contract(
        "utility_transform",
        "quality.linear",
        {
            "compatible_input_contract": {
                "metric": metric_quality.reference(),
                "method": method_a.reference(),
                "context_profile": {"kind": "intrinsic"},
            },
            "parameters": {
                "lower": {
                    "value_contract": {"type": "number"},
                    "default": 0,
                },
                "upper": {
                    "value_contract": {"type": "number"},
                    "default": 100,
                },
            },
            "behavior": {
                "behavior_id": "quality.linear/transform",
                "behavior_version": "2.1.0",
                "parameters": {},
            },
            "output_contract": {"minimum": 0, "maximum": 1},
        },
    )
    linear_novelty = _contract(
        "utility_transform",
        "novelty.linear",
        {
            "compatible_input_contract": {
                "metric": metric_novelty.reference(),
                "method": method_a.reference(),
                "context_profile": {"kind": "intrinsic"},
            },
            "parameters": {
                "lower": {
                    "value_contract": {"type": "number"},
                    "default": 0,
                },
                "upper": {
                    "value_contract": {"type": "number"},
                    "default": 100,
                },
            },
            "behavior": {
                "behavior_id": "novelty.linear/transform",
                "behavior_version": "2.1.0",
                "parameters": {},
            },
            "output_contract": {"minimum": 0, "maximum": 1},
        },
    )
    source_node = _contract(
        "node_type",
        "candidate.source",
        {
            "title": "Candidate source",
            "summary": "Produces admitted fixture Candidates.",
            "category": "input",
            "inputs": [],
            "outputs": [
                {
                    "name": "candidates",
                    "port_type": candidates_type.reference(),
                    "required": True,
                    "multiplicity": "one",
                    "scientific_meaning": "Admitted scoring subjects.",
                }
            ],
            "parameter_groups": [],
            "node_parameters": {},
        },
    )
    source_binding = _contract(
        "binding",
        "candidate.source.direct",
        {
            "node_type": source_node.reference(),
            "method": method_a.reference(),
            "binding_parameters": {},
            "execution_route": "direct",
            "route_behavior": {
                "behavior_id": "candidate.source/execute",
                "behavior_version": "2.1.0",
                "parameters": {},
            },
            "availability_declaration": {
                "behavior": {
                    "behavior_id": "candidate.source/availability",
                    "behavior_version": "2.1.0",
                    "parameters": {},
                },
                "prerequisites": {},
            },
            "readiness_declaration": {
                "behavior": {
                    "behavior_id": "candidate.source/readiness",
                    "behavior_version": "2.1.0",
                    "parameters": {},
                },
                "prerequisites": {},
            },
            "deterministic": True,
            "cacheable": True,
            "implementation_identity": {"name": "candidate.source.direct"},
            "produced_observations": [],
        },
    )
    producer_node = _contract(
        "node_type",
        "score.intrinsic",
        {
            "title": "Intrinsic scorer",
            "summary": "Produces fixed intrinsic observations.",
            "category": "evaluation",
            "inputs": [
                {
                    "name": "candidates",
                    "port_type": candidates_type.reference(),
                    "required": True,
                    "multiplicity": "one",
                    "scientific_meaning": "Admitted Candidates to score.",
                }
            ],
            "outputs": [
                {
                    "name": "scores",
                    "port_type": scores_type.reference(),
                    "required": True,
                    "multiplicity": "one",
                    "scientific_meaning": "Typed intrinsic observations.",
                },
            ],
            "parameter_groups": [],
            "node_parameters": {},
        },
    )
    producer_binding = _contract(
        "binding",
        "score.intrinsic.direct",
        {
            "node_type": producer_node.reference(),
            "method": method_a.reference(),
            "binding_parameters": {},
            "execution_route": "direct",
            "route_behavior": {
                "behavior_id": "score.intrinsic/execute",
                "behavior_version": "2.1.0",
                "parameters": {},
            },
            "availability_declaration": {
                "behavior": {
                    "behavior_id": "score.intrinsic/availability",
                    "behavior_version": "2.1.0",
                    "parameters": {},
                },
                "prerequisites": {},
            },
            "readiness_declaration": {
                "behavior": {
                    "behavior_id": "score.intrinsic/readiness",
                    "behavior_version": "2.1.0",
                    "parameters": {},
                },
                "prerequisites": {},
            },
            "deterministic": True,
            "cacheable": True,
            "implementation_identity": {"name": "score.intrinsic.direct"},
            "produced_observations": [
                {
                    "output_port": "scores",
                    "metric": metric_quality.reference(),
                    "context_profile": {"kind": "intrinsic"},
                    "subject_grain": "candidate",
                    "source_role": "subject",
                    "subject_direction": "input",
                    "subject_port": "candidates",
                    "guaranteed_multiplicity": "one",
                },
                {
                    "output_port": "scores",
                    "metric": metric_novelty.reference(),
                    "context_profile": {"kind": "intrinsic"},
                    "subject_grain": "candidate",
                    "source_role": "subject",
                    "subject_direction": "input",
                    "subject_port": "candidates",
                    "guaranteed_multiplicity": "one",
                },
            ],
        },
    )
    contracts = {
        contract.contract_id: contract
        for contract in (
            metric_quality,
            metric_novelty,
            method_a,
            method_b,
            linear_quality,
            linear_novelty,
            source_node,
            source_binding,
            producer_node,
            producer_binding,
        )
    }

    def linear(value: object, parameters: dict) -> float:
        numeric = float(value)
        return (numeric - parameters["lower"]) / (
            parameters["upper"] - parameters["lower"]
        )

    factory_behavior = BehaviorReference(
        "score.intrinsic/execute",
        "2.1.0",
        {},
    )
    readiness_behavior = BehaviorReference(
        "score.intrinsic/readiness",
        "2.1.0",
        {},
    )
    source_factory_behavior = BehaviorReference(
        "candidate.source/execute",
        "2.1.0",
        {},
    )
    source_readiness_behavior = BehaviorReference(
        "candidate.source/readiness",
        "2.1.0",
        {},
    )

    class CandidateSourceImplementation:
        def execute(self, call: OperationCall) -> dict:
            assert call.inputs == {}
            return {
                "candidates": CandidateCollection(
                    "raw-candidates",
                    "protein.sequence",
                    [
                        Candidate("raw-1", ProteinSequence("AA")),
                        Candidate("raw-2", ProteinSequence("GG")),
                    ],
                )
            }

    class ScoringImplementation:
        def execute(self, call: OperationCall) -> dict:
            assert call.node_parameters == {}
            assert call.binding_parameters == {}
            candidates = call.inputs["candidates"]
            assert type(candidates) is CandidateCollection
            admitted = call.input_content_digests["candidates"].candidate_data
            assert len(admitted) == 2
            first, second = candidates.items
            first_ref, second_ref = admitted
            return {
                "scores": ScoreCollection(
                    "raw-scores",
                    [
                        replace(
                            _observation(
                                contracts, first.candidate_id, 20
                            ),
                            subject=first_ref,
                        ),
                        replace(
                            _observation(
                                contracts, second.candidate_id, 90
                            ),
                            subject=second_ref,
                        ),
                        replace(
                            _observation(
                                contracts,
                                first.candidate_id,
                                80,
                                metric="novelty",
                            ),
                            subject=first_ref,
                        ),
                        replace(
                            _observation(
                                contracts,
                                second.candidate_id,
                                40,
                                metric="novelty",
                            ),
                            subject=second_ref,
                        ),
                    ],
                ),
            }

    catalog = FrozenCatalog(
        builtin.port_types,
        contracts=(
            *contracts.values(),
            *selection_catalog.contracts,
        ),
        availability=(
            {
                "binding": source_binding.reference(),
                "observed_at": "2026-07-29T06:00:00Z",
                "available": True,
            },
            {
                "binding": producer_binding.reference(),
                "observed_at": "2026-07-29T06:00:00Z",
                "available": True,
            },
            *selection_catalog.availability,
        ),
        availability_observed_at=datetime(
            2026,
            7,
            29,
            6,
            tzinfo=timezone.utc,
        ),
        utility_transforms={
            ("quality.linear", "2.1.0"): linear,
            ("novelty.linear", "2.1.0"): linear,
        },
        factories={
            **dict(selection_catalog.factories),
            ("candidate.source.direct", "2.1.0"): (
                ScientificOperationFactory(
                    behavior=source_factory_behavior,
                    build=lambda _: CandidateSourceImplementation(),
                )
            ),
            ("score.intrinsic.direct", "2.1.0"): (
                ScientificOperationFactory(
                    behavior=factory_behavior,
                    build=lambda _: ScoringImplementation(),
                )
            )
        },
        readiness_declarations={
            **dict(selection_catalog.readiness_declarations),
            ("candidate.source.direct", "2.1.0"): ReadinessDeclaration(
                behavior=source_readiness_behavior,
                prerequisites={},
                check=lambda _: ReadinessResult(True),
            ),
            ("score.intrinsic.direct", "2.1.0"): ReadinessDeclaration(
                behavior=readiness_behavior,
                prerequisites={},
                check=lambda _: ReadinessResult(True),
            )
        },
    )
    return catalog, contracts


def _dynamic_observation_method_catalog(
) -> tuple[FrozenCatalog, dict[str, CatalogContract]]:
    catalog, contracts = _scoring_catalog()
    candidates_type = catalog.require_port_type("candidate.collection", "3.0.0")
    scores_type = catalog.require_port_type("score.collection", "4.0.0")
    facts_type = CONFIDENCE_FACTS_PORT_TYPE
    generation_node = _contract(
        "node_type",
        "generation.confidence_facts",
        {
            "title": "Confidence fact generation",
            "summary": "Produces method-bearing confidence facts.",
            "category": "generation",
            "inputs": [
                {
                    "name": "candidates",
                    "port_type": candidates_type.reference(),
                    "required": True,
                    "multiplicity": "one",
                    "scientific_meaning": "Candidates to evaluate.",
                }
            ],
            "outputs": [
                {
                    "name": "facts",
                    "port_type": facts_type.reference(),
                    "required": True,
                    "multiplicity": "one",
                    "scientific_meaning": (
                        "Confidence facts produced by the generation Method."
                    ),
                }
            ],
            "parameter_groups": [],
            "node_parameters": {},
        },
    )
    generation_binding = _contract(
        "binding",
        "generation.confidence_facts.method_a",
        {
            "node_type": generation_node.reference(),
            "method": contracts["method.a"].reference(),
            "binding_parameters": {},
            "execution_route": "direct",
            "route_behavior": {
                "behavior_id": "generation.confidence_facts/execute",
                "behavior_version": "2.1.0",
                "parameters": {},
            },
            "availability_declaration": {
                "behavior": {
                    "behavior_id": "generation.confidence_facts/availability",
                    "behavior_version": "2.1.0",
                    "parameters": {},
                },
                "prerequisites": {},
            },
            "readiness_declaration": {
                "behavior": {
                    "behavior_id": "generation.confidence_facts/readiness",
                    "behavior_version": "2.1.0",
                    "parameters": {},
                },
                "prerequisites": {},
            },
            "deterministic": True,
            "cacheable": True,
            "implementation_identity": {
                "name": "generation.confidence_facts.method_a"
            },
            "produced_observations": [],
        },
    )
    materializer_node = _contract(
        "node_type",
        "score.materialize_confidence",
        {
            "title": "Confidence materializer",
            "summary": "Materializes confidence facts as observations.",
            "category": "evaluation",
            "inputs": [
                {
                    "name": "candidates",
                    "port_type": candidates_type.reference(),
                    "required": True,
                    "multiplicity": "one",
                    "scientific_meaning": "Candidates described by the facts.",
                },
                {
                    "name": "facts",
                    "port_type": facts_type.reference(),
                    "required": True,
                    "multiplicity": "one",
                    "scientific_meaning": "Method-bearing confidence facts.",
                },
            ],
            "outputs": [
                {
                    "name": "scores",
                    "port_type": scores_type.reference(),
                    "required": True,
                    "multiplicity": "one",
                    "scientific_meaning": "Materialized confidence observations.",
                }
            ],
            "parameter_groups": [],
            "node_parameters": {},
        },
    )
    materializer_binding = _contract(
        "binding",
        "score.materialize_confidence.method_b",
        {
            "node_type": materializer_node.reference(),
            "method": contracts["method.b"].reference(),
            "binding_parameters": {},
            "execution_route": "direct",
            "route_behavior": {
                "behavior_id": "score.materialize_confidence/execute",
                "behavior_version": "2.1.0",
                "parameters": {},
            },
            "availability_declaration": {
                "behavior": {
                    "behavior_id": "score.materialize_confidence/availability",
                    "behavior_version": "2.1.0",
                    "parameters": {},
                },
                "prerequisites": {},
            },
            "readiness_declaration": {
                "behavior": {
                    "behavior_id": "score.materialize_confidence/readiness",
                    "behavior_version": "2.1.0",
                    "parameters": {},
                },
                "prerequisites": {},
            },
            "deterministic": True,
            "cacheable": True,
            "implementation_identity": {
                "name": "score.materialize_confidence.method_b"
            },
            "produced_observations": [
                {
                    "output_port": "scores",
                    "metric": contracts["quality"].reference(),
                    "context_profile": {"kind": "intrinsic"},
                    "subject_grain": "candidate",
                    "source_role": "subject",
                    "subject_direction": "input",
                    "subject_port": "candidates",
                    "guaranteed_multiplicity": "one",
                    "method_direction": "input",
                    "method_port": "facts",
                }
            ],
        },
    )
    added_contracts = (
        generation_node,
        generation_binding,
        materializer_node,
        materializer_binding,
    )
    contracts.update(
        {contract.contract_id: contract for contract in added_contracts}
    )

    class CompileOnlyImplementation:
        def execute(self, call: OperationCall) -> dict:
            del call
            raise AssertionError("dynamic Method fixture is compiler-only")

    def compile_only_factory(binding: CatalogContract):
        behavior = binding.descriptor["route_behavior"]
        return ScientificOperationFactory(
            behavior=BehaviorReference(
                behavior["behavior_id"],
                behavior["behavior_version"],
                behavior["parameters"],
            ),
            build=lambda _: CompileOnlyImplementation(),
        )

    def compile_only_readiness(binding: CatalogContract):
        behavior = binding.descriptor["readiness_declaration"]["behavior"]
        return ReadinessDeclaration(
            behavior=BehaviorReference(
                behavior["behavior_id"],
                behavior["behavior_version"],
                behavior["parameters"],
            ),
            prerequisites={},
            check=lambda _: ReadinessResult(True),
        )

    catalog = replace(
        catalog,
        port_types=(*catalog.port_types, facts_type),
        contracts=(*catalog.contracts, *added_contracts),
        availability=(
            *catalog.availability,
            *(
                {
                    "binding": binding.reference(),
                    "observed_at": "2026-08-03T00:00:00Z",
                    "available": True,
                }
                for binding in (generation_binding, materializer_binding)
            ),
        ),
        factories={
            **dict(catalog.factories),
            (generation_binding.contract_id, "2.1.0"): (
                compile_only_factory(generation_binding)
            ),
            (materializer_binding.contract_id, "2.1.0"): (
                compile_only_factory(materializer_binding)
            ),
        },
        readiness_declarations={
            **dict(catalog.readiness_declarations),
            (generation_binding.contract_id, "2.1.0"): (
                compile_only_readiness(generation_binding)
            ),
            (materializer_binding.contract_id, "2.1.0"): (
                compile_only_readiness(materializer_binding)
            ),
        },
    )
    return catalog, contracts


def _reference(contract: CatalogContract) -> ExactContractReference:
    reference = contract.reference()
    return ExactContractReference(
        contract_kind=reference["contract_kind"],
        contract_id=reference["contract_id"],
        contract_version=reference["contract_version"],
        contract_digest=reference["contract_digest"],
    )


def _observation(
    contracts: dict[str, CatalogContract],
    candidate_id: str,
    value: float,
    *,
    metric: str = "quality",
    method: str = "method.a",
) -> ScoreObservation:
    sequence = (
        "GG" if candidate_id in {"raw-2", "candidate-2"} else "AA"
    )
    sequence_type = builtin_frozen_catalog().require_port_type(
        "protein.sequence",
        "3.0.0",
    )
    return ScoreObservation(
        subject=CandidateDataReference(
            candidate_id,
            "protein.sequence",
            sequence_type.content_digest(ProteinSequence(sequence)),
        ),
        metric=_reference(contracts[metric]),
        method=_reference(contracts[method]),
        context=IntrinsicObservationContext(),
        value=value,
    )


def test_observation_identity_excludes_value_and_distinguishes_metric_and_method() -> None:
    _, contracts = _scoring_catalog()
    first = _observation(contracts, "candidate-1", 90)

    assert replace(first, value=10).identity == first.identity
    assert (
        _observation(
            contracts,
            "candidate-1",
            90,
            metric="novelty",
        ).identity
        != first.identity
    )
    assert (
        _observation(
            contracts,
            "candidate-1",
            90,
            method="method.b",
        ).identity
        != first.identity
    )


def test_score_collection_codec_deduplicates_equal_observations_and_fails_closed() -> None:
    catalog, contracts = _scoring_catalog()
    score_type = catalog.require_port_type("score.collection", "4.0.0")
    observation = _observation(contracts, "candidate-1", 90)

    encoded = score_type.encode(
        ScoreCollection("scores", [observation, observation])
    )
    decoded = score_type.decode(encoded)
    assert decoded.entries == (observation,)

    with pytest.raises(PortValueError, match="conflicting values"):
        score_type.encode(
            ScoreCollection(
                "scores",
                [observation, replace(observation, value=10)],
            )
        )

    with pytest.raises(PortValueError, match="partition collision"):
        score_type.encode(
            ScoreCollection(
                "scores",
                [
                    observation,
                    replace(observation, source_partition="other"),
                ],
            )
        )

    with pytest.raises(PortValueError, match="conflicting values"):
        score_type.encode(
            ScoreCollection(
                "scores",
                [
                    observation,
                    replace(
                        observation,
                        source_partition="other",
                        value=10,
                    ),
                ],
            )
        )


def test_selection_rejects_one_observation_identity_in_two_partitions() -> None:
    catalog, contracts = _scoring_catalog()
    candidate_input = SelectionInput("producer", "candidates")
    score_input = SelectionInput("producer", "scores")
    observation = _observation(contracts, "candidate-1", 90)

    with pytest.raises(SelectionError, match="partition collision"):
        select_candidates(
            candidate_inputs={
                candidate_input: CandidateCollection(
                    "candidates",
                    "protein.sequence",
                    [Candidate("candidate-1", ProteinSequence("AA"))],
                )
            },
            score_collection_inputs={
                score_input: ScoreCollection(
                    "scores",
                    [
                        observation,
                        replace(observation, source_partition="other"),
                    ],
                )
            },
            objectives=(
                SelectionObjective(
                    objective_id="quality-objective",
                    candidate_input=candidate_input,
                    score_collection_input=score_input,
                    metric=_reference(contracts["quality"]),
                    method=_reference(contracts["method.a"]),
                    context_selector=IntrinsicObservationContext(),
                    utility_transform=_reference(
                        contracts["quality.linear"]
                    ),
                    utility_parameters={},
                    weight=1,
                ),
            ),
            catalog=catalog,
            limit=1,
        )


def test_score_collection_codec_enforces_metric_and_method_reference_roles() -> None:
    catalog, contracts = _scoring_catalog()
    score_type = catalog.require_port_type("score.collection", "4.0.0")
    malformed = replace(
        _observation(contracts, "candidate-1", 90),
        metric=_reference(contracts["method.a"]),
    )

    with pytest.raises(PortValueError, match="metric reference"):
        score_type.encode(ScoreCollection("scores", [malformed]))


def test_binding_output_obeys_exact_method_metric_context_and_multiplicity() -> None:
    catalog, contracts = _scoring_catalog()
    binding = contracts["score.intrinsic.direct"]
    candidates = CandidateCollection(
        "candidates",
        "protein.sequence",
        [Candidate("candidate-1", ProteinSequence("AA"))],
    )
    scores = ScoreCollection(
        "scores",
        [
            _observation(contracts, "candidate-1", 90),
            _observation(
                contracts,
                "candidate-1",
                25,
                metric="novelty",
            ),
        ],
    )

    validate_produced_score_collection(
        catalog=catalog,
        binding=binding,
        output_port="scores",
        collection=scores,
        inputs={"candidates": candidates},
        outputs={"scores": scores},
    )

    with pytest.raises(PortValueError, match="guaranteed one"):
        validate_produced_score_collection(
            catalog=catalog,
            binding=binding,
            output_port="scores",
            collection=ScoreCollection(
                "scores",
                [_observation(contracts, "candidate-1", 90)],
            ),
            inputs={"candidates": candidates},
            outputs={},
        )
    with pytest.raises(PortValueError, match="undeclared Method"):
        validate_produced_score_collection(
            catalog=catalog,
            binding=binding,
            output_port="scores",
            collection=ScoreCollection(
                "scores",
                [
                    _observation(
                        contracts,
                        "candidate-1",
                        90,
                        method="method.b",
                    )
                ],
            ),
            inputs={"candidates": candidates},
            outputs={},
        )


def test_binding_output_uses_exact_subject_source_and_rejects_ghosts() -> None:
    catalog, contracts = _scoring_catalog()
    binding = contracts["score.intrinsic.direct"]
    candidates = CandidateCollection(
        "candidates",
        "protein.sequence",
        [Candidate("candidate-1", ProteinSequence("AA"))],
    )
    valid_scores = ScoreCollection(
        "scores",
        [
            _observation(contracts, "candidate-1", 90),
            _observation(
                contracts,
                "candidate-1",
                20,
                metric="novelty",
            ),
        ],
    )
    validate_produced_score_collection(
        catalog=catalog,
        binding=binding,
        output_port="scores",
        collection=valid_scores,
        inputs={"candidates": candidates},
        outputs={"scores": valid_scores},
    )

    ghost_scores = ScoreCollection(
        "scores",
        [
            _observation(contracts, "candidate-ghost", 90),
            _observation(
                contracts,
                "candidate-ghost",
                20,
                metric="novelty",
            ),
        ],
    )
    with pytest.raises(PortValueError, match="exact subject"):
        validate_produced_score_collection(
            catalog=catalog,
            binding=binding,
            output_port="scores",
            collection=ghost_scores,
            inputs={"candidates": candidates},
            outputs={"scores": ghost_scores},
        )


def test_binding_output_validates_per_residue_shape_range_and_masking() -> None:
    catalog, contracts = _scoring_catalog()
    residue_metric = _contract(
        "metric",
        "residue.quality",
        {
            "title": "Residue quality",
            "description": "Per-residue quality with explicit null masking.",
            "value_shape": "per_residue",
            "unit": "dimensionless",
            "direction": "higher_is_better",
            "canonical_range": {"minimum": 0, "maximum": 100},
            "granularity": "residue",
            "aggregation_semantics": {"kind": "none"},
            "observation_context_schema": {"kind": "intrinsic"},
            "validation_contract": {
                "finite": True,
                "masking": {"allow_null": True},
            },
        },
    )
    axis_holder: dict[str, ResidueAxisReference] = {}
    axis_type = PortTypeDefinition(
        type_id="fixture.prediction_residue_axis",
        version="1.0.0",
        validator=BehaviorReference(
            "fixture.prediction_residue_axis/validate",
            "1.0.0",
            {"accepted_value_kind": "prediction_residue_axis"},
        ),
        codec=BehaviorReference(
            "fixture.prediction_residue_axis/codec",
            "1.0.0",
            {"canonicalization": "RFC 8785"},
        ),
        content_identity=BehaviorReference(
            "fixture.prediction_residue_axis/content",
            "1.0.0",
            {"digest": "SHA-256"},
        ),
        scientific_axis_projection=BehaviorReference(
            "fixture.prediction_residue_axis/project",
            "1.0.0",
            {"projection": "one-exact-axis"},
        ),
        runtime_scientific_axis_projection=lambda _: (
            axis_holder["axis"],
        ),
        runtime_validator=lambda _: None,
        runtime_to_wire=lambda value: value,
        runtime_from_wire=lambda value: value,
    )
    original_node = contracts["score.intrinsic"].public_contract()[
        "descriptor"
    ]
    residue_node = _contract(
        "node_type",
        "score.residue",
        {
            key: value
            for key, value in original_node.items()
            if key
            not in {
                "contract_kind",
                "contract_id",
                "contract_version",
                "schema_namespace",
                "inputs",
            }
        }
        | {
            "inputs": [
                {
                    "name": "residue_axis",
                    "port_type": axis_type.reference(),
                    "required": True,
                    "multiplicity": "one",
                    "scientific_meaning": "Exact prediction residue axis.",
                }
            ]
        },
    )
    original = contracts["score.intrinsic.direct"].public_contract()[
        "descriptor"
    ]
    residue_binding = _contract(
        "binding",
        "score.residue.direct",
        {
            key: value
            for key, value in original.items()
            if key
            not in {
                "contract_kind",
                "contract_id",
                "contract_version",
                "schema_namespace",
                "produced_observations",
                "node_type",
            }
        }
        | {
            "node_type": residue_node.reference(),
            "produced_observations": [
                {
                    "output_port": "scores",
                    "metric": residue_metric.reference(),
                    "context_profile": {"kind": "intrinsic"},
                    "subject_grain": "candidate",
                    "source_role": "subject",
                    "subject_direction": "output",
                    "subject_port": "candidates",
                    "axis_direction": "input",
                    "axis_port": "residue_axis",
                    "guaranteed_multiplicity": "one",
                }
            ]
        },
    )
    residue_catalog = replace(
        catalog,
        port_types=(*catalog.port_types, axis_type),
        contracts=(
            *catalog.contracts,
            residue_metric,
            residue_node,
            residue_binding,
        ),
    )
    candidates = CandidateCollection(
        "candidates",
        "protein.sequence",
        [Candidate("candidate-1", ProteinSequence("AAA"))],
    )
    sequence_type = residue_catalog.require_port_type(
        "protein.sequence", "3.0.0"
    )
    subject = CandidateDataReference(
        "candidate-1",
        "protein.sequence",
        sequence_type.content_digest(candidates.items[0].data),
    )
    axis_reference = axis_type.reference()
    axis_holder["axis"] = ResidueAxisReference(
        axis_kind="prediction_input",
        axis_contract=ExactContractReference(**axis_reference),
        axis_content_digest="sha256:" + ("a" * 64),
        source=subject,
        layout=ResidueLayout(
            "A",
            3,
            ("A:1", "A:2", "A:3"),
        ),
    )
    observation = ScoreObservation(
        subject=subject,
        metric=_reference(residue_metric),
        method=_reference(contracts["method.a"]),
        context=IntrinsicObservationContext(),
        value=[80, None, 95],
        residue_axis=axis_holder["axis"],
    )
    scores = ScoreCollection("scores", [observation])

    validate_produced_score_collection(
        catalog=residue_catalog,
        binding=residue_binding,
        output_port="scores",
        collection=scores,
        inputs={"residue_axis": "fixture-axis"},
        outputs={"candidates": candidates, "scores": scores},
    )

    with pytest.raises(PortValueError, match="canonical range"):
        validate_produced_score_collection(
            catalog=residue_catalog,
            binding=residue_binding,
            output_port="scores",
            collection=ScoreCollection(
                "scores",
                [replace(observation, value=[80, None, 101])],
            ),
            inputs={"residue_axis": "fixture-axis"},
            outputs={"candidates": candidates},
        )
    with pytest.raises(PortValueError, match="exact residue layout"):
        validate_produced_score_collection(
            catalog=residue_catalog,
            binding=residue_binding,
            output_port="scores",
            collection=ScoreCollection(
                "scores",
                [replace(observation, value=[80, 95])],
            ),
            inputs={"residue_axis": "fixture-axis"},
            outputs={"candidates": candidates},
        )
    with pytest.raises(PortValueError, match="does not resolve exactly once"):
        validate_produced_score_collection(
            catalog=residue_catalog,
            binding=residue_binding,
            output_port="scores",
            collection=ScoreCollection(
                "scores",
                [replace(observation, residue_axis=None)],
            ),
            inputs={"residue_axis": "fixture-axis"},
            outputs={"candidates": candidates},
        )
    wrong_subject = CandidateDataReference(
        "candidate-1",
        "protein.sequence",
        "sha256:" + ("f" * 64),
    )
    with pytest.raises(PortValueError, match="exact subject"):
        validate_produced_score_collection(
            catalog=residue_catalog,
            binding=residue_binding,
            output_port="scores",
            collection=ScoreCollection(
                "scores",
                [replace(observation, subject=wrong_subject)],
            ),
            inputs={"residue_axis": "fixture-axis"},
            outputs={"candidates": candidates},
        )


def test_modified_polymer_axis_length_does_not_use_raw_atom_record_count() -> None:
    metric = ExactContractReference(
        "metric", "residue.quality", "1.0.0", "sha256:" + ("1" * 64)
    )
    method = ExactContractReference(
        "method", "fixture", "1.0.0", "sha256:" + ("2" * 64)
    )
    subject = CandidateDataReference(
        "structure-1", "protein.structure", "sha256:" + ("3" * 64)
    )
    structure = Candidate(
        "structure-1",
        ProteinStructure(
            "ATOM      1  CA  ALA A   1      0.000   0.000   0.000\n"
            "HETATM    2  CA  MSE A   2      1.000   0.000   0.000\n"
            "ATOM      3  CA  GLY A   3      2.000   0.000   0.000\nEND"
        ),
    )
    axis = ResidueAxisReference(
        axis_kind="resolved_structure",
        axis_contract=ExactContractReference(
            "port_type",
            "structure_transform.resolved_residue_axis",
            "4.0.0",
            "sha256:" + ("4" * 64),
        ),
        axis_content_digest="sha256:" + ("5" * 64),
        source=subject,
        layout=ResidueLayout("A", 3, ("A:1", "A:2", "A:3")),
    )
    observation = ScoreObservation(
        subject=subject,
        metric=metric,
        method=method,
        context=IntrinsicObservationContext(),
        value=[80, 90, 95],
        residue_axis=axis,
    )
    collection = ScoreCollection("scores", [observation])
    reference = lambda item: {
        "contract_kind": item.contract_kind,
        "contract_id": item.contract_id,
        "contract_version": item.contract_version,
        "contract_digest": item.contract_digest,
    }
    validate_produced_score_collection_from_facts(
        binding_descriptor={
            "method": reference(method),
            "produced_observations": [
                {
                    "output_port": "scores",
                    "metric": reference(metric),
                    "context_profile": {"kind": "intrinsic"},
                    "subject_grain": "candidate",
                    "source_role": "subject",
                    "subject_direction": "input",
                    "subject_port": "structures",
                    "axis_direction": "input",
                    "axis_port": "axes",
                    "guaranteed_multiplicity": "one",
                }
            ],
        },
        output_port="scores",
        collection=collection,
        inputs={
            "structures": CandidateCollection(
                "structures", "protein.structure", [structure]
            ),
            "axes": "axis",
        },
        outputs={"scores": collection},
        metric_facts={
            (
                metric.contract_kind,
                metric.contract_id,
                metric.contract_version,
                metric.contract_digest,
            ): ResolvedMetricFacts(
                metric,
                "per_residue",
                0,
                100,
                False,
                True,
                False,
                True,
            )
        },
        axis_references={("input", "axes"): (axis,)},
        method_references={},
        candidate_references={("input", "structures"): (subject,)},
    )


def test_explicit_utilities_normalize_weights_and_record_provenance() -> None:
    catalog, contracts = _scoring_catalog()
    candidates = CandidateCollection(
        "candidates",
        "protein.sequence",
        [
            Candidate("candidate-1", ProteinSequence("AA")),
            Candidate("candidate-2", ProteinSequence("GG")),
        ],
    )
    scores = ScoreCollection(
        "scores",
        [
            _observation(contracts, "candidate-1", 90),
            _observation(contracts, "candidate-2", 70),
            _observation(
                contracts,
                "candidate-1",
                20,
                metric="novelty",
            ),
            _observation(
                contracts,
                "candidate-2",
                80,
                metric="novelty",
            ),
        ],
    )
    candidate_input = SelectionInput("producer", "candidates")
    score_input = SelectionInput("producer", "scores")
    objectives = (
        SelectionObjective(
            objective_id="quality-objective",
            candidate_input=candidate_input,
            score_collection_input=score_input,
            metric=_reference(contracts["quality"]),
            method=_reference(contracts["method.a"]),
            context_selector=IntrinsicObservationContext(),
            utility_transform=_reference(contracts["quality.linear"]),
            utility_parameters={},
            weight=3,
        ),
        SelectionObjective(
            objective_id="novelty-objective",
            candidate_input=candidate_input,
            score_collection_input=score_input,
            metric=_reference(contracts["novelty"]),
            method=_reference(contracts["method.a"]),
            context_selector=IntrinsicObservationContext(),
            utility_transform=_reference(contracts["novelty.linear"]),
            utility_parameters={},
            weight=1,
        ),
    )

    result = select_candidates(
        candidate_inputs={candidate_input: candidates},
        score_collection_inputs={score_input: scores},
        objectives=objectives,
        catalog=catalog,
        limit=2,
    )

    assert [item.candidate_id for item in result.candidates.items] == [
        "candidate-1",
        "candidate-2",
    ]
    assert result.public_provenance()["objectives"] == [
            {
                "objective_id": "quality-objective",
                "candidate_input": candidate_input.to_public(),
                "score_collection_input": score_input.to_public(),
                "source_partition": "default",
                "metric": contracts["quality"].reference(),
            "method": contracts["method.a"].reference(),
            "context_selector": {"kind": "intrinsic"},
            "utility_transform": contracts["quality.linear"].reference(),
            "utility_parameters": {"lower": 0, "upper": 100},
            "declared_weight": 3,
            "effective_weight": 0.75,
            "match_cardinality": "exactly_one",
            "missing_policy": "error",
        },
            {
                "objective_id": "novelty-objective",
                "candidate_input": candidate_input.to_public(),
                "score_collection_input": score_input.to_public(),
                "source_partition": "default",
                "metric": contracts["novelty"].reference(),
            "method": contracts["method.a"].reference(),
            "context_selector": {"kind": "intrinsic"},
            "utility_transform": contracts["novelty.linear"].reference(),
            "utility_parameters": {"lower": 0, "upper": 100},
            "declared_weight": 1,
            "effective_weight": 0.25,
            "match_cardinality": "exactly_one",
            "missing_policy": "error",
        },
    ]


def test_selection_result_defensively_freezes_all_provenance_paths() -> None:
    candidates = CandidateCollection(
        "selected",
        "protein.sequence",
        [Candidate("candidate-1", ProteinSequence("AA"))],
    )
    source = {"objectives": [{"parameters": [1]}]}

    result = SelectionResult(candidates, source)
    source["objectives"][0]["parameters"].append(2)
    first_public = result.public_provenance()
    first_public["objectives"][0]["parameters"].append(3)

    assert result.public_provenance() == {
        "objectives": [{"parameters": [1]}]
    }


def test_unselected_collection_cannot_override_pairwise_subject_digest() -> None:
    from core import PairwiseContextSelector
    from datatypes import (
        PairwiseObservationContext,
        PairwiseParticipant,
    )
    from tests.test_pairwise_scoring_v2 import (
        _pairwise_catalog,
        _reference_from_contract,
    )

    catalog, contracts = _pairwise_catalog()
    selected_input = SelectionInput("selected", "candidates")
    unselected_input = SelectionInput("unselected", "candidates")
    score_input = SelectionInput("scorer", "scores")
    selected = Candidate("subject", ProteinSequence("AA"))
    conflicting = Candidate("subject", ProteinSequence("GG"))
    reference = Candidate("reference", ProteinSequence("AG"))
    sequence_type = catalog.require_port_type("protein.sequence", "3.0.0")
    scores = ScoreCollection(
        "scores",
        [
            ScoreObservation(
                subject=CandidateDataReference(
                    "subject",
                    "protein.sequence",
                    sequence_type.content_digest(conflicting.data),
                ),
                metric=_reference_from_contract(
                    contracts["structure.tm_score"]
                ),
                method=_reference_from_contract(contracts["tm-align"]),
                context=PairwiseObservationContext(
                    subject=PairwiseParticipant(
                        role="subject",
                        candidate=CandidateDataReference(
                            "subject",
                            "protein.sequence",
                            sequence_type.content_digest(conflicting.data),
                        ),
                    ),
                    reference=PairwiseParticipant(
                        role="reference",
                        candidate=CandidateDataReference(
                            "reference",
                            "protein.sequence",
                            sequence_type.content_digest(reference.data),
                        ),
                    ),
                    pairing_mode="fixed_reference",
                    normalization="tm-score/reference-length",
                ),
                value=0.8,
                source_partition="fixed-reference",
            )
        ],
    )
    objective = SelectionObjective(
        objective_id="pairwise",
        candidate_input=selected_input,
        score_collection_input=score_input,
        metric=_reference_from_contract(contracts["structure.tm_score"]),
        method=_reference_from_contract(contracts["tm-align"]),
        context_selector=PairwiseContextSelector(
            pairing_mode="fixed_reference",
            normalization="tm-score/reference-length",
        ),
        utility_transform=_reference_from_contract(
            contracts["tm-score.fixed"]
        ),
        utility_parameters={},
        weight=1,
        source_partition="fixed-reference",
    )

    with pytest.raises(SelectionError, match="exact Candidate"):
        select_candidates(
            candidate_inputs={
                selected_input: CandidateCollection(
                    "selected",
                    "protein.sequence",
                    [selected],
                ),
                unselected_input: CandidateCollection(
                    "unselected",
                    "protein.sequence",
                    [conflicting],
                ),
            },
            score_collection_inputs={score_input: scores},
            objectives=(objective,),
            catalog=catalog,
            limit=1,
        )


@pytest.mark.parametrize("weight", [-1, -0.0, float("inf"), float("nan")])
def test_objective_rejects_negative_or_non_finite_weight(weight: float) -> None:
    _, contracts = _scoring_catalog()
    with pytest.raises(SelectionError, match="finite and strictly positive"):
        SelectionObjective(
            objective_id="quality-objective",
            candidate_input=SelectionInput("producer", "candidates"),
            score_collection_input=SelectionInput("producer", "scores"),
            metric=_reference(contracts["quality"]),
            method=_reference(contracts["method.a"]),
            context_selector=IntrinsicObservationContext(),
            utility_transform=_reference(contracts["quality.linear"]),
            utility_parameters={},
            weight=weight,
        )


def test_objective_rejects_non_i_json_integer_and_non_finite_total() -> None:
    catalog, contracts = _scoring_catalog()
    arguments = {
        "objective_id": "quality-objective",
        "candidate_input": SelectionInput("producer", "candidates"),
        "score_collection_input": SelectionInput("producer", "scores"),
        "metric": _reference(contracts["quality"]),
        "method": _reference(contracts["method.a"]),
        "context_selector": IntrinsicObservationContext(),
        "utility_transform": _reference(contracts["quality.linear"]),
        "utility_parameters": {},
    }
    with pytest.raises(SelectionError, match="finite and strictly positive"):
        SelectionObjective(**arguments, weight=10**400)

    candidates = CandidateCollection(
        "candidates",
        "protein.sequence",
        [Candidate("candidate-1", ProteinSequence("AA"))],
    )
    candidate_input = arguments["candidate_input"]
    score_input = arguments["score_collection_input"]
    scores = ScoreCollection(
        "scores",
        [_observation(contracts, "candidate-1", 90)],
    )
    with pytest.raises(SelectionError, match="finite positive total"):
        select_candidates(
            candidate_inputs={candidate_input: candidates},
            score_collection_inputs={score_input: scores},
            objectives=(
                SelectionObjective(**arguments, weight=1e308),
                SelectionObjective(
                    **{**arguments, "objective_id": "quality-objective-2"},
                    weight=1e308,
                ),
            ),
            catalog=catalog,
            limit=1,
        )


def test_selection_rejects_zero_total_weight_missing_and_out_of_range_utility() -> None:
    catalog, contracts = _scoring_catalog()
    candidates = CandidateCollection(
        "candidates",
        "protein.sequence",
        [Candidate("candidate-1", ProteinSequence("AA"))],
    )
    candidate_input = SelectionInput("producer", "candidates")
    score_input = SelectionInput("producer", "scores")
    with pytest.raises(SelectionError, match="strictly positive"):
        SelectionObjective(
            objective_id="quality-objective",
            candidate_input=candidate_input,
            score_collection_input=score_input,
            metric=_reference(contracts["quality"]),
            method=_reference(contracts["method.a"]),
            context_selector=IntrinsicObservationContext(),
            utility_transform=_reference(contracts["quality.linear"]),
            utility_parameters={},
            weight=0,
        )
    objective = SelectionObjective(
        objective_id="quality-objective",
        candidate_input=candidate_input,
        score_collection_input=score_input,
        metric=_reference(contracts["quality"]),
        method=_reference(contracts["method.a"]),
        context_selector=IntrinsicObservationContext(),
        utility_transform=_reference(contracts["quality.linear"]),
        utility_parameters={},
        weight=1,
    )
    with pytest.raises(SelectionError, match="missing observation"):
        select_candidates(
            candidate_inputs={candidate_input: candidates},
            score_collection_inputs={
                score_input: ScoreCollection("scores", [])
            },
            objectives=(replace(objective, weight=1),),
            catalog=catalog,
            limit=1,
        )
    unsafe_catalog = replace(
        catalog,
        utility_transforms={
            **dict(catalog.utility_transforms),
            ("quality.linear", "2.1.0"): lambda value, parameters: 1.01,
        },
    )
    with pytest.raises(SelectionError, match=r"within \[0, 1\]"):
        select_candidates(
            candidate_inputs={candidate_input: candidates},
            score_collection_inputs={
                score_input: ScoreCollection(
                    "scores",
                    [_observation(contracts, "candidate-1", 100)],
                )
            },
            objectives=(replace(objective, weight=1),),
            catalog=unsafe_catalog,
            limit=1,
        )


def _workflow_payload(
    contracts: dict[str, CatalogContract],
    *,
    metric: str = "quality",
    method: str = "method.a",
    utility: str = "quality.linear",
) -> dict:
    return {
        "schema_version": "2.1.0",
        "workflow_id": "workflow-scoring",
        "nodes": [
            {
                "node_id": "source",
                "node_type_id": "candidate.source",
                "node_type_version": "2.1.0",
                "binding_id": "candidate.source.direct",
                "binding_version": "2.1.0",
                "node_parameters": {},
                "binding_parameters": {},
            },
            {
                "node_id": "producer",
                "node_type_id": "score.intrinsic",
                "node_type_version": "2.1.0",
                "binding_id": "score.intrinsic.direct",
                "binding_version": "2.1.0",
                "node_parameters": {},
                "binding_parameters": {},
            },
            {
                "node_id": "select",
                "node_type_id": "selection.weighted_rank",
                "node_type_version": "4.0.0",
                "binding_id": "selection.weighted_rank.direct",
                "binding_version": "4.0.0",
                "node_parameters": {
                    "objective_ids": ["quality-objective"],
                    "tie_policy": "candidate_id_ascending",
                },
                "binding_parameters": {},
            },
        ],
        "edges": [
            {
                "source_node_id": "source",
                "source_port": "candidates",
                "target_node_id": "producer",
                "target_port": "candidates",
            },
            {
                "source_node_id": "source",
                "source_port": "candidates",
                "target_node_id": "select",
                "target_port": "candidates",
            },
            {
                "source_node_id": "producer",
                "source_port": "scores",
                "target_node_id": "select",
                "target_port": "scores",
            },
        ],
        "selection_objectives": [
            {
                "objective_id": "quality-objective",
                "candidate_input": {
                    "node_id": "source",
                    "output_port": "candidates",
                },
                "score_collection_input": {
                    "node_id": "producer",
                    "output_port": "scores",
                },
                "source_partition": "default",
                "metric": contracts[metric].reference(),
                "method": contracts[method].reference(),
                "context_selector": {"kind": "intrinsic"},
                "utility_transform": contracts[utility].reference(),
                "utility_parameters": {},
                "weight": 1,
                "match_cardinality": "exactly_one",
                "missing_policy": "error",
            }
        ],
        "contract_lock": [],
    }


def _dynamic_observation_method_payload(
    contracts: dict[str, CatalogContract],
    *,
    selection_kind: str,
    requested_method: str,
    generation_node_id: str = "generation",
    materializer_node_id: str = "materializer",
    selection_node_id: str = "select",
) -> dict:
    if selection_kind == "objective":
        selection_node = {
            "node_id": selection_node_id,
            "node_type_id": "selection.weighted_rank",
            "node_type_version": "4.0.0",
            "binding_id": "selection.weighted_rank.direct",
            "binding_version": "4.0.0",
            "node_parameters": {
                "objective_ids": ["quality-objective"],
                "tie_policy": "candidate_id_ascending",
            },
            "binding_parameters": {},
        }
    else:
        assert selection_kind == "selector"
        selection_node = {
            "node_id": selection_node_id,
            "node_type_id": "selection.filter",
            "node_type_version": "4.0.0",
            "binding_id": "selection.filter.direct",
            "binding_version": "4.0.0",
            "node_parameters": {
                "selector_id": "quality-selector",
                "operator": ">=",
                "threshold": 0.5,
                "out_of_scope_policy": "error",
                "tie_policy": "candidate_id_ascending",
            },
            "binding_parameters": {},
        }
    observation_request = {
        "candidate_input": {
            "node_id": "source",
            "output_port": "candidates",
        },
        "score_collection_input": {
            "node_id": materializer_node_id,
            "output_port": "scores",
        },
        "source_partition": "default",
        "metric": contracts["quality"].reference(),
        "method": contracts[requested_method].reference(),
        "context_selector": {"kind": "intrinsic"},
        "match_cardinality": "exactly_one",
        "missing_policy": "error",
    }
    return {
        "schema_version": "2.1.0",
        "workflow_id": "workflow-dynamic-observation-method",
        "nodes": [
            {
                "node_id": "source",
                "node_type_id": "candidate.source",
                "node_type_version": "2.1.0",
                "binding_id": "candidate.source.direct",
                "binding_version": "2.1.0",
                "node_parameters": {},
                "binding_parameters": {},
            },
            {
                "node_id": generation_node_id,
                "node_type_id": "generation.confidence_facts",
                "node_type_version": "2.1.0",
                "binding_id": "generation.confidence_facts.method_a",
                "binding_version": "2.1.0",
                "node_parameters": {},
                "binding_parameters": {},
            },
            {
                "node_id": materializer_node_id,
                "node_type_id": "score.materialize_confidence",
                "node_type_version": "2.1.0",
                "binding_id": "score.materialize_confidence.method_b",
                "binding_version": "2.1.0",
                "node_parameters": {},
                "binding_parameters": {},
            },
            selection_node,
        ],
        "edges": [
            {
                "source_node_id": "source",
                "source_port": "candidates",
                "target_node_id": generation_node_id,
                "target_port": "candidates",
            },
            {
                "source_node_id": "source",
                "source_port": "candidates",
                "target_node_id": materializer_node_id,
                "target_port": "candidates",
            },
            {
                "source_node_id": generation_node_id,
                "source_port": "facts",
                "target_node_id": materializer_node_id,
                "target_port": "facts",
            },
            {
                "source_node_id": "source",
                "source_port": "candidates",
                "target_node_id": selection_node_id,
                "target_port": "candidates",
            },
            {
                "source_node_id": materializer_node_id,
                "source_port": "scores",
                "target_node_id": selection_node_id,
                "target_port": "scores",
            },
        ],
        "observation_selectors": (
            [
                {
                    "selector_id": "quality-selector",
                    **observation_request,
                }
            ]
            if selection_kind == "selector"
            else []
        ),
        "selection_objectives": (
            [
                {
                    "objective_id": "quality-objective",
                    **observation_request,
                    "utility_transform": contracts[
                        "quality.linear"
                    ].reference(),
                    "utility_parameters": {},
                    "weight": 1,
                }
            ]
            if selection_kind == "objective"
            else []
        ),
        "contract_lock": [],
    }


def _compile_dynamic_observation_method(
    *,
    selection_kind: str,
    requested_method: str,
    generation_node_id: str = "generation",
    materializer_node_id: str = "materializer",
    selection_node_id: str = "select",
):
    catalog, contracts = _dynamic_observation_method_catalog()
    workflow = parse_workflow_document(
        _dynamic_observation_method_payload(
            contracts,
            selection_kind=selection_kind,
            requested_method=requested_method,
            generation_node_id=generation_node_id,
            materializer_node_id=materializer_node_id,
            selection_node_id=selection_node_id,
        )
    )
    return compile_workflow(
        relock_workflow(workflow, catalog),
        workflow_commit_revision=1,
        catalog=catalog,
    )


@pytest.mark.parametrize("selection_kind", ["objective", "selector"])
def test_compiler_uses_generation_method_for_dynamic_observation_capability(
    selection_kind: str,
) -> None:
    compiled = _compile_dynamic_observation_method(
        selection_kind=selection_kind,
        requested_method="method.a",
    )

    selected = (
        compiled.execution_plan.selection_objectives
        if selection_kind == "objective"
        else compiled.execution_plan.observation_selectors
    )
    assert selected[0].method.contract_id == "method.a"


@pytest.mark.parametrize(
    ("selection_kind", "collection", "error_code"),
    [
        (
            "objective",
            "selection_objectives",
            "unsatisfied_selection_objective",
        ),
        (
            "selector",
            "observation_selectors",
            "unsatisfied_observation_selector",
        ),
    ],
)
def test_compiler_rejects_materializer_method_for_dynamic_observation_capability(
    selection_kind: str,
    collection: str,
    error_code: str,
) -> None:
    with pytest.raises(WorkflowCompileError) as captured:
        _compile_dynamic_observation_method(
            selection_kind=selection_kind,
            requested_method="method.b",
        )

    assert captured.value.code == error_code
    assert captured.value.field_path == (collection, 0, "method")
    assert "Method" in str(captured.value)


@pytest.mark.parametrize("selection_kind", ["objective", "selector"])
def test_dynamic_observation_method_capability_is_independent_of_node_ids(
    selection_kind: str,
) -> None:
    compiled = _compile_dynamic_observation_method(
        selection_kind=selection_kind,
        requested_method="method.a",
        generation_node_id="fact-origin",
        materializer_node_id="observation-bridge",
        selection_node_id="decision",
    )

    assert {node.node_id for node in compiled.execution_plan.nodes} == {
        "source",
        "fact-origin",
        "observation-bridge",
        "decision",
    }


def test_compiler_resolves_exact_intrinsic_objective_before_runtime() -> None:
    catalog, contracts = _scoring_catalog()
    workflow = parse_workflow_document(_workflow_payload(contracts))
    locked = relock_workflow(workflow, catalog)

    compiled = compile_workflow(locked, workflow_commit_revision=1, catalog=catalog)

    assert compiled.execution_plan.selection_objectives[0].metric == (
        _reference(contracts["quality"])
    )
    assert {
        item.contract_id
        for item in compiled.execution_plan.resolved_contracts
    } >= {"quality", "method.a", "quality.linear"}

    novelty = parse_workflow_document(
        _workflow_payload(
            contracts,
            metric="novelty",
            utility="novelty.linear",
        )
    )
    compile_workflow(
        relock_workflow(novelty, catalog),
        workflow_commit_revision=1,
        catalog=catalog,
    )


def test_compiler_binds_65_declared_objectives_to_explicit_selection() -> None:
    catalog, contracts = _scoring_catalog()
    payload = _workflow_payload(contracts)
    template = payload["selection_objectives"][0]
    payload["selection_objectives"] = [
        {**template, "objective_id": f"quality-objective-{index}"}
        for index in range(65)
    ]
    payload["nodes"][2]["node_parameters"]["objective_ids"] = [
        objective["objective_id"]
        for objective in payload["selection_objectives"]
    ]
    workflow = parse_workflow_document(payload)
    compiled = compile_workflow(
        relock_workflow(workflow, catalog),
        workflow_commit_revision=1,
        catalog=catalog,
    )
    selection_node = next(
        node
        for node in compiled.execution_plan.nodes
        if node.node_id == "select"
    )

    assert len(compiled.execution_plan.selection_objectives) == 65
    assert len(selection_node._runtime.selection_objectives) == 65
    assert [
        objective.objective.objective_id
        for objective in selection_node._runtime.selection_objectives
    ] == [f"quality-objective-{index}" for index in range(65)]


def test_run_executes_objectives_and_publishes_effective_provenance(
    tmp_path,
    monkeypatch,
) -> None:
    catalog, contracts = _scoring_catalog()
    monkeypatch.setenv(
        "PROTEIN_WORKBENCH_PROJECT_ROOT",
        str(tmp_path / "projects"),
    )
    monkeypatch.setenv(
        "PROTEIN_WORKBENCH_RUN_ROOT",
        str(tmp_path / "runs"),
    )
    monkeypatch.setenv(
        "PROTEIN_WORKBENCH_OUTPUT_ROOT",
        str(tmp_path / "outputs"),
    )
    app = create_app(
        frozen_catalog_override=catalog,
        v2_environment_configuration={
            ("candidate.source.direct", "2.1.0"): {
                "values": {},
                "safe_fingerprint": "candidate-source-fixture-v1",
                "invalidation_token": "candidate-source-assets-v1",
            },
            ("score.intrinsic.direct", "2.1.0"): {
                "values": {},
                "safe_fingerprint": "scoring-fixture-v1",
                "invalidation_token": "scoring-fixture-assets-v1",
            }
        },
    )

    with TestClient(app) as client:
        project = client.post(
            "/api/v2/projects",
            json={"name": "intrinsic scoring"},
        ).json()
        project_id = project["id"]
        workflow = _workflow_payload(contracts)
        workflow["workflow_id"] = project_id
        committed = client.post(
            f"/api/v2/projects/{project_id}/workflow:commit",
            json={
                "expected_draft_revision": 0,
                "workflow": workflow,
            },
        )
        assert committed.status_code == 200
        started = client.post(
            f"/api/v2/projects/{project_id}/runs",
            json={
                "workflow_commit_id": committed.json()["workflow_commit_id"],
                "client_request_id": "scoring-run-1",
            },
        )
        assert started.status_code == 202
        projection = wait_for_testclient_run_terminal(
            client,
            project_id,
            started.json()["run_id"],
        )

    assert projection["status"] == "succeeded"
    candidate_output = next(
        output
        for output in projection["outputs"]
        if output["output_port"] == "candidates"
    )
    candidate_items = candidate_output["values"][0]["fields"]["items"]
    produced_ids = [
        item["fields"]["candidate_id"] for item in candidate_items
    ]
    result = projection["selection_results"][0]
    assert result["status"] == "succeeded"
    assert result["selected_candidate_ids"] == [
        produced_ids[1],
        produced_ids[0],
    ]
    assert result["candidate_input"] == {
        "node_id": "source",
        "output_port": "candidates",
    }
    assert result["objectives"] == [
        {
            "objective_id": "quality-objective",
            "candidate_input": {
                "node_id": "source",
                "output_port": "candidates",
            },
                "score_collection_input": {
                    "node_id": "producer",
                    "output_port": "scores",
                },
                "source_partition": "default",
                "metric": contracts["quality"].reference(),
            "method": contracts["method.a"].reference(),
            "context_selector": {"kind": "intrinsic"},
            "utility_transform": contracts["quality.linear"].reference(),
            "utility_parameters": {"lower": 0, "upper": 100},
            "declared_weight": 1,
            "effective_weight": 1,
            "match_cardinality": "exactly_one",
            "missing_policy": "error",
        }
    ]
    reloaded_app = create_app(
        frozen_catalog_override=catalog,
        v2_environment_configuration={
            ("candidate.source.direct", "2.1.0"): {
                "values": {},
                "safe_fingerprint": "candidate-source-fixture-v1",
                "invalidation_token": "candidate-source-assets-v1",
            },
            ("score.intrinsic.direct", "2.1.0"): {
                "values": {},
                "safe_fingerprint": "scoring-fixture-v1",
                "invalidation_token": "scoring-fixture-assets-v1",
            }
        },
    )
    with TestClient(reloaded_app) as client:
        reloaded = client.get(
            f"/api/v2/projects/{project_id}/runs/"
            f"{started.json()['run_id']}"
        )
    assert reloaded.status_code == 200
    assert reloaded.json()["selection_results"] == (
        projection["selection_results"]
    )


def test_selection_failure_is_public_and_survives_ledger_reload(
    tmp_path,
    monkeypatch,
) -> None:
    catalog, contracts = _scoring_catalog()
    unsafe_catalog = replace(
        catalog,
        utility_transforms={
            **dict(catalog.utility_transforms),
            ("quality.linear", "2.1.0"): lambda value, parameters: 1.01,
        },
    )
    monkeypatch.setenv(
        "PROTEIN_WORKBENCH_PROJECT_ROOT",
        str(tmp_path / "projects"),
    )
    monkeypatch.setenv(
        "PROTEIN_WORKBENCH_RUN_ROOT",
        str(tmp_path / "runs"),
    )
    monkeypatch.setenv(
        "PROTEIN_WORKBENCH_OUTPUT_ROOT",
        str(tmp_path / "outputs"),
    )
    environment = {
        ("candidate.source.direct", "2.1.0"): {
            "values": {},
            "safe_fingerprint": "candidate-source-fixture-v1",
            "invalidation_token": "candidate-source-assets-v1",
        },
        ("score.intrinsic.direct", "2.1.0"): {
            "values": {},
            "safe_fingerprint": "scoring-fixture-v1",
            "invalidation_token": "scoring-fixture-assets-v1",
        }
    }
    app = create_app(
        frozen_catalog_override=unsafe_catalog,
        v2_environment_configuration=environment,
    )

    with TestClient(app) as client:
        project = client.post(
            "/api/v2/projects",
            json={"name": "unsafe intrinsic scoring"},
        ).json()
        project_id = project["id"]
        workflow = _workflow_payload(contracts)
        workflow["workflow_id"] = project_id
        committed = client.post(
            f"/api/v2/projects/{project_id}/workflow:commit",
            json={
                "expected_draft_revision": 0,
                "workflow": workflow,
            },
        )
        assert committed.status_code == 200
        started = client.post(
            f"/api/v2/projects/{project_id}/runs",
            json={
                "workflow_commit_id": committed.json()["workflow_commit_id"],
                "client_request_id": "unsafe-scoring-run-1",
            },
        )
        run_id = started.json()["run_id"]
        projection = wait_for_testclient_run_terminal(
            client,
            project_id,
            run_id,
        )
        with client.websocket_connect(
            f"/api/v2/projects/{project_id}/runs/{run_id}/events"
        ) as websocket:
            messages = []
            try:
                while True:
                    messages.append(websocket.receive_json())
            except WebSocketDisconnect as closed:
                assert closed.code == 1000

    assert projection["status"] == "failed"
    assert projection["selection_results"] == []
    assert "selection_error" not in projection
    assert next(
        disposition
        for disposition in projection["node_dispositions"]
        if disposition["node_id"] == "select"
    )["outcome"] == "failed"
    selection_events = [
        message["event"]
        for message in messages
        if message["event"]["type"] == "selection_terminal"
    ]
    for message in messages:
        validate_event(message)
    assert selection_events == []
    operation_terminal = next(
        message["event"]
        for message in messages
        if message["event"]["type"] == "operation_attempt_terminal"
        and message["event"]["status"] == "failed"
    )
    assert operation_terminal["error"]["code"] == "node_execution_failed"
    assert operation_terminal["error"]["details"] == {
        "exception_type": "SelectionError"
    }
    reloaded_app = create_app(
        frozen_catalog_override=unsafe_catalog,
        v2_environment_configuration=environment,
    )
    with TestClient(reloaded_app) as client:
        reloaded = client.get(
            f"/api/v2/projects/{project_id}/runs/{run_id}"
        )
    assert reloaded.status_code == 200
    assert reloaded.json()["status"] == "failed"
    assert reloaded.json()["node_dispositions"] == (
        projection["node_dispositions"]
    )
    assert "selection_error" not in reloaded.json()


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("method", "method.b", "does not use requested Method"),
        ("utility", "novelty.linear", "incompatible"),
    ],
)
def test_compiler_rejects_unsatisfied_objective_before_provider(
    field: str,
    value: str,
    message: str,
) -> None:
    catalog, contracts = _scoring_catalog()
    arguments = {field: value}
    workflow = parse_workflow_document(
        _workflow_payload(contracts, **arguments)
    )
    locked = relock_workflow(workflow, catalog)

    with pytest.raises(WorkflowCompileError, match=message):
        compile_workflow(locked, workflow_commit_revision=1, catalog=catalog)


def test_compiler_rejects_metric_not_guaranteed_by_selected_binding() -> None:
    catalog, contracts = _scoring_catalog()
    original = contracts["score.intrinsic.direct"]
    original_descriptor = original.public_contract()["descriptor"]
    limited_binding = _contract(
        "binding",
        original.contract_id,
        {
            key: value
            for key, value in original_descriptor.items()
            if key
            not in {
                "contract_kind",
                "contract_id",
                "contract_version",
                "schema_namespace",
                "produced_observations",
            }
        }
        | {
            "produced_observations": [
                original_descriptor["produced_observations"][0]
            ]
        },
    )
    limited_catalog = replace(
        catalog,
        contracts=tuple(
            limited_binding
            if contract.contract_id == limited_binding.contract_id
            else contract
            for contract in catalog.contracts
        ),
        availability=(
            {
                "binding": limited_binding.reference(),
                "observed_at": "2026-07-29T06:00:00Z",
                "available": True,
            },
        ),
    )
    workflow = parse_workflow_document(
        _workflow_payload(
            contracts
            | {"score.intrinsic.direct": limited_binding},
            metric="novelty",
            utility="novelty.linear",
        )
    )
    locked = relock_workflow(workflow, limited_catalog)

    with pytest.raises(WorkflowCompileError, match="cannot guarantee"):
        compile_workflow(
            locked,
            workflow_commit_revision=1,
            catalog=limited_catalog,
        )


def test_compiler_rejects_weighting_across_different_candidate_inputs() -> None:
    catalog, contracts = _scoring_catalog()
    payload = _workflow_payload(contracts)
    second_node = {
        **payload["nodes"][0],
        "node_id": "producer-2",
    }
    second_objective = {
        **payload["selection_objectives"][0],
        "objective_id": "quality-objective-2",
        "candidate_input": {
            "node_id": "producer-2",
            "output_port": "candidates",
        },
        "score_collection_input": {
            "node_id": "producer-2",
            "output_port": "scores",
        },
    }
    payload["nodes"].append(second_node)
    payload["selection_objectives"].append(second_objective)
    workflow = parse_workflow_document(payload)

    with pytest.raises(
        WorkflowCompileError,
        match="one exact Candidate input",
    ):
        compile_workflow(
            relock_workflow(workflow, catalog),
            workflow_commit_revision=1,
            catalog=catalog,
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("python", "lambda score: score"),
        ("normalization", "dataset_min_max"),
        ("reverse_direction", True),
        ("raw_metric_addition", True),
    ],
)
def test_workflow_rejects_implicit_or_arbitrary_scoring_controls(
    field: str,
    value: object,
) -> None:
    _, contracts = _scoring_catalog()
    payload = _workflow_payload(contracts)
    payload["selection_objectives"][0][field] = value

    with pytest.raises(WorkflowDocumentError, match="unexpected fields"):
        parse_workflow_document(payload)
