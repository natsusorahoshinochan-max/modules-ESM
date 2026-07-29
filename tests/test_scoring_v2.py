"""Ticket 10 acceptance at the agreed v2 scoring and compiler seams."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone

import pytest

from core import (
    CatalogContract,
    FrozenCatalog,
    SelectionError,
    SelectionInput,
    SelectionObjective,
    builtin_frozen_catalog,
    compile_workflow,
    relock_workflow,
    select_candidates,
    validate_produced_score_collection,
)
from core.port_types import PortValueError
from core.workflow_v2 import (
    WorkflowCompileError,
    WorkflowDocumentError,
    parse_workflow_document,
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
                    "guaranteed_multiplicity": "one",
                },
                {
                    "output_port": "scores",
                    "metric": metric_novelty.reference(),
                    "context_profile": {"kind": "intrinsic"},
                    "subject_grain": "candidate",
                    "source_role": "subject",
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


def test_binding_output_obeys_exact_method_metric_context_and_multiplicity() -> None:
    catalog, contracts = _scoring_catalog()
    binding = contracts["score.intrinsic.direct"]
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
        expected_candidate_ids=("candidate-1",),
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
            expected_candidate_ids=("candidate-1",),
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
    assert result.provenance["objectives"] == [
        {
            "objective_id": "quality-objective",
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
    with pytest.raises(SelectionError, match="at least one positive"):
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
