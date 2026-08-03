from dataclasses import replace
from types import SimpleNamespace

import pytest

from core.operation import (
    CandidatePairingIntent,
    CandidatePairingIntentEntry,
    InputContentDigests,
)
from core.port_types import (
    BehaviorReference,
    CatalogBuildError,
    PortTypeDefinition,
    PortValueError,
    canonical_sha256,
)
from core.scoring_v2 import (
    ResolvedMetricFacts,
    validate_produced_score_collection_from_facts,
)
from core.value_admission import normalize_scientific_outputs
from core.run_execution_v2 import V2RunService
from datatypes import (
    Candidate,
    CandidateCollection,
    CandidateDataReference,
    ExactContractReference,
    IntrinsicObservationContext,
    PairwiseCandidateMapping,
    PairwiseCandidateMatch,
    PairwiseObservationContext,
    PairwiseParticipant,
    ProteinSequence,
    ProteinStructure,
    ResidueAxisReference,
    ResidueLayout,
    ScoreCollection,
    ScoreObservation,
)
from tests.fixtures.scientific_operation import operation_context


def _method_reference(
    contract_id: str,
    digest_character: str,
) -> ExactContractReference:
    return ExactContractReference(
        "method",
        contract_id,
        "1.0.0",
        "sha256:" + (digest_character * 64),
    )


def _intrinsic_score(
    subject: CandidateDataReference,
    *,
    value: float = 0.5,
) -> ScoreObservation:
    return ScoreObservation(
        subject=subject,
        metric=ExactContractReference(
            "metric",
            "fixture.quality",
            "1.0.0",
            "sha256:" + ("b" * 64),
        ),
        method=_method_reference("fixture.measure", "c"),
        context=IntrinsicObservationContext(),
        value=value,
    )


def test_input_content_digests_snapshots_caller_owned_sequences() -> None:
    value_content_digests = ["sha256:" + ("1" * 64)]
    candidate_digest = CandidateDataReference(
        candidate_id="candidate-1",
        data_type_id="protein.sequence",
        content_digest="sha256:" + ("2" * 64),
    )
    candidate_data = [candidate_digest]

    admitted = InputContentDigests(
        port_type_id="candidate.collection",
        value_content_digests=value_content_digests,  # type: ignore[arg-type]
        candidate_data=candidate_data,  # type: ignore[arg-type]
    )

    value_content_digests.append("sha256:" + ("3" * 64))
    candidate_data.clear()

    assert admitted.value_content_digests == ("sha256:" + ("1" * 64),)
    assert admitted.candidate_data == (candidate_digest,)


def test_direct_operation_context_preserves_axis_and_method_sources() -> None:
    method = _method_reference("fixture.materializer", "a")
    metric = ExactContractReference(
        "metric",
        "fixture.metric",
        "1.0.0",
        "sha256:" + ("b" * 64),
    )
    binding = SimpleNamespace(
        descriptor={
            "method": {
                "contract_kind": method.contract_kind,
                "contract_id": method.contract_id,
                "contract_version": method.contract_version,
                "contract_digest": method.contract_digest,
            },
            "produced_observations": (
                {
                    "output_port": "scores",
                    "output_partition": "default",
                    "metric": {
                        "contract_kind": metric.contract_kind,
                        "contract_id": metric.contract_id,
                        "contract_version": metric.contract_version,
                        "contract_digest": metric.contract_digest,
                    },
                    "context_profile": {"kind": "intrinsic"},
                    "subject_grain": "candidate",
                    "source_role": "subject",
                    "subject_direction": "input",
                    "subject_port": "candidates",
                    "axis_direction": "input",
                    "axis_port": "facts",
                    "method_direction": "input",
                    "method_port": "facts",
                    "guaranteed_multiplicity": "one",
                },
            ),
        }
    )
    catalog = SimpleNamespace(
        require_contract=lambda *args: binding,
    )

    context = operation_context(
        catalog,
        "fixture.materializer.direct",
        object(),
    )

    observation = context.produced_observations[0]
    assert (
        observation.axis_direction,
        observation.axis_port,
        observation.method_direction,
        observation.method_port,
    ) == ("input", "facts", "input", "facts")


