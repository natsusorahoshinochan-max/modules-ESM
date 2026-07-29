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
    LazyImplementationFactory,
    ReadinessDeclaration,
    SelectionError,
    SelectionInput,
    SelectionObjective,
    SelectionResult,
    builtin_frozen_catalog,
    compile_workflow,
    relock_workflow,
    select_candidates,
    validate_produced_score_collection,
)
from core.port_types import PortValueError
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
    ExactContractReference,
    IntrinsicObservationContext,
    ProteinSequence,
    ScoreCollection,
    ScoreObservation,
)


def _contract(
    kind: str,
    contract_id: str,
    descriptor: dict,
) -> CatalogContract:
    return CatalogContract(
        contract_kind=kind,  # type: ignore[arg-type]
        contract_id=contract_id,
        contract_version="2.0.0",
        descriptor={
            "schema_namespace": "protein-workbench-contract/v2",
            "contract_kind": kind,
            "contract_id": contract_id,
            "contract_version": "2.0.0",
            **descriptor,
        },
    )


def _scoring_catalog() -> tuple[FrozenCatalog, dict[str, CatalogContract]]:
    builtin = builtin_frozen_catalog()
    candidates_type = builtin.require_port_type("candidate.collection", "2.0.0")
    scores_type = builtin.require_port_type("score.collection", "2.0.0")
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
                "lower": {"type": "number", "default": 0},
                "upper": {"type": "number", "default": 100},
            },
            "behavior": {
                "behavior_id": "quality.linear/transform",
                "behavior_version": "2.0.0",
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
                "lower": {"type": "number", "default": 0},
                "upper": {"type": "number", "default": 100},
            },
            "behavior": {
                "behavior_id": "novelty.linear/transform",
                "behavior_version": "2.0.0",
                "parameters": {},
            },
            "output_contract": {"minimum": 0, "maximum": 1},
        },
    )
    producer_node = _contract(
        "node_type",
        "score.intrinsic",
        {
            "title": "Intrinsic scorer",
            "summary": "Produces fixed intrinsic observations.",
            "category": "evaluation",
            "inputs": [],
            "outputs": [
                {
                    "name": "candidates",
                    "port_type": candidates_type.reference(),
                    "required": True,
                    "multiplicity": "one",
                    "scientific_meaning": "Candidates that were observed.",
                },
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
                "behavior_version": "2.0.0",
                "parameters": {},
            },
            "availability_declaration": {
                "behavior": {
                    "behavior_id": "score.intrinsic/availability",
                    "behavior_version": "2.0.0",
                    "parameters": {},
                },
                "prerequisites": {},
            },
            "readiness_declaration": {
                "behavior": {
                    "behavior_id": "score.intrinsic/readiness",
                    "behavior_version": "2.0.0",
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
                    "subject_direction": "output",
                    "subject_port": "candidates",
                    "guaranteed_multiplicity": "one",
                },
                {
                    "output_port": "scores",
                    "metric": metric_novelty.reference(),
                    "context_profile": {"kind": "intrinsic"},
                    "subject_grain": "candidate",
                    "source_role": "subject",
                    "subject_direction": "output",
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
        "2.0.0",
        {},
    )
    readiness_behavior = BehaviorReference(
        "score.intrinsic/readiness",
        "2.0.0",
        {},
    )

    class ScoringImplementation:
        def execute(
            self,
            *,
            inputs: dict,
            node_parameters: dict,
            binding_parameters: dict,
        ) -> dict:
            assert inputs == {}
            assert node_parameters == {}
            assert binding_parameters == {}
            candidates = CandidateCollection(
                "raw-candidates",
                "protein.sequence",
                [
                    Candidate("raw-1", ProteinSequence("AA")),
                    Candidate("raw-2", ProteinSequence("GG")),
                ],
            )
            return {
                "candidates": candidates,
                "scores": ScoreCollection(
                    "raw-scores",
                    [
                        _observation(contracts, "raw-1", 20),
                        _observation(contracts, "raw-2", 90),
                        _observation(
                            contracts,
                            "raw-1",
                            80,
                            metric="novelty",
                        ),
                        _observation(
                            contracts,
                            "raw-2",
                            40,
                            metric="novelty",
                        ),
                    ],
                ),
            }

    catalog = FrozenCatalog(
        builtin.port_types,
        contracts=tuple(contracts.values()),
        availability=(
            {
                "binding": producer_binding.reference(),
                "observed_at": "2026-07-29T06:00:00Z",
                "available": True,
            },
        ),
        availability_observed_at=datetime(
            2026,
            7,
            29,
            6,
            tzinfo=timezone.utc,
        ),
        utility_transforms={
            ("quality.linear", "2.0.0"): linear,
            ("novelty.linear", "2.0.0"): linear,
        },
        factories={
            ("score.intrinsic.direct", "2.0.0"): (
                LazyImplementationFactory(
                    behavior=factory_behavior,
                    build=lambda **_: ScoringImplementation(),
                )
            )
        },
        readiness_declarations={
            ("score.intrinsic.direct", "2.0.0"): ReadinessDeclaration(
                behavior=readiness_behavior,
                prerequisites={},
                check=lambda _: True,
            )
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
    return ScoreObservation(
        candidate_id=candidate_id,
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
    score_type = catalog.require_port_type("score.collection", "2.0.0")
    observation = _observation(contracts, "candidate-1", 90)

    encoded = score_type.encode(
        ScoreCollection("scores", [observation, observation])
    )
    decoded = score_type.decode(encoded)
    assert decoded.entries == [observation]

    with pytest.raises(PortValueError, match="conflicting values"):
        score_type.encode(
            ScoreCollection(
                "scores",
                [observation, replace(observation, value=10)],
            )
        )


def test_score_collection_codec_enforces_metric_and_method_reference_roles() -> None:
    catalog, contracts = _scoring_catalog()
    score_type = catalog.require_port_type("score.collection", "2.0.0")
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
        inputs={},
        outputs={"candidates": candidates, "scores": scores},
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
            inputs={},
            outputs={"candidates": candidates},
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
            inputs={},
            outputs={"candidates": candidates},
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
        inputs={},
        outputs={"candidates": candidates, "scores": valid_scores},
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
    with pytest.raises(PortValueError, match="outside its declared subject"):
        validate_produced_score_collection(
            catalog=catalog,
            binding=binding,
            output_port="scores",
            collection=ghost_scores,
            inputs={},
            outputs={"candidates": candidates, "scores": ghost_scores},
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
            }
        }
        | {
            "produced_observations": [
                {
                    "output_port": "scores",
                    "metric": residue_metric.reference(),
                    "context_profile": {"kind": "intrinsic"},
                    "subject_grain": "candidate",
                    "source_role": "subject",
                    "subject_direction": "output",
                    "subject_port": "candidates",
                    "guaranteed_multiplicity": "one",
                }
            ]
        },
    )
    residue_catalog = replace(
        catalog,
        contracts=(*catalog.contracts, residue_metric, residue_binding),
    )
    candidates = CandidateCollection(
        "candidates",
        "protein.sequence",
        [Candidate("candidate-1", ProteinSequence("AAA"))],
    )
    observation = ScoreObservation(
        candidate_id="candidate-1",
        metric=_reference(residue_metric),
        method=_reference(contracts["method.a"]),
        context=IntrinsicObservationContext(),
        value=[80, None, 95],
    )
    scores = ScoreCollection("scores", [observation])

    validate_produced_score_collection(
        catalog=residue_catalog,
        binding=residue_binding,
        output_port="scores",
        collection=scores,
        inputs={},
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
            inputs={},
            outputs={"candidates": candidates},
        )
    with pytest.raises(PortValueError, match="exact subject residue layout"):
        validate_produced_score_collection(
            catalog=residue_catalog,
            binding=residue_binding,
            output_port="scores",
            collection=ScoreCollection(
                "scores",
                [replace(observation, value=[80, 95])],
            ),
            inputs={},
            outputs={"candidates": candidates},
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


@pytest.mark.parametrize("weight", [-1, -0.0, float("inf"), float("nan")])
def test_objective_rejects_negative_or_non_finite_weight(weight: float) -> None:
    _, contracts = _scoring_catalog()
    with pytest.raises(SelectionError, match="finite and non-negative"):
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
    with pytest.raises(SelectionError, match="finite and non-negative"):
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
    objective = SelectionObjective(
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
    with pytest.raises(SelectionError, match="finite positive total"):
        select_candidates(
            candidate_inputs={candidate_input: candidates},
            score_collection_inputs={
                score_input: ScoreCollection(
                    "scores",
                    [_observation(contracts, "candidate-1", 90)],
                )
            },
            objectives=(objective,),
            catalog=catalog,
            limit=1,
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
            ("quality.linear", "2.0.0"): lambda value, parameters: 1.01,
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
        "schema_version": "2.0.0",
        "workflow_id": "workflow-scoring",
        "nodes": [
            {
                "node_id": "producer",
                "node_type_id": "score.intrinsic",
                "node_type_version": "2.0.0",
                "binding_id": "score.intrinsic.direct",
                "binding_version": "2.0.0",
                "node_parameters": {},
                "binding_parameters": {},
            }
        ],
        "edges": [],
        "selection_objectives": [
            {
                "objective_id": "quality-objective",
                "candidate_input": {
                    "node_id": "producer",
                    "output_port": "candidates",
                },
                "score_collection_input": {
                    "node_id": "producer",
                    "output_port": "scores",
                },
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


def test_compiler_resolves_exact_intrinsic_objective_before_runtime() -> None:
    catalog, contracts = _scoring_catalog()
    workflow = parse_workflow_document(_workflow_payload(contracts))
    locked = relock_workflow(workflow, catalog)

    compiled = compile_workflow(locked, workflow_revision=1, catalog=catalog)

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
        workflow_revision=1,
        catalog=catalog,
    )


def test_compiler_and_runtime_accept_65_declared_objectives() -> None:
    catalog, contracts = _scoring_catalog()
    payload = _workflow_payload(contracts)
    template = payload["selection_objectives"][0]
    payload["selection_objectives"] = [
        {**template, "objective_id": f"quality-objective-{index}"}
        for index in range(65)
    ]
    workflow = parse_workflow_document(payload)
    compiled = compile_workflow(
        relock_workflow(workflow, catalog),
        workflow_revision=1,
        catalog=catalog,
    )
    candidate_input = SelectionInput("producer", "candidates")
    score_input = SelectionInput("producer", "scores")
    candidates = CandidateCollection(
        "candidates",
        "protein.sequence",
        [Candidate("candidate-1", ProteinSequence("AA"))],
    )
    selection = select_candidates(
        candidate_inputs={candidate_input: candidates},
        score_collection_inputs={
            score_input: ScoreCollection(
                "scores",
                [_observation(contracts, "candidate-1", 90)],
            )
        },
        objectives=compiled.execution_plan.selection_objectives,
        catalog=catalog,
        limit=1,
    )
    provenance = selection.public_provenance()
    result = {
        "status": "succeeded",
        "candidate_input": candidate_input.to_public(),
        "selected_collection_id": selection.candidates.collection_id,
        "selected_candidate_ids": ["candidate-1"],
        "objectives": provenance["objectives"],
    }

    assert len(provenance["objectives"]) == 65
    validate_schema("#/$defs/SelectionResult", result)


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
            ("score.intrinsic.direct", "2.0.0"): {
                "values": {},
                "safe_fingerprint": "scoring-fixture-v1",
                "invalidation_token": "scoring-fixture-assets-v1",
            }
        },
    )

    with TestClient(app) as client:
        project = client.post(
            "/api/projects",
            json={"name": "intrinsic scoring"},
        ).json()
        project_id = project["id"]
        workflow = _workflow_payload(contracts)
        workflow["workflow_id"] = project_id
        saved = client.put(
            f"/api/v2/projects/{project_id}/workflow",
            json={
                "expected_workflow_revision": 0,
                "workflow": workflow,
            },
        )
        assert saved.status_code == 200
        relocked = client.post(
            f"/api/v2/projects/{project_id}/workflow:relock",
            json={"workflow_revision": 1},
        )
        assert relocked.status_code == 200
        compiled = client.post(
            f"/api/v2/projects/{project_id}/workflow:compile",
            json={
                "workflow_revision": 2,
                "workflow": relocked.json()["workflow"],
            },
        )
        assert compiled.status_code == 200
        started = client.post(
            f"/api/v2/projects/{project_id}/runs",
            json={
                "workflow_revision": 2,
                "compile_id": compiled.json()["compile_id"],
                "client_request_id": "scoring-run-1",
            },
        )
        assert started.status_code == 202
        projection_response = client.get(
            f"/api/v2/projects/{project_id}/runs/"
            f"{started.json()['run_id']}"
        )

    assert projection_response.status_code == 200
    projection = projection_response.json()
    validate_response("run_projection", 200, projection)
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
        "node_id": "producer",
        "output_port": "candidates",
    }
    assert result["objectives"] == [
        {
            "objective_id": "quality-objective",
            "candidate_input": {
                "node_id": "producer",
                "output_port": "candidates",
            },
            "score_collection_input": {
                "node_id": "producer",
                "output_port": "scores",
            },
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
            ("score.intrinsic.direct", "2.0.0"): {
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
            ("quality.linear", "2.0.0"): lambda value, parameters: 1.01,
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
        ("score.intrinsic.direct", "2.0.0"): {
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
            "/api/projects",
            json={"name": "unsafe intrinsic scoring"},
        ).json()
        project_id = project["id"]
        workflow = _workflow_payload(contracts)
        workflow["workflow_id"] = project_id
        assert client.put(
            f"/api/v2/projects/{project_id}/workflow",
            json={
                "expected_workflow_revision": 0,
                "workflow": workflow,
            },
        ).status_code == 200
        relocked = client.post(
            f"/api/v2/projects/{project_id}/workflow:relock",
            json={"workflow_revision": 1},
        )
        compiled = client.post(
            f"/api/v2/projects/{project_id}/workflow:compile",
            json={
                "workflow_revision": 2,
                "workflow": relocked.json()["workflow"],
            },
        )
        started = client.post(
            f"/api/v2/projects/{project_id}/runs",
            json={
                "workflow_revision": 2,
                "compile_id": compiled.json()["compile_id"],
                "client_request_id": "unsafe-scoring-run-1",
            },
        )
        run_id = started.json()["run_id"]
        projection_response = client.get(
            f"/api/v2/projects/{project_id}/runs/{run_id}"
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

    assert projection_response.status_code == 200
    projection = projection_response.json()
    validate_response("run_projection", 200, projection)
    assert projection["status"] == "failed"
    assert projection["selection_results"] == []
    assert projection["selection_error"]["code"] == "selection_failed"
    assert projection["selection_error"]["message"] == (
        "Workflow selection failed safely"
    )
    selection_events = [
        message["event"]
        for message in messages
        if message["event"]["type"] == "selection_terminal"
    ]
    for message in messages:
        validate_event(message)
    assert selection_events == [
        {
            "type": "selection_terminal",
            "status": "failed",
            "error": projection["selection_error"],
        }
    ]
    reloaded_app = create_app(
        frozen_catalog_override=unsafe_catalog,
        v2_environment_configuration=environment,
    )
    with TestClient(reloaded_app) as client:
        reloaded = client.get(
            f"/api/v2/projects/{project_id}/runs/{run_id}"
        )
    assert reloaded.status_code == 200
    assert reloaded.json()["selection_error"] == (
        projection["selection_error"]
    )


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
        compile_workflow(locked, workflow_revision=1, catalog=catalog)


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
            workflow_revision=1,
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
            workflow_revision=1,
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
