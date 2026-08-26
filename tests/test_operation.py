from dataclasses import replace
from types import SimpleNamespace

import pytest

from core.operation import (
    AdmittedPort,
    CandidatePairingIntent,
    CandidatePairingIntentEntry,
    OperationCall,
)
from core.catalog.errors import (
    CatalogBuildError,
    PortValueError,
)
from core.catalog.canonical import canonical_sha256
from core.catalog.port_contract import (
    BehaviorReference,
    PortTypeDefinition,
)
from core.scoring.observation_admission import (
    ObservationAdmissionError,
    admit_produced_observations,
)
from core.scoring.observation_plan import (
    IntrinsicContextProfile,
    ObservationPropagationFilter,
    ObservationPropagationPlan,
    ProducedObservationPlan,
    ResolvedMetricFacts,
    ResolvedProducedObservation,
)
from tests.support.output_admission import (
    admit_fixture_port,
    normalize_fixture_outputs,
)
from datatypes.candidate import (
    Candidate,
    CandidateCollection,
    CandidateDataReference,
)
from datatypes.exact_reference import (
    ExactContractReference,
    ResidueAxisReference,
)
from datatypes.observation import (
    IntrinsicObservationContext,
    PairwiseCandidateMapping,
    PairwiseCandidateMatch,
    PairwiseObservationContext,
    PairwiseParticipant,
    ScoreCollection,
    ScoreObservation,
)
from datatypes.residue import ResidueLayout
from datatypes.sequence import ProteinSequence
from datatypes.structure import ProteinStructure
from tests.fixtures.scientific_operation import (
    admitted_port_fixture,
    operation_context,
)


def _method_reference(
    contract_id: str,
    digest_character: str,
) -> ExactContractReference:
    return ExactContractReference(
        "method",
        contract_id)


def _intrinsic_score(
    subject: CandidateDataReference,
    *,
    value: float = 0.5,
) -> ScoreObservation:
    return ScoreObservation(
        subject=subject,
        metric=ExactContractReference(
            "metric",
            "fixture.quality"),
        method=_method_reference("fixture.measure", "c"),
        context=IntrinsicObservationContext(),
        source_partition="default",
        value=value,
    )


def test_operation_call_carries_one_complete_admitted_port_record() -> None:
    method = _method_reference("fixture.provider", "1")
    candidate_reference = CandidateDataReference(
        candidate_id="candidate-1",
        data_type_id="protein.sequence",
        content_digest="sha256:" + ("2" * 64),
    )
    port_type = PortTypeDefinition(
        type_id="fixture.facts",
        validator=BehaviorReference("fixture.facts/validate", {}),
        codec=BehaviorReference("fixture.facts/codec", {}),
        content_identity=BehaviorReference(
            "fixture.facts/content", {}
        ),
        runtime_validator=lambda value: None,
        runtime_to_wire=lambda value: value,
        runtime_from_wire=lambda value: value,
        candidate_data_projection=BehaviorReference(
            "fixture.facts/candidate_projection", {}
        ),
        runtime_candidate_data_projection=lambda _value, _port_types: (
            candidate_reference,
        ),
        observation_method_projection=BehaviorReference(
            "fixture.facts/method_projection", {}
        ),
        runtime_observation_method_projection=lambda _: (method,),
    )
    runtime_value = {"facts": [1, 2]}
    admitted = admit_fixture_port(
        port_type=port_type,
        multiplicity="one",
        values=(runtime_value,),
        candidate_data_port_types={},
    )
    call = OperationCall(
        inputs={"facts": admitted},
        node_parameters={},
        binding_parameters={},
        effective_randomness={"effective_seed": {"value": 17}},
    )

    assert isinstance(call.inputs["facts"], AdmittedPort)
    assert call.inputs["facts"] is admitted
    assert admitted.value is runtime_value
    assert admitted.values[0].canonical_bytes == (
        b'{"port_type_id":"fixture.facts",'
        b'"schema_namespace":"protein-workbench-port-value/v2",'
        b'"value":{"facts":[1,2]}}'
    )
    assert admitted.value_content_digests == (admitted.content_digest,)
    assert admitted.candidate_data == (candidate_reference,)
    assert admitted.observation_methods == (method,)
    assert call.effective_randomness == {
        "effective_seed": {"value": 17}
    }