def test_observation_method_projection_declaration_and_runtime_are_atomic(
) -> None:
    behavior = BehaviorReference(
        "fixture.confidence/method_projection",
        "1.0.0",
        {"projection": "exact-provider-method"},
    )
    common = {
        "type_id": "fixture.confidence",
        "version": "1.0.0",
        "validator": BehaviorReference(
            "fixture.confidence/validate", "1.0.0", {}
        ),
        "codec": BehaviorReference(
            "fixture.confidence/codec", "1.0.0", {}
        ),
        "content_identity": BehaviorReference(
            "fixture.confidence/content", "1.0.0", {}
        ),
    }

    with pytest.raises(CatalogBuildError, match="provided together"):
        PortTypeDefinition(
            **common,
            observation_method_projection=behavior,
        )

    method = ExactContractReference(
        "method",
        "provider.inference",
        "1.0.0",
        "sha256:" + ("e" * 64),
    )
    definition = PortTypeDefinition(
        **common,
        observation_method_projection=behavior,
        runtime_observation_method_projection=lambda _: (method,),
    )
    assert definition.observation_method_references("facts") == (method,)
    assert "observation_method_projection" in definition.descriptor()


@pytest.mark.parametrize(
    "projected_method",
    (
        _method_reference("fixture.producer", "d"),
        _method_reference("fixture.other", "c"),
    ),
)
def test_output_admission_rejects_a_method_not_owned_by_the_binding(
    projected_method: ExactContractReference,
) -> None:
    producing_method = _method_reference("fixture.producer", "c")
    port_type = PortTypeDefinition(
        type_id="fixture.confidence_facts",
        version="1.0.0",
        validator=BehaviorReference(
            "fixture.confidence_facts/validate", "1.0.0", {}
        ),
        codec=BehaviorReference(
            "fixture.confidence_facts/codec", "1.0.0", {}
        ),
        content_identity=BehaviorReference(
            "fixture.confidence_facts/content", "1.0.0", {}
        ),
        runtime_validator=lambda value: None,
        runtime_to_wire=lambda value: value,
        runtime_from_wire=lambda value: value,
        observation_method_projection=BehaviorReference(
            "fixture.confidence_facts/method_projection",
            "1.0.0",
            {"projection": "exact-method"},
        ),
        runtime_observation_method_projection=lambda _: (projected_method,),
    )
    runtime_port = SimpleNamespace(
        declaration={"required": True, "multiplicity": "one"},
        port_type=port_type,
    )
    node = SimpleNamespace(
        node_id="producer",
        method=producing_method,
        _runtime=SimpleNamespace(
            output_ports={"confidence_facts": runtime_port},
            binding_contract=SimpleNamespace(
                descriptor={"produced_observations": ()}
            ),
            produced_metric_facts={},
        ),
    )
    plan = SimpleNamespace(
        _runtime=SimpleNamespace(candidate_data_port_types={})
    )

    with pytest.raises(
        PortValueError,
        match="does not equal the producing Binding Method",
    ):
        V2RunService._admit_outputs(
            object.__new__(V2RunService),
            plan,
            node,
            {"confidence_facts": "facts"},
            inputs={},
            input_content_digests={},
        )


def test_output_admission_accepts_the_exact_binding_method_projection() -> None:
    producing_method = _method_reference("fixture.producer", "c")
    port_type = PortTypeDefinition(
        type_id="fixture.confidence_facts",
        version="1.0.0",
        validator=BehaviorReference(
            "fixture.confidence_facts/validate", "1.0.0", {}
        ),
        codec=BehaviorReference(
            "fixture.confidence_facts/codec", "1.0.0", {}
        ),
        content_identity=BehaviorReference(
            "fixture.confidence_facts/content", "1.0.0", {}
        ),
        runtime_validator=lambda value: None,
        runtime_to_wire=lambda value: value,
        runtime_from_wire=lambda value: value,
        observation_method_projection=BehaviorReference(
            "fixture.confidence_facts/method_projection",
            "1.0.0",
            {"projection": "exact-method"},
        ),
        runtime_observation_method_projection=lambda _: (producing_method,),
    )
    runtime_port = SimpleNamespace(
        declaration={"required": True, "multiplicity": "one"},
        port_type=port_type,
    )
    node = SimpleNamespace(
        node_id="producer",
        method=producing_method,
        _runtime=SimpleNamespace(
            output_ports={"confidence_facts": runtime_port},
            binding_contract=SimpleNamespace(
                descriptor={"produced_observations": ()}
            ),
            produced_metric_facts={},
        ),
    )
    plan = SimpleNamespace(
        _runtime=SimpleNamespace(candidate_data_port_types={})
    )

    _, admitted = V2RunService._admit_outputs(
        object.__new__(V2RunService),
        plan,
        node,
        {"confidence_facts": "facts"},
        inputs={},
        input_content_digests={},
    )

    assert admitted[("producer", "confidence_facts")].runtime_values == (
        "facts",
    )


