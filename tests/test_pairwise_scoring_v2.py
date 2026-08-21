"""Ticket 11 acceptance at the typed scoring, compiler, and selection seams."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone

import pytest

from core import (
    BehaviorReference,
    CandidatePairingIntent,
    CandidatePairingIntentEntry,
    CatalogContract,
    CatalogBuildError,
    FrozenCatalog,
    ObservationPropagationDefinition,
    PairwiseContextSelector,
    SelectionError,
    SelectionInput,
    SelectionObjective,
    ContractIdentity,
    ProducedObservationDefinition,
    ReadinessDeclaration,
    ReadinessResult,
    ScientificOperationFactory,
    WorkflowCompileError,
    WorkflowDocument,
    WorkflowNodeInstance,
    build_frozen_catalog,
    compile_workflow,
    relock_workflow,
    builtin_frozen_catalog,
    validate_produced_score_collection,
)
from core.port_types import PortValueError
from core.value_admission import normalize_scientific_outputs
from core.workflow_v2 import WorkflowEdge as V2WorkflowEdge
from datatypes import (
    Candidate,
    CandidateDataReference,
    CandidateCollection,
    ExactContractReference,
    PairwiseObservationContext,
    PairwiseCandidateMatch,
    PairwiseCandidateMapping,
    PairwiseParticipant,
    ProteinSequence,
    ScoreCollection,
    ScoreObservation,
)
from modules.selection.package import MODULE_PACKAGE as SELECTION_PACKAGE
from protein_workbench_public import (
    ProtocolValidationError,
    validate_schema,
)
from tests.fixtures.scientific_operation import select_admitted_candidates


CONTRACT_VERSION = "2.1.0"
PORT_VERSION = "4.0.0"
SCORE_PORT_VERSION = "5.0.0"
CANDIDATE_COLLECTION_PORT_TYPE_VERSION = "4.0.0"
CANDIDATE_PAIRING_PORT_TYPE_VERSION = "4.0.0"
NODE_BINDING_VERSION = "4.0.0"
SELECTION_NODE_BINDING_VERSION = "5.0.0"


def _reference(kind: str, contract_id: str) -> ExactContractReference:
    return ExactContractReference(
        contract_kind=kind,
        contract_id=contract_id,
        contract_version="2.1.0",
        contract_digest="sha256:" + "1" * 64,
    )


def _contract(
    kind: str,
    contract_id: str,
    descriptor: dict,
    *,
    version: str = CONTRACT_VERSION,
) -> CatalogContract:
    return CatalogContract(
        contract_kind=kind,  # type: ignore[arg-type]
        contract_id=contract_id,
        contract_version=version,
        descriptor={
            "schema_namespace": "protein-workbench-contract/v2",
            "contract_kind": kind,
            "contract_id": contract_id,
            "contract_version": version,
            **descriptor,
        },
    )


def _pairwise_catalog() -> tuple[FrozenCatalog, dict[str, CatalogContract]]:
    builtin = builtin_frozen_catalog()
    metric = _contract(
        "metric",
        "structure.tm_score",
        {
            "value_shape": "scalar",
            "canonical_range": {"minimum": 0, "maximum": 1},
            "validation_contract": {"finite": True},
        },
    )
    method = _contract("method", "tm-align", {})
    pairwise_node = _contract(
        "node_type",
        "score.test.pairwise",
        {
            "inputs": [
                {
                    "name": name,
                    "port_type": builtin.require_port_type(
                        "candidate.pairing"
                        if name == "pairings"
                        else "score.collection"
                        if name in {"left", "right", "source"}
                        else "candidate.collection",
                        CANDIDATE_PAIRING_PORT_TYPE_VERSION
                        if name == "pairings"
                        else SCORE_PORT_VERSION
                        if name in {"left", "right", "source"}
                        else CANDIDATE_COLLECTION_PORT_TYPE_VERSION,
                    ).reference(),
                    "required": False,
                    "multiplicity": "one",
                }
                for name in (
                    "subjects",
                    "counterparts",
                    "pairings",
                    "left",
                    "right",
                    "source",
                )
            ],
            "outputs": [
                {
                    "name": "scores",
                    "port_type": builtin.require_port_type(
                        "score.collection",
                        SCORE_PORT_VERSION,
                    ).reference(),
                    "required": True,
                    "multiplicity": "one",
                }
            ],
            "node_parameters": {},
        },
    )
    selector_profile = PairwiseContextSelector(
        pairing_mode="fixed_reference",
        normalization="tm-score/reference-length",
    ).to_public()
    fixed_utility = _contract(
        "utility_transform",
        "tm-score.fixed",
        {
            "compatible_input_contract": {
                "metric": metric.reference(),
                "method": method.reference(),
                "context_profile": selector_profile,
            },
            "parameters": {},
        },
    )
    paired_utility = _contract(
        "utility_transform",
        "tm-score.paired",
        {
            "compatible_input_contract": {
                "metric": metric.reference(),
                "method": method.reference(),
                "context_profile": PairwiseContextSelector(
                    pairing_mode="per_subject_counterpart",
                    normalization="tm-score/reference-length",
                ).to_public(),
            },
            "parameters": {},
        },
    )
    contracts = {
        item.contract_id: item
        for item in (
            metric,
            method,
            pairwise_node,
            fixed_utility,
            paired_utility,
        )
    }
    return (
        FrozenCatalog(
            builtin.port_types,
            contracts=tuple(contracts.values()),
            availability_observed_at=datetime(
                2026,
                7,
                29,
                tzinfo=timezone.utc,
            ),
            utility_transforms={
                ("tm-score.fixed", "2.1.0"): lambda value, _: float(value),
                ("tm-score.paired", "2.1.0"): lambda value, _: float(value),
            },
        ),
        contracts,
    )


def _pairwise_context(
    *,
    subject_id: str = "subject-a",
    reference_id: str = "reference-a",
) -> PairwiseObservationContext:
    subject = CandidateDataReference(
        candidate_id=subject_id,
        data_type_id="protein.sequence",
        content_digest="sha256:" + "2" * 64,
    )
    reference = CandidateDataReference(
        candidate_id=reference_id,
        data_type_id="protein.sequence",
        content_digest="sha256:" + "3" * 64,
    )
    return PairwiseObservationContext(
        subject=PairwiseParticipant(
            role="subject",
            candidate=subject,
        ),
        reference=PairwiseParticipant(
            role="reference",
            candidate=reference,
        ),
        pairing_mode="fixed_reference",
        normalization="tm-score/reference-length",
    )


def test_pairwise_context_is_typed_canonical_and_part_of_observation_identity() -> None:
    score_type = builtin_frozen_catalog().require_port_type(
        "score.collection",
        SCORE_PORT_VERSION,
    )
    context = _pairwise_context()
    observation = ScoreObservation(
        subject=context.subject.candidate,
        metric=_reference("metric", "structure.tm_score"),
        method=_reference("method", "tm-align"),
        context=context,
        value=0.8,
        source_partition="fixed-reference",
    )

    decoded = score_type.decode(
        score_type.encode(ScoreCollection("pairwise-scores", [observation]))
    )

    assert decoded.entries == (observation,)
    assert context.to_public() == {
        "kind": "pairwise",
        "subject": {
            "role": "subject",
            "candidate": {
                "candidate_id": "subject-a",
                "data_type_id": "protein.sequence",
                "content_digest": "sha256:" + "2" * 64,
            },
        },
        "reference": {
            "role": "reference",
            "candidate": {
                "candidate_id": "reference-a",
                "data_type_id": "protein.sequence",
                "content_digest": "sha256:" + "3" * 64,
            },
        },
        "pairing_mode": "fixed_reference",
        "normalization": "tm-score/reference-length",
    }
    assert replace(observation, value=0.2).identity == observation.identity
    assert (
        replace(
            observation,
            context=_pairwise_context(reference_id="reference-b"),
        ).identity
        != observation.identity
    )


@pytest.mark.parametrize(
    ("context", "message"),
    [
        (
            replace(
                _pairwise_context(),
                subject=PairwiseParticipant(
                    role="reference",
                    candidate=_pairwise_context().subject.candidate,
                ),
            ),
            "subject role",
        ),
        (
            replace(
                _pairwise_context(),
                reference=PairwiseParticipant(
                    role="reference",
                    candidate=_pairwise_context().subject.candidate,
                ),
            ),
            "identities must differ",
        ),
    ],
)
def test_pairwise_context_fails_closed_on_invalid_roles_or_identity(
    context: PairwiseObservationContext,
    message: str,
) -> None:
    score_type = builtin_frozen_catalog().require_port_type(
        "score.collection",
        SCORE_PORT_VERSION,
    )
    observation = ScoreObservation(
        subject=context.subject.candidate,
        metric=_reference("metric", "structure.tm_score"),
        method=_reference("method", "tm-align"),
        context=context,
        value=0.8,
        source_partition="fixed-reference",
    )

    with pytest.raises(PortValueError, match=message):
        score_type.encode(ScoreCollection("pairwise-scores", [observation]))


def _pairwise_observation(
    *,
    catalog: FrozenCatalog,
    contracts: dict[str, CatalogContract],
    subject: Candidate,
    reference: Candidate,
    pairing_mode: str,
    source_partition: str,
    value: float,
) -> ScoreObservation:
    candidate_type = catalog.require_port_type("protein.sequence", "3.0.0")
    reference_type = catalog.require_port_type("protein.sequence", "3.0.0")
    subject_reference = CandidateDataReference(
        candidate_id=subject.candidate_id,
        data_type_id="protein.sequence",
        content_digest=candidate_type.content_digest(subject.data),
    )
    counterpart_reference = CandidateDataReference(
        candidate_id=reference.candidate_id,
        data_type_id="protein.sequence",
        content_digest=reference_type.content_digest(reference.data),
    )
    return ScoreObservation(
        subject=subject_reference,
        metric=_reference_from_contract(contracts["structure.tm_score"]),
        method=_reference_from_contract(contracts["tm-align"]),
        context=PairwiseObservationContext(
            subject=PairwiseParticipant(
                role="subject",
                candidate=subject_reference,
            ),
            reference=PairwiseParticipant(
                role="reference",
                candidate=counterpart_reference,
            ),
            pairing_mode=pairing_mode,
            normalization="tm-score/reference-length",
        ),
        value=value,
        source_partition=source_partition,
    )


def _pairing_map(
    catalog: FrozenCatalog,
    pairs: list[tuple[Candidate, Candidate]],
) -> PairwiseCandidateMapping:
    candidate_type = catalog.require_port_type("protein.sequence", "3.0.0")
    return PairwiseCandidateMapping(
        entries=[
            PairwiseCandidateMatch(
                subject=CandidateDataReference(
                    candidate_id=subject.candidate_id,
                    data_type_id="protein.sequence",
                    content_digest=candidate_type.content_digest(subject.data),
                ),
                reference=CandidateDataReference(
                    candidate_id=reference.candidate_id,
                    data_type_id="protein.sequence",
                    content_digest=candidate_type.content_digest(
                        reference.data
                    ),
                ),
            )
            for subject, reference in pairs
        ]
    )


def test_candidate_pairing_port_is_canonical_and_one_to_one() -> None:
    catalog, _ = _pairwise_catalog()
    subject = Candidate("subject-a", ProteinSequence("AA"))
    reference = Candidate("reference-a", ProteinSequence("AT"))
    pairing_type = catalog.require_port_type("candidate.pairing", PORT_VERSION)
    mapping = _pairing_map(catalog, [(subject, reference)])

    assert pairing_type.decode(pairing_type.encode(mapping)) == mapping

    with pytest.raises(PortValueError, match="multiple counterparts"):
        pairing_type.encode(
            PairwiseCandidateMapping(
                entries=[mapping.entries[0], mapping.entries[0]]
            )
        )

    subject_b = Candidate("subject-b", ProteinSequence("GG"))
    conflicting_reference = Candidate("reference-a", ProteinSequence("AG"))
    with pytest.raises(PortValueError, match="conflicting exact data reference"):
        pairing_type.encode(
            _pairing_map(
                catalog,
                [
                    (subject, reference),
                    (subject_b, conflicting_reference),
                ],
            )
        )


def _reference_from_contract(
    contract: CatalogContract,
) -> ExactContractReference:
    value = contract.reference()
    return ExactContractReference(
        contract_kind=value["contract_kind"],
        contract_id=value["contract_id"],
        contract_version=value["contract_version"],
        contract_digest=value["contract_digest"],
    )


def _objective(
    contracts: dict[str, CatalogContract],
    *,
    objective_id: str,
    partition: str,
    pairing_mode: str,
    utility: str,
) -> SelectionObjective:
    return SelectionObjective(
        objective_id=objective_id,
        candidate_input=SelectionInput("subjects", "candidates"),
        score_collection_input=SelectionInput("scorer", "scores"),
        source_partition=partition,
        metric=_reference_from_contract(contracts["structure.tm_score"]),
        method=_reference_from_contract(contracts["tm-align"]),
        context_selector=PairwiseContextSelector(
            pairing_mode=pairing_mode,
            normalization="tm-score/reference-length",
        ),
        utility_transform=_reference_from_contract(contracts[utility]),
        utility_parameters={},
        weight=1,
    )


def test_fixed_and_per_subject_partitions_never_cross_match() -> None:
    catalog, contracts = _pairwise_catalog()
    subject_a = Candidate("subject-a", data=ProteinSequence("AA"))
    subject_b = Candidate("subject-b", data=ProteinSequence("GG"))
    fixed_reference = Candidate(
        "reference-fixed",
        data=ProteinSequence("AG"),
    )
    reference_a = Candidate(
        "reference-a",
        data=ProteinSequence("AT"),
    )
    reference_b = Candidate(
        "reference-b",
        data=ProteinSequence("GT"),
    )
    candidates = CandidateCollection(
        "subjects",
        "protein.sequence",
        [subject_a, subject_b],
    )
    scores = ScoreCollection(
        "overlapping-pairwise-scores",
        [
            _pairwise_observation(
                catalog=catalog,
                contracts=contracts,
                subject=subject_a,
                reference=fixed_reference,
                pairing_mode="fixed_reference",
                source_partition="fixed-reference",
                value=0.9,
            ),
            _pairwise_observation(
                catalog=catalog,
                contracts=contracts,
                subject=subject_b,
                reference=fixed_reference,
                pairing_mode="fixed_reference",
                source_partition="fixed-reference",
                value=0.1,
            ),
            _pairwise_observation(
                catalog=catalog,
                contracts=contracts,
                subject=subject_a,
                reference=reference_a,
                pairing_mode="per_subject_counterpart",
                source_partition="per-subject",
                value=0.1,
            ),
            _pairwise_observation(
                catalog=catalog,
                contracts=contracts,
                subject=subject_b,
                reference=reference_b,
                pairing_mode="per_subject_counterpart",
                source_partition="per-subject",
                value=0.9,
            ),
        ],
    )
    inputs = {
        SelectionInput("subjects", "candidates"): candidates,
    }
    score_inputs = {
        SelectionInput("scorer", "scores"): scores,
    }

    fixed = select_admitted_candidates(
        candidate_inputs=inputs,
        score_collection_inputs=score_inputs,
        objectives=(
            _objective(
                contracts,
                objective_id="fixed",
                partition="fixed-reference",
                pairing_mode="fixed_reference",
                utility="tm-score.fixed",
            ),
        ),
        catalog=catalog,
        limit=1,
    )
    paired = select_admitted_candidates(
        candidate_inputs=inputs,
        score_collection_inputs=score_inputs,
        objectives=(
            _objective(
                contracts,
                objective_id="paired",
                partition="per-subject",
                pairing_mode="per_subject_counterpart",
                utility="tm-score.paired",
            ),
        ),
        catalog=catalog,
        limit=1,
    )

    assert [item.candidate_id for item in fixed.candidates.items] == ["subject-a"]
    assert [item.candidate_id for item in paired.candidates.items] == ["subject-b"]


def test_pairwise_selection_fails_closed_on_zero_or_multiple_counterparts() -> None:
    catalog, contracts = _pairwise_catalog()
    subject = Candidate(
        "subject-a",
        data=ProteinSequence("AA"),
    )
    reference_a = Candidate(
        "reference-a",
        data=ProteinSequence("AT"),
    )
    reference_b = Candidate(
        "reference-b",
        data=ProteinSequence("AG"),
    )
    objective = _objective(
        contracts,
        objective_id="paired",
        partition="per-subject",
        pairing_mode="per_subject_counterpart",
        utility="tm-score.paired",
    )
    candidates = CandidateCollection(
        "subjects",
        "protein.sequence",
        [subject],
    )
    inputs = {SelectionInput("subjects", "candidates"): candidates}
    score_input = SelectionInput("scorer", "scores")

    with pytest.raises(SelectionError, match="missing observation"):
        select_admitted_candidates(
            candidate_inputs=inputs,
            score_collection_inputs={
                score_input: ScoreCollection(
                    "wrong-partition",
                    [
                        _pairwise_observation(
                            catalog=catalog,
                            contracts=contracts,
                            subject=subject,
                            reference=reference_a,
                            pairing_mode="per_subject_counterpart",
                            source_partition="other",
                            value=0.5,
                        )
                    ],
                )
            },
            objectives=(objective,),
            catalog=catalog,
            limit=1,
        )

    with pytest.raises(SelectionError, match="exactly one"):
        select_admitted_candidates(
            candidate_inputs=inputs,
            score_collection_inputs={
                score_input: ScoreCollection(
                    "ambiguous",
                    [
                        _pairwise_observation(
                            catalog=catalog,
                            contracts=contracts,
                            subject=subject,
                            reference=reference_a,
                            pairing_mode="per_subject_counterpart",
                            source_partition="per-subject",
                            value=0.5,
                        ),
                        _pairwise_observation(
                            catalog=catalog,
                            contracts=contracts,
                            subject=subject,
                            reference=reference_b,
                            pairing_mode="per_subject_counterpart",
                            source_partition="per-subject",
                            value=0.5,
                        ),
                    ],
                )
            },
            objectives=(objective,),
            catalog=catalog,
            limit=1,
        )


def _pairwise_binding(
    contracts: dict[str, CatalogContract],
) -> CatalogContract:
    return _contract(
        "binding",
        "score.tm.pairwise",
        {
            "node_type": contracts["score.test.pairwise"].reference(),
            "method": contracts["tm-align"].reference(),
            "produced_observations": [
                {
                    "output_port": "scores",
                    "output_partition": "per-subject",
                    "metric": contracts["structure.tm_score"].reference(),
                    "context_profile": PairwiseContextSelector(
                        pairing_mode="per_subject_counterpart",
                        normalization="tm-score/reference-length",
                    ).to_public(),
                    "subject_grain": "candidate",
                    "source_role": "subject",
                    "subject_direction": "input",
                    "subject_port": "subjects",
                    "reference_direction": "input",
                    "reference_port": "counterparts",
                    "pairing_direction": "input",
                    "pairing_port": "pairings",
                    "guaranteed_multiplicity": "one",
                }
            ],
            "observation_propagation": None,
        },
    )


def test_pairwise_output_requires_exact_subject_and_reference_candidates() -> None:
    catalog, contracts = _pairwise_catalog()
    subject = Candidate("subject-a", ProteinSequence("AA"))
    reference = Candidate("reference-a", ProteinSequence("AT"))
    impostor = Candidate("reference-b", ProteinSequence("AG"))
    observation = _pairwise_observation(
        catalog=catalog,
        contracts=contracts,
        subject=subject,
        reference=reference,
        pairing_mode="per_subject_counterpart",
        source_partition="per-subject",
        value=0.7,
    )
    inputs = {
        "subjects": CandidateCollection(
            "subjects",
            "protein.sequence",
            [subject],
        ),
        "counterparts": CandidateCollection(
            "counterparts",
            "protein.sequence",
            [reference],
        ),
        "pairings": _pairing_map(catalog, [(subject, reference)]),
    }

    validate_produced_score_collection(
        catalog=catalog,
        binding=_pairwise_binding(contracts),
        output_port="scores",
        collection=ScoreCollection("pairwise", [observation]),
        inputs=inputs,
        outputs={},
    )

    with pytest.raises(PortValueError, match="reference source"):
        validate_produced_score_collection(
            catalog=catalog,
            binding=_pairwise_binding(contracts),
            output_port="scores",
            collection=ScoreCollection("pairwise", [observation]),
            inputs={
                **inputs,
                "counterparts": CandidateCollection(
                    "counterparts",
                    "protein.sequence",
                    [impostor],
                ),
                "pairings": _pairing_map(catalog, [(subject, impostor)]),
            },
            outputs={},
        )


def test_per_subject_pairing_rejects_one_global_implicit_reference() -> None:
    catalog, contracts = _pairwise_catalog()
    subject_a = Candidate("subject-a", ProteinSequence("AA"))
    subject_b = Candidate("subject-b", ProteinSequence("GG"))
    shared_reference = Candidate("reference-a", ProteinSequence("AT"))
    scores = ScoreCollection(
        "invalid-global-reference",
        [
            _pairwise_observation(
                catalog=catalog,
                contracts=contracts,
                subject=subject,
                reference=shared_reference,
                pairing_mode="per_subject_counterpart",
                source_partition="per-subject",
                value=value,
            )
            for subject, value in ((subject_a, 0.7), (subject_b, 0.8))
        ],
    )

    with pytest.raises(PortValueError, match="reuses one counterpart"):
        validate_produced_score_collection(
            catalog=catalog,
            binding=_pairwise_binding(contracts),
            output_port="scores",
            collection=scores,
            inputs={
                "subjects": CandidateCollection(
                    "subjects",
                    "protein.sequence",
                    [subject_a, subject_b],
                ),
                "counterparts": CandidateCollection(
                    "counterparts",
                    "protein.sequence",
                    [shared_reference],
                ),
                "pairings": _pairing_map(
                    catalog,
                    [
                        (subject_a, shared_reference),
                        (subject_b, shared_reference),
                    ],
                ),
            },
            outputs={},
        )


def test_per_subject_pairing_rejects_a_swapped_bijection() -> None:
    catalog, contracts = _pairwise_catalog()
    subject_a = Candidate("subject-a", ProteinSequence("AA"))
    subject_b = Candidate("subject-b", ProteinSequence("GG"))
    reference_a = Candidate("reference-a", ProteinSequence("AT"))
    reference_b = Candidate("reference-b", ProteinSequence("GT"))
    scores = ScoreCollection(
        "swapped-bijection",
        [
            _pairwise_observation(
                catalog=catalog,
                contracts=contracts,
                subject=subject,
                reference=reference,
                pairing_mode="per_subject_counterpart",
                source_partition="per-subject",
                value=value,
            )
            for subject, reference, value in (
                (subject_a, reference_a, 0.7),
                (subject_b, reference_b, 0.8),
            )
        ],
    )

    with pytest.raises(PortValueError, match="pairing source"):
        validate_produced_score_collection(
            catalog=catalog,
            binding=_pairwise_binding(contracts),
            output_port="scores",
            collection=scores,
            inputs={
                "subjects": CandidateCollection(
                    "subjects",
                    "protein.sequence",
                    [subject_a, subject_b],
                ),
                "counterparts": CandidateCollection(
                    "counterparts",
                    "protein.sequence",
                    [reference_a, reference_b],
                ),
                "pairings": _pairing_map(
                    catalog,
                    [
                        (subject_a, reference_b),
                        (subject_b, reference_a),
                    ],
                ),
            },
            outputs={},
        )


def test_controlled_union_preserves_partitions_and_rejects_invented_entries() -> None:
    catalog, contracts = _pairwise_catalog()
    subject = Candidate("subject-a", ProteinSequence("AA"))
    reference = Candidate("reference-a", ProteinSequence("AT"))
    fixed = _pairwise_observation(
        catalog=catalog,
        contracts=contracts,
        subject=subject,
        reference=reference,
        pairing_mode="fixed_reference",
        source_partition="fixed-reference",
        value=0.4,
    )
    paired = replace(
        fixed,
        context=replace(
            fixed.context,
            pairing_mode="per_subject_counterpart",
        ),
        source_partition="per-subject",
        value=0.8,
    )
    binding = _contract(
        "binding",
        "score.union",
        {
            "node_type": contracts["score.test.pairwise"].reference(),
            "method": contracts["tm-align"].reference(),
            "produced_observations": [],
            "observation_propagation": {
                "schema_version": "2.1.0",
                "mode": "union",
                "output_port": "scores",
                "input_ports": ["left", "right"],
                "filter": None,
            },
        },
    )
    inputs = {
        "left": ScoreCollection("left", [fixed]),
        "right": ScoreCollection("right", [paired]),
    }

    validate_produced_score_collection(
        catalog=catalog,
        binding=binding,
        output_port="scores",
        collection=ScoreCollection("union", [fixed, paired]),
        inputs=inputs,
        outputs={},
    )

    with pytest.raises(PortValueError, match="invent"):
        validate_produced_score_collection(
            catalog=catalog,
            binding=binding,
            output_port="scores",
            collection=ScoreCollection(
                "union",
                [fixed, replace(paired, source_partition="invented")],
            ),
            inputs=inputs,
            outputs={},
        )


def test_controlled_pass_through_requires_the_exact_source_collection() -> None:
    catalog, contracts = _pairwise_catalog()
    subject = Candidate("subject-a", ProteinSequence("AA"))
    reference = Candidate("reference-a", ProteinSequence("AT"))
    observation = _pairwise_observation(
        catalog=catalog,
        contracts=contracts,
        subject=subject,
        reference=reference,
        pairing_mode="fixed_reference",
        source_partition="fixed-reference",
        value=0.4,
    )
    binding = _contract(
        "binding",
        "score.pass-through",
        {
            "node_type": contracts["score.test.pairwise"].reference(),
            "method": contracts["tm-align"].reference(),
            "produced_observations": [],
            "observation_propagation": {
                "schema_version": "2.1.0",
                "mode": "pass_through",
                "output_port": "scores",
                "input_ports": ["source"],
                "filter": None,
            },
        },
    )
    inputs = {"source": ScoreCollection("source", [observation])}

    validate_produced_score_collection(
        catalog=catalog,
        binding=binding,
        output_port="scores",
        collection=ScoreCollection("copied", [observation]),
        inputs=inputs,
        outputs={},
    )

    with pytest.raises(PortValueError, match="cannot omit"):
        validate_produced_score_collection(
            catalog=catalog,
            binding=binding,
            output_port="scores",
            collection=ScoreCollection("copied", []),
            inputs=inputs,
            outputs={},
        )


def test_controlled_filter_publishes_every_exact_matching_observation() -> None:
    catalog, contracts = _pairwise_catalog()
    subject = Candidate("subject-a", ProteinSequence("AA"))
    reference = Candidate("reference-a", ProteinSequence("AT"))
    fixed = _pairwise_observation(
        catalog=catalog,
        contracts=contracts,
        subject=subject,
        reference=reference,
        pairing_mode="fixed_reference",
        source_partition="fixed-reference",
        value=0.4,
    )
    paired = replace(
        fixed,
        context=replace(
            fixed.context,
            pairing_mode="per_subject_counterpart",
        ),
        source_partition="per-subject",
        value=0.8,
    )
    binding = _contract(
        "binding",
        "score.filter",
        {
            "node_type": contracts["score.test.pairwise"].reference(),
            "method": contracts["tm-align"].reference(),
            "produced_observations": [],
            "observation_propagation": {
                "schema_version": "2.1.0",
                "mode": "filter",
                "output_port": "scores",
                "input_ports": ["source"],
                "filter": {"source_partition": "fixed-reference"},
            },
        },
    )
    inputs = {"source": ScoreCollection("source", [fixed, paired])}

    validate_produced_score_collection(
        catalog=catalog,
        binding=binding,
        output_port="scores",
        collection=ScoreCollection("filtered", [fixed]),
        inputs=inputs,
        outputs={},
    )

    with pytest.raises(PortValueError, match="exact filter result"):
        validate_produced_score_collection(
            catalog=catalog,
            binding=binding,
            output_port="scores",
            collection=ScoreCollection("filtered", []),
            inputs=inputs,
            outputs={},
        )


def test_produced_pairwise_and_propagation_contracts_are_closed_descriptors() -> None:
    produced = ProducedObservationDefinition(
        output_port="scores",
        output_partition="per-subject",
        metric=ContractIdentity(
            "metric",
            "structure.tm_score",
            "2.1.0",
        ),
        context_profile={
            "kind": "pairwise",
            "subject_role": "subject",
            "reference_role": "reference",
            "pairing_mode": "per_subject_counterpart",
            "normalization": "tm-score/reference-length",
        },
        subject_grain="candidate",
        source_role="subject",
        subject_direction="input",
        subject_port="subjects",
        reference_direction="input",
        reference_port="counterparts",
        pairing_direction="input",
        pairing_port="pairings",
        guaranteed_multiplicity="one",
    )
    propagation = ObservationPropagationDefinition(
        mode="union",
        output_port="scores",
        input_ports=("fixed_scores", "paired_scores"),
    )

    assert produced.descriptor_template()["output_partition"] == "per-subject"
    assert produced.descriptor_template()["reference_port"] == "counterparts"
    assert produced.descriptor_template()["pairing_port"] == "pairings"
    assert propagation.descriptor_template() == {
        "schema_version": "2.1.0",
        "mode": "union",
        "output_port": "scores",
        "input_ports": ("fixed_scores", "paired_scores"),
        "filter": None,
    }

    with pytest.raises(CatalogBuildError, match="at least two"):
        ObservationPropagationDefinition(
            mode="union",
            output_port="scores",
            input_ports=("scores",),
        )

    with pytest.raises(CatalogBuildError, match="both reference"):
        replace(produced, reference_port=None)

    with pytest.raises(CatalogBuildError, match="both pairing"):
        replace(produced, pairing_port=None)

    propagation_public = {
        **propagation.descriptor_template(),
        "input_ports": list(propagation.input_ports),
    }
    validate_schema(
        "#/$defs/ObservationPropagationDeclaration",
        propagation_public,
    )
    with pytest.raises(ProtocolValidationError, match="unexpected"):
        validate_schema(
            "#/$defs/ObservationPropagationDeclaration",
            {
                **propagation_public,
                "mode": "filter",
                "input_ports": ["fixed_scores"],
                "filter": {
                    "source_partition": "fixed-reference",
                    "unexpected": True,
                },
            },
        )


def _compiler_catalog() -> tuple[FrozenCatalog, dict[str, CatalogContract]]:
    base, scoring = _pairwise_catalog()
    selection_catalog = build_frozen_catalog((SELECTION_PACKAGE,))
    candidate_type = base.require_port_type("candidate.collection", PORT_VERSION)
    pairing_type = base.require_port_type("candidate.pairing", PORT_VERSION)
    score_type = base.require_port_type(
        "score.collection",
        SCORE_PORT_VERSION,
    )
    producer_node = _contract(
        "node_type",
        "score.pairwise.producer",
        {
            "inputs": [],
            "outputs": [
                {
                    "name": "candidates",
                    "port_type": candidate_type.reference(),
                    "required": True,
                    "multiplicity": "one",
                    "scientific_meaning": "Pairwise subject Candidates.",
                },
                {
                    "name": "references",
                    "port_type": candidate_type.reference(),
                    "required": True,
                    "multiplicity": "one",
                    "scientific_meaning": "Pairwise reference Candidates.",
                },
                {
                    "name": "scores",
                    "port_type": score_type.reference(),
                    "required": True,
                    "multiplicity": "one",
                    "scientific_meaning": "Pairwise score Observations.",
                },
                {
                    "name": "pairings",
                    "port_type": pairing_type.reference(),
                    "required": True,
                    "multiplicity": "one",
                    "scientific_meaning": "Exact subject-reference pairing.",
                },
            ],
            "node_parameters": {},
        },
        version=NODE_BINDING_VERSION,
    )
    union_node = _contract(
        "node_type",
        "score.partition.union",
        {
            "inputs": [
                {
                    "name": "left",
                    "port_type": score_type.reference(),
                    "required": True,
                    "multiplicity": "one",
                    "scientific_meaning": "Left score partition.",
                },
                {
                    "name": "right",
                    "port_type": score_type.reference(),
                    "required": True,
                    "multiplicity": "one",
                    "scientific_meaning": "Right score partition.",
                },
            ],
            "outputs": [
                {
                    "name": "scores",
                    "port_type": score_type.reference(),
                    "required": True,
                    "multiplicity": "one",
                    "scientific_meaning": "Union of exact score partitions.",
                }
            ],
            "node_parameters": {},
        },
        version=NODE_BINDING_VERSION,
    )
    producer_binding = _contract(
        "binding",
        "score.pairwise.producer.direct",
        {
            "node_type": producer_node.reference(),
            "method": scoring["tm-align"].reference(),
            "binding_parameters": {},
            "produced_observations": [
                {
                    "output_port": "scores",
                    "output_partition": "fixed-reference",
                    "metric": scoring["structure.tm_score"].reference(),
                    "context_profile": PairwiseContextSelector(
                        pairing_mode="fixed_reference",
                        normalization="tm-score/reference-length",
                    ).to_public(),
                    "subject_grain": "candidate",
                    "source_role": "subject",
                    "subject_direction": "output",
                    "subject_port": "candidates",
                    "reference_direction": "output",
                    "reference_port": "references",
                    "guaranteed_multiplicity": "one",
                },
                {
                    "output_port": "scores",
                    "output_partition": "per-subject",
                    "metric": scoring["structure.tm_score"].reference(),
                    "context_profile": PairwiseContextSelector(
                        pairing_mode="per_subject_counterpart",
                        normalization="tm-score/reference-length",
                    ).to_public(),
                    "subject_grain": "candidate",
                    "source_role": "subject",
                    "subject_direction": "output",
                    "subject_port": "candidates",
                    "reference_direction": "output",
                    "reference_port": "references",
                    "pairing_direction": "output",
                    "pairing_port": "pairings",
                    "guaranteed_multiplicity": "one",
                },
            ],
            "observation_propagation": None,
        },
        version=NODE_BINDING_VERSION,
    )
    union_binding = _contract(
        "binding",
        "score.partition.union.direct",
        {
            "node_type": union_node.reference(),
            "method": scoring["tm-align"].reference(),
            "binding_parameters": {},
            "produced_observations": [],
            "observation_propagation": {
                "schema_version": "2.1.0",
                "mode": "union",
                "output_port": "scores",
                "input_ports": ["left", "right"],
                "filter": None,
            },
        },
        version=NODE_BINDING_VERSION,
    )
    contracts = {
        **scoring,
        producer_node.contract_id: producer_node,
        union_node.contract_id: union_node,
        producer_binding.contract_id: producer_binding,
        union_binding.contract_id: union_binding,
    }
    availability = tuple(
        {
            "binding": binding.reference(),
            "observed_at": "2026-07-29T00:00:00Z",
            "available": True,
        }
        for binding in (producer_binding, union_binding)
    )

    def fail_if_factory_is_constructed(_context: object) -> object:
        raise AssertionError("compile-only factory was constructed")

    factories = {
        (binding.contract_id, binding.contract_version): (
            ScientificOperationFactory(
                behavior=BehaviorReference(
                    f"{binding.contract_id}/factory",
                    "2.1.0",
                    {},
                ),
                build=fail_if_factory_is_constructed,
            )
        )
        for binding in (producer_binding, union_binding)
    }
    readiness = {
        (binding.contract_id, binding.contract_version): (
            ReadinessDeclaration(
                behavior=BehaviorReference(
                    f"{binding.contract_id}/readiness",
                    "2.1.0",
                    {},
                ),
                prerequisites={},
                check=lambda _input: ReadinessResult(True),
            )
        )
        for binding in (producer_binding, union_binding)
    }
    return (
        replace(
            base,
            contracts=(
                *contracts.values(),
                *selection_catalog.contracts,
            ),
            availability=(
                *availability,
                *selection_catalog.availability,
            ),
            factories={
                **selection_catalog.factories,
                **factories,
            },
            readiness_declarations={
                **selection_catalog.readiness_declarations,
                **readiness,
            },
            owners=selection_catalog.owners,
        ),
        contracts,
    )


def _compiler_workflow(
    contracts: dict[str, CatalogContract],
    *,
    source_partition: str = "fixed-reference",
) -> WorkflowDocument:
    return WorkflowDocument(
        schema_version="2.1.0",
        workflow_id="pairwise-capability",
        nodes=(
            WorkflowNodeInstance(
                node_id="producer",
                node_type_id="score.pairwise.producer",
                node_type_version=NODE_BINDING_VERSION,
                binding_id="score.pairwise.producer.direct",
                binding_version=NODE_BINDING_VERSION,
                node_parameters={},
                binding_parameters={},
            ),
            WorkflowNodeInstance(
                node_id="union",
                node_type_id="score.partition.union",
                node_type_version=NODE_BINDING_VERSION,
                binding_id="score.partition.union.direct",
                binding_version=NODE_BINDING_VERSION,
                node_parameters={},
                binding_parameters={},
            ),
            WorkflowNodeInstance(
                node_id="select",
                node_type_id="selection.sort",
                node_type_version=SELECTION_NODE_BINDING_VERSION,
                binding_id="selection.sort.direct",
                binding_version=SELECTION_NODE_BINDING_VERSION,
                node_parameters={"objective_id": "fixed"},
                binding_parameters={},
            ),
        ),
        edges=(
            V2WorkflowEdge("producer", "scores", "union", "left"),
            V2WorkflowEdge("producer", "scores", "union", "right"),
            V2WorkflowEdge(
                "producer",
                "candidates",
                "select",
                "candidates",
            ),
            V2WorkflowEdge("union", "scores", "select", "scores"),
        ),
        contract_lock=(),
        selection_objectives=(
            replace(
                _objective(
                    contracts,
                    objective_id="fixed",
                    partition=source_partition,
                    pairing_mode="fixed_reference",
                    utility="tm-score.fixed",
                ),
                candidate_input=SelectionInput("producer", "candidates"),
                score_collection_input=SelectionInput("union", "scores"),
            ),
        ),
    )


def test_compiler_derives_exact_capability_through_controlled_union() -> None:
    catalog, contracts = _compiler_catalog()
    workflow = _compiler_workflow(contracts)

    compiled = compile_workflow(
        relock_workflow(workflow, catalog),
        workflow_commit_revision=1,
        catalog=catalog,
    )

    assert compiled.execution_plan.workflow_commit_revision == 1
    assert compiled.execution_plan.selection_objectives[0].source_partition == (
        "fixed-reference"
    )


def test_compiler_rejects_unknown_partition_before_any_provider_invocation() -> None:
    catalog, contracts = _compiler_catalog()
    workflow = _compiler_workflow(
        contracts,
        source_partition="global-reference",
    )

    with pytest.raises(
        WorkflowCompileError,
        match="cannot guarantee",
    ):
        compile_workflow(
            relock_workflow(workflow, catalog),
            workflow_commit_revision=1,
            catalog=catalog,
        )


def test_output_score_cannot_claim_a_future_candidate_reference() -> None:
    catalog, contracts = _compiler_catalog()
    subject = Candidate("raw-subject", ProteinSequence("AA"))
    reference = Candidate("raw-reference", ProteinSequence("AT"))
    fixed = _pairwise_observation(
        catalog=catalog,
        contracts=contracts,
        subject=subject,
        reference=reference,
        pairing_mode="fixed_reference",
        source_partition="fixed-reference",
        value=0.4,
    )
    paired = _pairwise_observation(
        catalog=catalog,
        contracts=contracts,
        subject=subject,
        reference=reference,
        pairing_mode="per_subject_counterpart",
        source_partition="per-subject",
        value=0.8,
    )
    outputs = {
        "candidates": CandidateCollection(
            "raw-subjects",
            "protein.sequence",
            [subject],
        ),
        "references": CandidateCollection(
            "raw-references",
            "protein.sequence",
            [reference],
        ),
        "pairings": CandidatePairingIntent(
            (
                CandidatePairingIntentEntry(
                    subject_candidate_id=subject.candidate_id,
                    reference_candidate_id=reference.candidate_id,
                ),
            )
        ),
        "scores": ScoreCollection("raw-scores", [fixed, paired]),
    }
    with pytest.raises(
        PortValueError,
        match="cannot reference a same-operation output Candidate",
    ):
        normalize_scientific_outputs(
            node_id="producer",
            result_identity="sha256:" + "a" * 64,
            inputs={},
            outputs=outputs,
            candidate_content_digest=lambda _candidate: (
                "sha256:" + "b" * 64
            ),
        )


def test_one_raw_candidate_cannot_claim_two_output_slots() -> None:
    shared = Candidate("raw-shared", ProteinSequence("AA"))
    outputs = {
        "candidates": CandidateCollection(
            "raw-subjects",
            "protein.sequence",
            [shared],
        ),
        "references": CandidateCollection(
            "raw-references",
            "protein.sequence",
            [shared],
        ),
    }
    with pytest.raises(
        PortValueError,
        match="reuses one producer identity",
    ):
        normalize_scientific_outputs(
            node_id="producer",
            result_identity="sha256:" + "a" * 64,
            inputs={},
            outputs=outputs,
            candidate_content_digest=lambda _candidate: (
                "sha256:" + "b" * 64
            ),
        )

    assert shared.candidate_id == "raw-shared"
    assert outputs["candidates"].collection_id == "raw-subjects"
    assert outputs["references"].collection_id == "raw-references"