def test_candidate_data_projection_declaration_and_runtime_are_atomic() -> None:
    behavior = BehaviorReference(
        "fixture.candidates/project", {}
    )
    definition_arguments = {
        "type_id": "fixture.candidates",
        "validator": BehaviorReference(
            "fixture.candidates/validate", {}
        ),
        "codec": BehaviorReference(
            "fixture.candidates/codec", {}
        ),
        "content_identity": BehaviorReference(
            "fixture.candidates/content", {}
        ),
    }
    with pytest.raises(CatalogBuildError, match="provided together"):
        PortTypeDefinition(
            **definition_arguments,
            candidate_data_projection=behavior,
        )
    with pytest.raises(CatalogBuildError, match="provided together"):
        PortTypeDefinition(
            **definition_arguments,
            runtime_candidate_data_projection=lambda _value, _types: (),
        )


def test_direct_operation_context_preserves_axis_and_method_sources() -> None:
    method = _method_reference("fixture.materializer", "a")
    metric = ExactContractReference(
        "metric",
        "fixture.metric")
    binding = SimpleNamespace(
        descriptor={
            "method": {
                "contract_kind": method.contract_kind,
                "contract_id": method.contract_id},
            "produced_observations": (
                {
                    "output_port": "scores",
                    "output_partition": "default",
                    "metric": {
                        "contract_kind": metric.contract_kind,
                        "contract_id": metric.contract_id},
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
        {"projection": "exact-provider-method"},
    )
    common = {
        "type_id": "fixture.confidence",
        "validator": BehaviorReference(
            "fixture.confidence/validate", {}
        ),
        "codec": BehaviorReference(
            "fixture.confidence/codec", {}
        ),
        "content_identity": BehaviorReference(
            "fixture.confidence/content", {}
        ),
    }

    with pytest.raises(CatalogBuildError, match="provided together"):
        PortTypeDefinition(
            **common,
            observation_method_projection=behavior,
        )

    method = ExactContractReference(
        "method",
        "provider.inference")
    definition = PortTypeDefinition(
        **common,
        observation_method_projection=behavior,
        runtime_observation_method_projection=lambda _: (method,),
    )
    assert definition.observation_method_references("facts") == (method,)
    assert "observation_method_projection" in definition.descriptor()


def test_produced_observation_method_uses_declared_projection_or_binding_default(
) -> None:
    digest = "sha256:" + ("a" * 64)
    subject = CandidateDataReference(
        "candidate-1", "protein.sequence", digest
    )
    metric = ExactContractReference(
        "metric", "quality")
    binding_method = ExactContractReference(
        "method", "materialize")
    provider_method = ExactContractReference(
        "method", "provider")
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
    def validate(
        method: ExactContractReference,
        *,
        dynamic: bool,
        projected: tuple[ExactContractReference, ...],
    ) -> None:
        declaration = ResolvedProducedObservation(
            output_port="scores",
            output_partition="default",
            metric=metric,
            context_profile=IntrinsicContextProfile(),
            subject_grain="candidate",
            source_role="subject",
            subject_direction="input",
            subject_port="candidates",
            guaranteed_multiplicity="one",
            method_direction="input" if dynamic else None,
            method_port="confidence" if dynamic else None,
        )
        collection = ScoreCollection(
            "scores",
            [
                ScoreObservation(
                    subject=subject,
                    metric=metric,
                    method=method,
                    context=IntrinsicObservationContext(),
                    source_partition="default",
                    value=0.5,
                )
            ],
        )
        admit_produced_observations(
            plan=ProducedObservationPlan(
                binding_method=binding_method,
                observations=(declaration,),
                metric_facts={metric: facts},
            ),
            output_port="scores",
            collection=collection,
            inputs={
                "candidates": admitted_port_fixture(
                    candidates,
                    port_type_id="candidate.collection",
                    value_content_digests=("sha256:" + ("8" * 64),),
                    candidate_data=(subject,),
                ),
                "confidence": admitted_port_fixture(
                    "facts",
                    port_type_id="fixture.confidence",
                    value_content_digests=("sha256:" + ("9" * 64),),
                    observation_methods=projected,
                ),
            },
            outputs={
                "scores": admitted_port_fixture(
                    collection,
                    port_type_id="score.collection",
                    value_content_digests=("sha256:" + ("a" * 64),),
                    candidate_data=(subject,),
                )
            },
        )

    validate(provider_method, dynamic=True, projected=(provider_method,))
    validate(binding_method, dynamic=False, projected=())

    with pytest.raises(ObservationAdmissionError, match="undeclared Method"):
        validate(provider_method, dynamic=True, projected=())
    with pytest.raises(ObservationAdmissionError, match="undeclared Method"):
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
        "quality")
    method = ExactContractReference(
        "method",
        "fixture")
    with pytest.raises(PortValueError, match="same-operation output"):
        normalize_fixture_outputs(
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
                            source_partition="default",
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
            "fixture.prediction_axis"),
        axis_content_digest="sha256:" + ("4" * 64),
        source=axis_source,
        layout=ResidueLayout("A", 1, ("A:1",)),
    )
    score = replace(_intrinsic_score(subject), residue_axis=axis)

    normalized = normalize_fixture_outputs(
        node_id="materializer",
        result_identity="sha256:" + ("5" * 64),
        inputs={
            "structures": admitted_port_fixture(
                CandidateCollection(
                    "structures",
                    "protein.structure",
                    [Candidate("structure", ProteinStructure("ATOM\n"))],
                ),
                port_type_id="candidate.collection",
                value_content_digests=("sha256:" + ("6" * 64),),
                candidate_data=(subject,),
            ),
            "confidence_facts": admitted_port_fixture(
                "admitted-axis-owner",
                port_type_id="fixture.confidence",
                value_content_digests=("sha256:" + ("7" * 64),),
                scientific_axes=(axis,),
            ),
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

    normalized = normalize_fixture_outputs(
        node_id="merge",
        result_identity="sha256:" + ("3" * 64),
        inputs={
            "source": admitted_port_fixture(
                ScoreCollection("source", [observation]),
                port_type_id="score.collection",
                value_content_digests=("sha256:" + ("4" * 64),),
                candidate_data=(subject, reference),
            )
        },
        outputs={"scores": ScoreCollection("raw-output", [observation])},
        candidate_content_digest=lambda _: pytest.fail(
            "propagated admitted Score references must not be recomputed"
        ),
        observation_propagation=ObservationPropagationPlan(
            mode="pass_through",
            output_port="scores",
            input_ports=("source",),
        ),
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
        normalize_fixture_outputs(
            node_id="merge",
            result_identity="sha256:" + ("3" * 64),
            inputs={
                "left": admitted_port_fixture(
                    ScoreCollection("left", [_intrinsic_score(left_subject)]),
                    port_type_id="score.collection",
                    value_content_digests=("sha256:" + ("4" * 64),),
                    candidate_data=(left_subject,),
                ),
                "right": admitted_port_fixture(
                    ScoreCollection("right", [_intrinsic_score(right_subject)]),
                    port_type_id="score.collection",
                    value_content_digests=("sha256:" + ("5" * 64),),
                    candidate_data=(right_subject,),
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
            observation_propagation=ObservationPropagationPlan(
                mode="union",
                output_port="scores",
                input_ports=("left", "right"),
            ),
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
        normalize_fixture_outputs(
            node_id="filter",
            result_identity="sha256:" + ("3" * 64),
            inputs={
                "source": admitted_port_fixture(
                    ScoreCollection("source", [_intrinsic_score(admitted)]),
                    port_type_id="score.collection",
                    value_content_digests=("sha256:" + ("4" * 64),),
                    candidate_data=(admitted,),
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
            observation_propagation=ObservationPropagationPlan(
                mode="filter",
                output_port="scores",
                input_ports=("source",),
                filter=ObservationPropagationFilter(
                    source_partition="default"
                ),
            ),
        )


def test_pairing_intent_projects_normalized_exact_candidate_content() -> None:
    subject_digest = "sha256:" + ("a" * 64)
    reference_digest = "sha256:" + ("b" * 64)
    normalized = normalize_fixture_outputs(
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
        "subjects": admitted_port_fixture(
            CandidateCollection(
                "subjects",
                "protein.sequence",
                [Candidate("candidate-subject", ProteinSequence("AA"))],
            ),
            port_type_id="candidate.collection",
            value_content_digests=("sha256:" + ("5" * 64),),
            candidate_data=(
                CandidateDataReference(
                    "candidate-subject",
                    "protein.sequence",
                    "sha256:" + ("1" * 64),
                ),
            ),
        ),
        "references": admitted_port_fixture(
            CandidateCollection(
                "references",
                "protein.sequence",
                [Candidate("candidate-reference", ProteinSequence("AT"))],
            ),
            port_type_id="candidate.collection",
            value_content_digests=("sha256:" + ("6" * 64),),
            candidate_data=(
                CandidateDataReference(
                    "candidate-reference",
                    "protein.sequence",
                    "sha256:" + ("2" * 64),
                ),
            ),
        ),
    }

    with pytest.raises(PortValueError, match=message):
        normalize_fixture_outputs(
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
                    "raw-subject",
                ),
            ),
            "conflicting counterpart",
        ),
    ),
)
def test_pairing_intent_requires_known_distinct_candidates(
    entries: tuple[CandidatePairingIntentEntry, ...],
    message: str,
) -> None:
    with pytest.raises(PortValueError, match=message):
        normalize_fixture_outputs(
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
                    metadata={
                        "runtime_path": "/trusted/producer/value",
                        "experiment_label": "sample-a",
                    },
                )
            ],
        ),
        "z_parents": CandidateCollection(
            "raw-parents",
            "protein.sequence",
            [Candidate("raw-parent", ProteinSequence("AA"))],
        ),
    }

    normalized = normalize_fixture_outputs(
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
        "runtime_path": "/trusted/producer/value",
        "experiment_label": "sample-a",
        "producer_result_identity": "sha256:" + ("c" * 64),
        "output_port": "a_children",
        "sample_slot": "0:0",
        "content_digest": "sha256:" + ("2" * 64),
    }

    normalized_from_reverse_insertion = normalize_fixture_outputs(
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
        normalize_fixture_outputs(
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
    normalized = normalize_fixture_outputs(
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
        normalize_fixture_outputs(
            node_id="producer",
            result_identity="sha256:" + ("c" * 64),
            inputs={},
            outputs={"parents": duplicate, "references": duplicate},
            candidate_content_digest=_lineage_digest,
        )


def test_output_normalization_consumes_prevalidated_input_candidates() -> None:
    shared_id = "candidate-shared"

    normalized = normalize_fixture_outputs(
        node_id="consumer",
        result_identity="sha256:" + ("c" * 64),
        inputs={
            port: admitted_port_fixture(
                CandidateCollection(
                    port,
                    "protein.sequence",
                    [Candidate(shared_id, ProteinSequence("AA"))],
                ),
                port_type_id="candidate.collection",
                value_content_digests=("sha256:" + (digest * 64),),
                candidate_data=(
                    CandidateDataReference(
                        shared_id,
                        "protein.sequence",
                        "sha256:" + ("a" * 64),
                    ),
                ),
            )
            for port, digest in (("left", "1"), ("right", "2"))
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
        normalize_fixture_outputs(
            node_id="producer",
            result_identity="sha256:" + ("c" * 64),
            inputs={},
            outputs=outputs,
            candidate_content_digest=_lineage_digest,
        )