def test_produced_observation_method_uses_declared_projection_or_binding_default(
) -> None:
    digest = "sha256:" + ("a" * 64)
    subject = CandidateDataReference(
        "candidate-1", "protein.sequence", digest
    )
    metric = ExactContractReference(
        "metric", "quality", "1.0.0", "sha256:" + ("b" * 64)
    )
    binding_method = ExactContractReference(
        "method", "materialize", "1.0.0", "sha256:" + ("c" * 64)
    )
    provider_method = ExactContractReference(
        "method", "provider", "1.0.0", "sha256:" + ("d" * 64)
    )
    candidate = Candidate("candidate-1", ProteinSequence("AA"))
    candidates = CandidateCollection(
        "candidates", "protein.sequence", [candidate]
    )
    facts = ResolvedMetricFacts(
        reference=metric,
        value_shape="scalar",
        minimum=0,
        maximum=1,
        allow_null=False,
        require_finite=True,
        exact_binary32=False,
        requires_residue_axis=False,
    )
    metric_key = (
        metric.contract_kind,
        metric.contract_id,
        metric.contract_version,
        metric.contract_digest,
    )
    declaration = {
        "output_port": "scores",
        "output_partition": "default",
        "metric": {
            "contract_kind": metric.contract_kind,
            "contract_id": metric.contract_id,
            "contract_version": metric.contract_version,
            "contract_digest": metric.contract_digest,
        },
        "context_profile": {"kind": "intrinsic"},
        "subject_grain": "candidate",
        "source_role": "subject",
        "subject_direction": "input",
        "subject_port": "candidates",
        "guaranteed_multiplicity": "one",
    }

    def validate(
        method: ExactContractReference,
        *,
        dynamic: bool,
        projected: tuple[ExactContractReference, ...],
    ) -> None:
        dynamic_declaration = (
            declaration
            | {
                "method_direction": "input",
                "method_port": "confidence",
            }
            if dynamic
            else declaration
        )
        collection = ScoreCollection(
            "scores",
            [
                ScoreObservation(
                    subject=subject,
                    metric=metric,
                    method=method,
                    context=IntrinsicObservationContext(),
                    value=0.5,
                )
            ],
        )
        validate_produced_score_collection_from_facts(
            binding_descriptor={
                "method": {
                    "contract_kind": binding_method.contract_kind,
                    "contract_id": binding_method.contract_id,
                    "contract_version": binding_method.contract_version,
                    "contract_digest": binding_method.contract_digest,
                },
                "produced_observations": [dynamic_declaration],
            },
            output_port="scores",
            collection=collection,
            inputs={"candidates": candidates, "confidence": "facts"},
            outputs={"scores": collection},
            metric_facts={metric_key: facts},
            axis_references={},
            method_references={
                ("input", "confidence"): projected
            },
            candidate_references={
                ("input", "candidates"): (subject,)
            },
        )

    validate(provider_method, dynamic=True, projected=(provider_method,))
    validate(binding_method, dynamic=False, projected=())

    with pytest.raises(PortValueError, match="undeclared Method"):
        validate(provider_method, dynamic=True, projected=())
    with pytest.raises(PortValueError, match="undeclared Method"):
        validate(
            replace(provider_method, contract_digest="sha256:" + ("e" * 64)),
            dynamic=True,
            projected=(provider_method,),
        )
    with pytest.raises(PortValueError, match="undeclared Method"):
        validate(provider_method, dynamic=False, projected=(provider_method,))


def _candidate_outputs(pairing: CandidatePairingIntent) -> dict[str, object]:
    return {
        "subjects": CandidateCollection(
            "raw-subjects",
            "protein.sequence",
            [Candidate("raw-subject", ProteinSequence("AA"))],
        ),
        "references": CandidateCollection(
            "raw-references",
            "protein.sequence",
            [Candidate("raw-reference", ProteinSequence("AT"))],
        ),
        "pairing": pairing,
    }


def test_score_subject_cannot_project_a_same_operation_output_candidate(
) -> None:
    content_digest = "sha256:" + ("a" * 64)
    reference = ExactContractReference(
        "metric",
        "quality",
        "2.1.0",
        "sha256:" + ("b" * 64),
    )
    method = ExactContractReference(
        "method",
        "fixture",
        "2.1.0",
        "sha256:" + ("c" * 64),
    )
    with pytest.raises(PortValueError, match="same-operation output"):
        normalize_scientific_outputs(
            node_id="source",
            result_identity="sha256:" + ("d" * 64),
            inputs={},
            outputs={
                "candidates": CandidateCollection(
                    "raw-candidates",
                    "protein.sequence",
                    [Candidate("raw-subject", ProteinSequence("AA"))],
                ),
                "scores": ScoreCollection(
                    "raw-scores",
                    [
                        ScoreObservation(
                            subject=CandidateDataReference(
                                "raw-subject",
                                "protein.sequence",
                                content_digest,
                            ),
                            metric=reference,
                            method=method,
                            context=IntrinsicObservationContext(),
                            value=0.5,
                        )
                    ],
                ),
            },
            candidate_content_digest=lambda _: content_digest,
        )


def test_score_axis_source_is_not_rebound_to_the_direct_candidate_input(
) -> None:
    structure_digest = "sha256:" + ("1" * 64)
    subject = CandidateDataReference(
        "structure",
        "protein.structure",
        structure_digest,
    )
    axis_source = CandidateDataReference(
        "upstream-sequence",
        "protein.sequence",
        "sha256:" + ("2" * 64),
    )
    axis = ResidueAxisReference(
        axis_kind="prediction_input",
        axis_contract=ExactContractReference(
            "port_type",
            "fixture.prediction_axis",
            "1.0.0",
            "sha256:" + ("3" * 64),
        ),
        axis_content_digest="sha256:" + ("4" * 64),
        source=axis_source,
        layout=ResidueLayout("A", 1, ("A:1",)),
    )
    score = replace(_intrinsic_score(subject), residue_axis=axis)

    normalized = normalize_scientific_outputs(
        node_id="materializer",
        result_identity="sha256:" + ("5" * 64),
        inputs={
            "structures": CandidateCollection(
                "structures",
                "protein.structure",
                [Candidate("structure", ProteinStructure("ATOM\n"))],
            ),
            "confidence_facts": "admitted-axis-owner",
        },
        outputs={"scores": ScoreCollection("raw", [score])},
        candidate_content_digest=lambda candidate: (
            structure_digest
            if candidate.candidate_id == "structure"
            else pytest.fail("axis source must be admitted by its axis Port")
        ),
    )

    assert normalized["scores"].entries[0].residue_axis == axis


def test_observation_propagation_preserves_admitted_pairwise_references(
) -> None:
    subject = CandidateDataReference(
        "candidate-subject",
        "protein.structure",
        "sha256:" + ("1" * 64),
    )
    reference = CandidateDataReference(
        "candidate-reference",
        "protein.structure",
        "sha256:" + ("2" * 64),
    )
    observation = replace(
        _intrinsic_score(subject),
        context=PairwiseObservationContext(
            subject=PairwiseParticipant("subject", subject),
            reference=PairwiseParticipant("reference", reference),
            pairing_mode="fixed_reference",
            normalization="tm-score/reference-length",
        ),
    )

    normalized = normalize_scientific_outputs(
        node_id="merge",
        result_identity="sha256:" + ("3" * 64),
        inputs={"source": ScoreCollection("source", [observation])},
        outputs={"scores": ScoreCollection("raw-output", [observation])},
        candidate_content_digest=lambda _: pytest.fail(
            "propagated admitted Score references must not be recomputed"
        ),
        observation_propagation={
            "schema_version": "2.1.0",
            "mode": "pass_through",
            "output_port": "scores",
            "input_ports": ("source",),
            "filter": None,
        },
    )

    assert normalized["scores"].entries == (observation,)


@pytest.mark.parametrize(
    ("conflicting_type", "conflicting_digest"),
    (
        ("protein.sequence", "sha256:" + ("1" * 64)),
        ("protein.structure", "sha256:" + ("2" * 64)),
    ),
)
def test_observation_propagation_rejects_conflicting_candidate_references(
    conflicting_type: str,
    conflicting_digest: str,
) -> None:
    left_subject = CandidateDataReference(
        "candidate-shared",
        "protein.structure",
        "sha256:" + ("1" * 64),
    )
    right_subject = CandidateDataReference(
        "candidate-shared",
        conflicting_type,
        conflicting_digest,
    )

    with pytest.raises(
        PortValueError,
        match="conflicting propagated Candidate references",
    ):
        normalize_scientific_outputs(
            node_id="merge",
            result_identity="sha256:" + ("3" * 64),
            inputs={
                "left": ScoreCollection(
                    "left", [_intrinsic_score(left_subject)]
                ),
                "right": ScoreCollection(
                    "right", [_intrinsic_score(right_subject)]
                ),
            },
            outputs={
                "scores": ScoreCollection(
                    "raw-output", [_intrinsic_score(left_subject)]
                )
            },
            candidate_content_digest=lambda _: pytest.fail(
                "propagated admitted Score references must not be recomputed"
            ),
            observation_propagation={
                "schema_version": "2.1.0",
                "mode": "union",
                "output_port": "scores",
                "input_ports": ("left", "right"),
                "filter": None,
            },
        )


def test_observation_propagation_rejects_a_ghost_subject() -> None:
    admitted = CandidateDataReference(
        "candidate-admitted",
        "protein.structure",
        "sha256:" + ("1" * 64),
    )
    ghost = CandidateDataReference(
        "candidate-ghost",
        "protein.structure",
        "sha256:" + ("2" * 64),
    )

    with pytest.raises(
        PortValueError,
        match="unknown propagated Candidate reference",
    ):
        normalize_scientific_outputs(
            node_id="filter",
            result_identity="sha256:" + ("3" * 64),
            inputs={
                "source": ScoreCollection(
                    "source", [_intrinsic_score(admitted)]
                )
            },
            outputs={
                "scores": ScoreCollection(
                    "raw-output", [_intrinsic_score(ghost)]
                )
            },
            candidate_content_digest=lambda _: pytest.fail(
                "propagated admitted Score references must not be recomputed"
            ),
            observation_propagation={
                "schema_version": "2.1.0",
                "mode": "filter",
                "output_port": "scores",
                "input_ports": ("source",),
                "filter": {"source_partition": "default"},
            },
        )


def test_pairing_intent_projects_normalized_exact_candidate_content() -> None:
    subject_digest = "sha256:" + ("a" * 64)
    reference_digest = "sha256:" + ("b" * 64)
    normalized = normalize_scientific_outputs(
        node_id="source",
        result_identity="sha256:" + ("c" * 64),
        inputs={},
        outputs=_candidate_outputs(
            CandidatePairingIntent(
                (
                    CandidatePairingIntentEntry(
                        subject_candidate_id="raw-subject",
                        reference_candidate_id="raw-reference",
                    ),
                )
            )
        ),
        candidate_content_digest=lambda candidate: (
            subject_digest
            if candidate.candidate_id == "raw-subject"
            else reference_digest
        ),
    )

    subject = normalized["subjects"].items[0]
    reference = normalized["references"].items[0]
    pairing = normalized["pairing"]
    assert type(pairing) is PairwiseCandidateMapping
    assert pairing.entries == (
        PairwiseCandidateMatch(
            subject=CandidateDataReference(
                candidate_id=subject.candidate_id,
                data_type_id="protein.sequence",
                content_digest=subject_digest,
            ),
            reference=CandidateDataReference(
                candidate_id=reference.candidate_id,
                data_type_id="protein.sequence",
                content_digest=reference_digest,
            ),
        ),
    )


@pytest.mark.parametrize(
    ("subject", "reference", "message"),
    (
        (
            CandidateDataReference(
                "candidate-ghost",
                "protein.sequence",
                "sha256:" + ("1" * 64),
            ),
            CandidateDataReference(
                "candidate-reference",
                "protein.sequence",
                "sha256:" + ("2" * 64),
            ),
            "unknown input Candidate reference",
        ),
        (
            CandidateDataReference(
                "candidate-subject",
                "protein.structure",
                "sha256:" + ("1" * 64),
            ),
            CandidateDataReference(
                "candidate-reference",
                "protein.sequence",
                "sha256:" + ("2" * 64),
            ),
            "conflicts with exact input Candidate reference",
        ),
        (
            CandidateDataReference(
                "candidate-subject",
                "protein.sequence",
                "sha256:" + ("3" * 64),
            ),
            CandidateDataReference(
                "candidate-reference",
                "protein.sequence",
                "sha256:" + ("2" * 64),
            ),
            "conflicts with exact input Candidate reference",
        ),
    ),
)
def test_direct_candidate_pairing_requires_exact_admitted_input_references(
    subject: CandidateDataReference,
    reference: CandidateDataReference,
    message: str,
) -> None:
    inputs = {
        "subjects": CandidateCollection(
            "subjects",
            "protein.sequence",
            [Candidate("candidate-subject", ProteinSequence("AA"))],
        ),
        "references": CandidateCollection(
            "references",
            "protein.sequence",
            [Candidate("candidate-reference", ProteinSequence("AT"))],
        ),
    }

    with pytest.raises(PortValueError, match=message):
        normalize_scientific_outputs(
            node_id="pair",
            result_identity="sha256:" + ("4" * 64),
            inputs=inputs,
            outputs={
                "pairing": PairwiseCandidateMapping(
                    (PairwiseCandidateMatch(subject, reference),)
                )
            },
            candidate_content_digest=lambda candidate: {
                "candidate-subject": "sha256:" + ("1" * 64),
                "candidate-reference": "sha256:" + ("2" * 64),
            }[candidate.candidate_id],
        )


@pytest.mark.parametrize(
    ("entries", "message"),
    (
        (
            (
                CandidatePairingIntentEntry(
                    "unknown-subject",
                    "raw-reference",
                ),
            ),
            "unknown Candidate identity",
        ),
        (
            (
                CandidatePairingIntentEntry(
                    "raw-subject",
                    "raw-reference",
                ),
                CandidatePairingIntentEntry(
                    "raw-subject",
                    "raw-reference",
                ),
            ),
            "duplicate exact pair",
        ),
        (
            (
                CandidatePairingIntentEntry(
                    "raw-subject",
                    "raw-reference",
                ),
                CandidatePairingIntentEntry(
                    "raw-subject",
                    "raw-subject",
                ),
            ),
            "conflicting counterpart",
        ),
    ),
)
def test_pairing_intent_fails_closed_before_port_admission(
    entries: tuple[CandidatePairingIntentEntry, ...],
    message: str,
) -> None:
    with pytest.raises(PortValueError, match=message):
        normalize_scientific_outputs(
            node_id="source",
            result_identity="sha256:" + ("c" * 64),
            inputs={},
            outputs=_candidate_outputs(CandidatePairingIntent(entries)),
            candidate_content_digest=lambda candidate: (
                "sha256:" + ("a" * 64)
            ),
        )


def _lineage_digest(candidate: Candidate) -> str:
    return {
        "raw-parent": "sha256:" + ("1" * 64),
        "raw-child": "sha256:" + ("2" * 64),
    }[candidate.candidate_id]


def test_candidate_lineage_resolution_does_not_depend_on_output_port_sort() -> None:
    outputs = {
        "a_children": CandidateCollection(
            "raw-children",
            "protein.sequence",
            [
                Candidate(
                    "raw-child",
                    ProteinSequence("AT"),
                    parent_ids=("raw-parent",),
                )
            ],
        ),
        "z_parents": CandidateCollection(
            "raw-parents",
            "protein.sequence",
            [Candidate("raw-parent", ProteinSequence("AA"))],
        ),
    }

    normalized = normalize_scientific_outputs(
        node_id="producer",
        result_identity="sha256:" + ("c" * 64),
        inputs={},
        outputs=outputs,
        candidate_content_digest=_lineage_digest,
    )

    parent = normalized["z_parents"].items[0]
    child = normalized["a_children"].items[0]
    expected_parent_id = "candidate-" + canonical_sha256(
        {
            "schema_namespace": "protein-workbench-candidate/v2",
            "producer_result_identity": "sha256:" + ("c" * 64),
            "output_port": "z_parents",
            "sample_slot": "0:0",
            "parent_candidate_identities": [],
            "content_digest": "sha256:" + ("1" * 64),
        }
    ).removeprefix("sha256:")
    expected_child_id = "candidate-" + canonical_sha256(
        {
            "schema_namespace": "protein-workbench-candidate/v2",
            "producer_result_identity": "sha256:" + ("c" * 64),
            "output_port": "a_children",
            "sample_slot": "0:0",
            "parent_candidate_identities": [expected_parent_id],
            "content_digest": "sha256:" + ("2" * 64),
        }
    ).removeprefix("sha256:")

    assert parent.candidate_id == expected_parent_id
    assert child.candidate_id == expected_child_id
    assert child.parent_ids == (parent.candidate_id,)
    assert child.metadata == {
        "producer_result_identity": "sha256:" + ("c" * 64),
        "output_port": "a_children",
        "sample_slot": "0:0",
        "content_digest": "sha256:" + ("2" * 64),
    }

    normalized_from_reverse_insertion = normalize_scientific_outputs(
        node_id="producer",
        result_identity="sha256:" + ("c" * 64),
        inputs={},
        outputs=dict(reversed(tuple(outputs.items()))),
        candidate_content_digest=_lineage_digest,
    )
    assert normalized_from_reverse_insertion == normalized


def test_candidate_lineage_rejects_unknown_parent_without_root_fallback() -> None:
    with pytest.raises(
        PortValueError,
        match="not a resolved input or output Candidate",
    ):
        normalize_scientific_outputs(
            node_id="producer",
            result_identity="sha256:" + ("c" * 64),
            inputs={},
            outputs={
                "children": CandidateCollection(
                    "raw-children",
                    "protein.sequence",
                    [
                        Candidate(
                            "raw-child",
                            ProteinSequence("AT"),
                            parent_ids=("producer",),
                        )
                    ],
                )
            },
            candidate_content_digest=_lineage_digest,
        )


def test_root_candidate_requires_empty_parent_lineage() -> None:
    normalized = normalize_scientific_outputs(
        node_id="producer",
        result_identity="sha256:" + ("c" * 64),
        inputs={},
        outputs={
            "roots": CandidateCollection(
                "raw-roots",
                "protein.sequence",
                [Candidate("raw-parent", ProteinSequence("AA"))],
            )
        },
        candidate_content_digest=_lineage_digest,
    )

    assert normalized["roots"].items[0].parent_ids == ()


def test_candidate_lineage_rejects_duplicate_output_identity() -> None:
    duplicate = Candidate("raw-parent", ProteinSequence("AA"))
    with pytest.raises(
        PortValueError,
        match="reuses one producer identity",
    ):
        normalize_scientific_outputs(
            node_id="producer",
            result_identity="sha256:" + ("c" * 64),
            inputs={},
            outputs={"parents": duplicate, "references": duplicate},
            candidate_content_digest=_lineage_digest,
        )


def test_cross_input_candidate_identity_rejects_conflicting_canonical_facts(
) -> None:
    from core.value_admission import validate_candidate_input_identities

    shared_id = "candidate-shared"
    left = Candidate(
        shared_id,
        ProteinSequence("AA"),
        metadata={"partition": "left"},
    )
    right = Candidate(
        shared_id,
        ProteinSequence("CC"),
        metadata={"partition": "right"},
    )
    digests = {
        "left": InputContentDigests(
            port_type_id="candidate.collection",
            value_content_digests=("sha256:" + "1" * 64,),
            candidate_data=(
                CandidateDataReference(
                    shared_id,
                    "protein.sequence",
                    "sha256:" + "a" * 64,
                ),
            ),
        ),
        "right": InputContentDigests(
            port_type_id="candidate.collection",
            value_content_digests=("sha256:" + "2" * 64,),
            candidate_data=(
                CandidateDataReference(
                    shared_id,
                    "protein.sequence",
                    "sha256:" + "b" * 64,
                ),
            ),
        ),
    }

    with pytest.raises(PortValueError, match="conflicting canonical facts"):
        validate_candidate_input_identities(
            {
                "left": CandidateCollection(
                    "left",
                    "protein.sequence",
                    [left],
                ),
                "right": CandidateCollection(
                    "right",
                    "protein.sequence",
                    [right],
                ),
            },
            digests,
        )


def test_cross_input_candidate_identity_allows_exact_canonical_duplicates(
) -> None:
    from core.value_admission import validate_candidate_input_identities

    first = Candidate(
        "candidate-shared",
        ProteinSequence("AA"),
        parent_ids=("candidate-parent",),
        metadata={"partition": "shared"},
    )
    duplicate = Candidate(
        first.candidate_id,
        ProteinSequence("AA"),
        parent_ids=first.parent_ids,
        metadata=dict(first.metadata),
    )
    candidate_digest = CandidateDataReference(
        first.candidate_id,
        "protein.sequence",
        "sha256:" + "a" * 64,
    )

    validate_candidate_input_identities(
        {
            "left": CandidateCollection(
                "left",
                "protein.sequence",
                [first],
            ),
            "right": CandidateCollection(
                "right",
                "protein.sequence",
                [duplicate],
            ),
        },
        {
            port: InputContentDigests(
                port_type_id="candidate.collection",
                value_content_digests=(value_digest,),
                candidate_data=(candidate_digest,),
            )
            for port, value_digest in (
                ("left", "sha256:" + "1" * 64),
                ("right", "sha256:" + "2" * 64),
            )
        },
    )


def test_cross_input_candidate_identity_distinguishes_json_boolean_and_number(
) -> None:
    from core.value_admission import validate_candidate_input_identities

    candidate_digest = CandidateDataReference(
        "candidate-shared",
        "protein.sequence",
        "sha256:" + "a" * 64,
    )
    candidates = {
        "left": CandidateCollection(
            "left",
            "protein.sequence",
            (
                Candidate(
                    "candidate-shared",
                    ProteinSequence("AA"),
                    metadata={"flag": True},
                ),
            ),
        ),
        "right": CandidateCollection(
            "right",
            "protein.sequence",
            (
                Candidate(
                    "candidate-shared",
                    ProteinSequence("AA"),
                    metadata={"flag": 1},
                ),
            ),
        ),
    }

    with pytest.raises(PortValueError, match="conflicting canonical facts"):
        validate_candidate_input_identities(
            candidates,
            {
                port: InputContentDigests(
                    port_type_id="candidate.collection",
                    value_content_digests=("sha256:" + value * 64,),
                    candidate_data=(candidate_digest,),
                )
                for port, value in (("left", "1"), ("right", "2"))
            },
        )


def test_output_normalization_consumes_prevalidated_input_candidates() -> None:
    shared_id = "candidate-shared"

    normalized = normalize_scientific_outputs(
        node_id="consumer",
        result_identity="sha256:" + ("c" * 64),
        inputs={
            "left": CandidateCollection(
                "left",
                "protein.sequence",
                [Candidate(shared_id, ProteinSequence("AA"))],
            ),
            "right": CandidateCollection(
                "right",
                "protein.sequence",
                [Candidate(shared_id, ProteinSequence("AA"))],
            ),
        },
        outputs={},
        candidate_content_digest=lambda candidate: pytest.fail(
            "input Candidate facts were already admitted before execution"
        ),
    )

    assert normalized == {}


@pytest.mark.parametrize(
    "outputs",
    (
        {
            "children": Candidate(
                "raw-child",
                ProteinSequence("AT"),
                parent_ids=("raw-child",),
            )
        },
        {
            "children": Candidate(
                "raw-child",
                ProteinSequence("AT"),
                parent_ids=("raw-parent",),
            ),
            "parents": Candidate(
                "raw-parent",
                ProteinSequence("AA"),
                parent_ids=("raw-child",),
            ),
        },
    ),
)
def test_candidate_lineage_rejects_cycles(
    outputs: dict[str, Candidate],
) -> None:
    with pytest.raises(PortValueError, match="lineage contains a cycle"):
        normalize_scientific_outputs(
            node_id="producer",
            result_identity="sha256:" + ("c" * 64),
            inputs={},
            outputs=outputs,
            candidate_content_digest=_lineage_digest,
        )
