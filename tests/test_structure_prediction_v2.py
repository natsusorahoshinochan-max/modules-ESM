"""Public contract tests for subjectless structure-prediction confidence."""

from __future__ import annotations

from dataclasses import replace

import pytest

from core import (
    OperationCall,
    ResolvedProducedObservation,
    build_frozen_catalog,
)
from datatypes import (
    Candidate,
    CandidateCollection,
    CandidateDataReference,
    ExactContractReference,
    ExactPortValueReference,
    ProteinSequence,
    ProteinStructure,
    ResidueLayout,
    validate_canonical_identifier,
)
from tests.fixtures.scientific_operation import admitted_port_fixture
from modules.structure_prediction import (
    ConfidenceFact,
    ConfidenceFactCollection,
    PredictionResidueAxis,
    MODULE_PACKAGE,
    prediction_key,
)
from modules.structure_prediction.port_types import (
    CONFIDENCE_FACTS_PORT_TYPE,
    PREDICTION_RESIDUE_AXIS_PORT_TYPE,
    prediction_axis_reference,
)
from modules.prompt_authoring.prompt_types import PROTEIN_PROMPT_PORT_TYPE
from modules.structure_prediction.implementation import (
    MaterializeConfidenceImplementation,
)


_DIGEST = "sha256:" + "1" * 64


def test_prediction_residue_axis_requires_exact_sequence_layout_identity() -> None:
    source = CandidateDataReference(
        candidate_id="sequence-1",
        data_type_id="protein.sequence",
        content_digest=_DIGEST,
    )
    layout = ResidueLayout("A", 2, ("A:1", "A:2"))

    axis = PredictionResidueAxis(
        source=source,
        layout=layout,
        sequence=ProteinSequence("AC", ("A:1", "A:2")),
    )

    assert axis.sequence.residue_ids == axis.layout.residue_ids
    with pytest.raises(ValueError, match="residue identities"):
        PredictionResidueAxis(
            source=source,
            layout=layout,
            sequence=ProteinSequence("AC", ("A:1", "A:3")),
        )


def test_prediction_key_is_canonical_over_the_exact_output_join_fields() -> None:
    arguments = {
        "output_role": "structure_candidates",
        "output_slot": 0,
        "structure_content_digest": "sha256:" + "2" * 64,
        "prediction_axis_content_digest": "sha256:" + "3" * 64,
    }
    key = prediction_key(**arguments)

    assert key == validate_canonical_identifier(key, "prediction_key")
    assert key.startswith("prediction-") and len(key) == 75
    assert len(
        {
            key,
            prediction_key(**(arguments | {"output_role": "structures"})),
            prediction_key(**(arguments | {"output_slot": 1})),
            prediction_key(
                **(
                    arguments
                    | {"structure_content_digest": "sha256:" + "6" * 64}
                )
            ),
            prediction_key(
                **(
                    arguments
                    | {
                        "prediction_axis_content_digest": (
                            "sha256:" + "7" * 64
                        )
                    }
                )
            ),
        }
    ) == 5


def test_confidence_fact_is_exactly_aligned_and_keeps_explicit_nulls() -> None:
    axis = PredictionResidueAxis(
        source=CandidateDataReference(
            "sequence-1",
            "protein.sequence",
            _DIGEST,
        ),
        layout=ResidueLayout("A", 2, ("A:1", "A:2")),
        sequence=ProteinSequence("AC", ("A:1", "A:2")),
    )

    fact = ConfidenceFact(
        prediction_key="prediction-" + "4" * 64,
        structure_content_digest="sha256:" + "5" * 64,
        prediction_axis=axis,
        plddt_per_residue=(91.5, None),
        ptm=None,
        pae=None,
    )

    assert fact.plddt_per_residue == (91.5, None)
    with pytest.raises(ValueError, match="axis length"):
        ConfidenceFact(
            prediction_key="prediction-" + "4" * 64,
            structure_content_digest="sha256:" + "5" * 64,
            prediction_axis=axis,
            plddt_per_residue=(91.5,),
            ptm=None,
            pae=None,
        )


def test_confidence_fact_collection_has_one_method_and_canonical_unique_keys() -> None:
    axis = PredictionResidueAxis(
        source=CandidateDataReference(
            "sequence-1",
            "protein.sequence",
            _DIGEST,
        ),
        layout=ResidueLayout("A", 2, ("A:1", "A:2")),
        sequence=ProteinSequence("AC", ("A:1", "A:2")),
    )
    first = ConfidenceFact(
        prediction_key="prediction-" + "1" * 64,
        structure_content_digest="sha256:" + "5" * 64,
        prediction_axis=axis,
        plddt_per_residue=(90.0, 80.0),
        ptm=0.75,
        pae=None,
    )
    second = replace(first, prediction_key="prediction-" + "2" * 64)
    method = ExactContractReference(
        contract_kind="method",
        contract_id="folding.example.method",
        contract_version="1.0.0",
        contract_digest="sha256:" + "8" * 64,
    )

    collection = ConfidenceFactCollection(
        observation_method=method,
        entries=(second, first),
    )

    assert collection.entries == (first, second)
    with pytest.raises(ValueError, match="duplicate prediction_key"):
        ConfidenceFactCollection(
            observation_method=method,
            entries=(first, first),
        )


def test_prediction_residue_axis_port_has_exact_round_trip_and_content_identity() -> None:
    axis = PredictionResidueAxis(
        source=CandidateDataReference(
            "sequence-1",
            "protein.sequence",
            _DIGEST,
        ),
        layout=ResidueLayout("A", 2, ("A:1", "A:2")),
        sequence=ProteinSequence("AC", ("A:1", "A:2")),
    )

    encoded = PREDICTION_RESIDUE_AXIS_PORT_TYPE.encode(axis)

    assert PREDICTION_RESIDUE_AXIS_PORT_TYPE.type_id == (
        "structure_prediction.prediction_residue_axis"
    )
    assert PREDICTION_RESIDUE_AXIS_PORT_TYPE.version == "1.0.0"
    assert PREDICTION_RESIDUE_AXIS_PORT_TYPE.decode(encoded) == axis
    assert PREDICTION_RESIDUE_AXIS_PORT_TYPE.content_digest(axis).startswith(
        "sha256:"
    )


def test_prediction_residue_axis_allows_exact_prompt_port_source() -> None:
    prompt_source = ExactPortValueReference(
        port_type=ExactContractReference(**PROTEIN_PROMPT_PORT_TYPE.reference()),
        content_digest="sha256:" + "a" * 64,
    )
    axis = PredictionResidueAxis(
        source=prompt_source,
        layout=ResidueLayout("A", 2, ("A:1", "A:2")),
        sequence=ProteinSequence("AC", ("A:1", "A:2")),
    )

    assert PREDICTION_RESIDUE_AXIS_PORT_TYPE.decode(
        PREDICTION_RESIDUE_AXIS_PORT_TYPE.encode(axis)
    ) == axis


def test_confidence_facts_port_round_trips_and_projects_unique_axis_and_method() -> None:
    axis = PredictionResidueAxis(
        source=CandidateDataReference(
            "sequence-1",
            "protein.sequence",
            _DIGEST,
        ),
        layout=ResidueLayout("A", 2, ("A:1", "A:2")),
        sequence=ProteinSequence("AC", ("A:1", "A:2")),
    )
    first = ConfidenceFact(
        prediction_key="prediction-" + "1" * 64,
        structure_content_digest="sha256:" + "5" * 64,
        prediction_axis=axis,
        plddt_per_residue=(90.0, 80.0),
        ptm=0.75,
        pae=((0.0, 1.0), (1.0, 0.0)),
    )
    method = ExactContractReference(
        "method",
        "folding.example.method",
        "1.0.0",
        "sha256:" + "8" * 64,
    )
    facts = ConfidenceFactCollection(
        observation_method=method,
        entries=(
            replace(
                first,
                prediction_key="prediction-" + "2" * 64,
                structure_content_digest="sha256:" + "6" * 64,
            ),
            first,
        ),
    )

    encoded = CONFIDENCE_FACTS_PORT_TYPE.encode(facts)
    axes = CONFIDENCE_FACTS_PORT_TYPE.scientific_axis_references(facts)

    assert CONFIDENCE_FACTS_PORT_TYPE.decode(encoded) == facts
    assert CONFIDENCE_FACTS_PORT_TYPE.observation_method_references(facts) == (
        method,
    )
    assert len(axes) == 1
    assert axes[0].axis_kind == "prediction_input"
    assert axes[0].axis_content_digest == (
        PREDICTION_RESIDUE_AXIS_PORT_TYPE.content_digest(axis)
    )
    assert axes[0].source == axis.source
    assert axes[0].layout == axis.layout


def _produced_observation(
    metric_id: str,
    version: str,
    *,
    has_axis: bool,
    multiplicity: str = "one",
) -> ResolvedProducedObservation:
    return ResolvedProducedObservation(
        output_port="observations",
        output_partition="prediction_confidence",
        metric=ExactContractReference(
            "metric",
            metric_id,
            version,
            "sha256:" + metric_id.encode().hex()[:1].ljust(64, "0"),
        ),
        context_profile={"kind": "intrinsic"},
        subject_grain="candidate",
        source_role="subject",
        subject_direction="input",
        subject_port="structure_candidates",
        guaranteed_multiplicity=multiplicity,
        axis_direction="input" if has_axis else None,
        axis_port="confidence_facts" if has_axis else None,
        method_direction="input",
        method_port="confidence_facts",
    )


def test_materializer_joins_exact_facts_and_preserves_method_axis_and_partition() -> None:
    axis = PredictionResidueAxis(
        source=CandidateDataReference(
            "sequence-1",
            "protein.sequence",
            _DIGEST,
        ),
        layout=ResidueLayout("A", 2, ("A:1", "A:2")),
        sequence=ProteinSequence("AC", ("A:1", "A:2")),
    )
    structure_digest = "sha256:" + "b" * 64
    key = prediction_key(
        output_role="structure_candidates",
        output_slot=0,
        structure_content_digest=structure_digest,
        prediction_axis_content_digest=(
            PREDICTION_RESIDUE_AXIS_PORT_TYPE.content_digest(axis)
        ),
    )
    method = ExactContractReference(
        "method",
        "folding.example.method",
        "1.0.0",
        "sha256:" + "8" * 64,
    )
    facts = ConfidenceFactCollection(
        observation_method=method,
        entries=(
            ConfidenceFact(
                prediction_key=key,
                structure_content_digest=structure_digest,
                prediction_axis=axis,
                plddt_per_residue=(90.0, None),
                ptm=0.75,
                pae=((0.0, 1.0), (1.0, 0.0)),
            ),
        ),
    )
    subject = CandidateDataReference(
        "structure-1",
        "protein.structure",
        structure_digest,
    )
    candidates = CandidateCollection(
        "structures",
        "protein.structure",
        (
            Candidate(
                "structure-1",
                ProteinStructure("ATOM\n"),
                metadata={
                    "prediction_key": key,
                    "output_port": "structure_candidates",
                    "sample_slot": "0:0",
                },
            ),
        ),
    )
    operation = MaterializeConfidenceImplementation(
        produced_observations=(
            _produced_observation(
                "structure.plddt.per_residue",
                "3.0.0",
                has_axis=True,
            ),
            _produced_observation(
                "structure.plddt.mean_residue",
                "3.0.0",
                has_axis=True,
            ),
            _produced_observation(
                "structure.ptm",
                "2.1.0",
                has_axis=False,
                multiplicity="zero_or_more",
            ),
            _produced_observation(
                "structure.pae",
                "3.0.0",
                has_axis=True,
                multiplicity="zero_or_more",
            ),
        )
    )
    call = OperationCall(
        inputs={
            "structure_candidates": admitted_port_fixture(
                candidates,
                port_type_id="candidate.collection",
                value_content_digests=("sha256:" + "c" * 64,),
                candidate_data=(subject,),
            ),
            "confidence_facts": admitted_port_fixture(
                facts,
                port_type_id="structure_prediction.confidence_facts",
                value_content_digests=(
                    CONFIDENCE_FACTS_PORT_TYPE.content_digest(facts),
                ),
            ),
        },
        node_parameters={},
        binding_parameters={},
    )

    observations = operation.execute(call)["observations"]
    by_metric = {entry.metric.contract_id: entry for entry in observations}
    expected_axis = prediction_axis_reference(axis)

    assert set(by_metric) == {
        "structure.plddt.per_residue",
        "structure.plddt.mean_residue",
        "structure.ptm",
        "structure.pae",
    }
    assert all(entry.subject == subject for entry in observations)
    assert all(entry.method == method for entry in observations)
    assert all(
        entry.source_partition == "prediction_confidence"
        for entry in observations
    )
    assert by_metric["structure.plddt.per_residue"].residue_axis == expected_axis
    assert by_metric["structure.plddt.mean_residue"].residue_axis == expected_axis
    assert by_metric["structure.pae"].residue_axis == expected_axis
    assert by_metric["structure.ptm"].residue_axis is None
    assert by_metric["structure.plddt.mean_residue"].value == 90.0


@pytest.mark.parametrize(
    ("key_override", "output_port", "sample_slot", "message"),
    (
        (
            "prediction-" + "0" * 64,
            "structure_candidates",
            "0:0",
            "canonical output slot",
        ),
        (None, "other_structures", "0:0", "canonical output slot"),
        (None, "structure_candidates", "0:1", "canonical output slot"),
        (None, "structure_candidates", "1:0", "canonical 0:index"),
    ),
)
def test_materializer_rejects_metadata_or_key_that_contradicts_exact_slot_facts(
    key_override: str | None,
    output_port: str,
    sample_slot: str,
    message: str,
) -> None:
    axis = PredictionResidueAxis(
        source=CandidateDataReference(
            "sequence-1",
            "protein.sequence",
            _DIGEST,
        ),
        layout=ResidueLayout("A", 1, ("A:1",)),
        sequence=ProteinSequence("A", ("A:1",)),
    )
    structure_digest = "sha256:" + "b" * 64
    derived_key = prediction_key(
        output_role="structure_candidates",
        output_slot=0,
        structure_content_digest=structure_digest,
        prediction_axis_content_digest=(
            PREDICTION_RESIDUE_AXIS_PORT_TYPE.content_digest(axis)
        ),
    )
    supplied_key = derived_key if key_override is None else key_override
    method = ExactContractReference(
        "method",
        "folding.example.method",
        "1.0.0",
        "sha256:" + "8" * 64,
    )
    facts = ConfidenceFactCollection(
        observation_method=method,
        entries=(
            ConfidenceFact(
                prediction_key=supplied_key,
                structure_content_digest=structure_digest,
                prediction_axis=axis,
                plddt_per_residue=(90.0,),
                ptm=None,
                pae=None,
            ),
        ),
    )
    subject = CandidateDataReference(
        "structure-1",
        "protein.structure",
        structure_digest,
    )
    operation = MaterializeConfidenceImplementation(
        produced_observations=(
            _produced_observation(
                "structure.plddt.per_residue",
                "3.0.0",
                has_axis=True,
            ),
            _produced_observation(
                "structure.plddt.mean_residue",
                "3.0.0",
                has_axis=True,
            ),
            _produced_observation(
                "structure.ptm",
                "2.1.0",
                has_axis=False,
                multiplicity="zero_or_more",
            ),
            _produced_observation(
                "structure.pae",
                "3.0.0",
                has_axis=True,
                multiplicity="zero_or_more",
            ),
        )
    )
    call = OperationCall(
        inputs={
            "structure_candidates": admitted_port_fixture(
                CandidateCollection(
                    "structures",
                    "protein.structure",
                    (
                        Candidate(
                            "structure-1",
                            ProteinStructure("ATOM\n"),
                            metadata={
                                "prediction_key": supplied_key,
                                "output_port": output_port,
                                "sample_slot": sample_slot,
                            },
                        ),
                    ),
                ),
                port_type_id="candidate.collection",
                value_content_digests=("sha256:" + "c" * 64,),
                candidate_data=(subject,),
            ),
            "confidence_facts": admitted_port_fixture(
                facts,
                port_type_id="structure_prediction.confidence_facts",
                value_content_digests=(
                    CONFIDENCE_FACTS_PORT_TYPE.content_digest(facts),
                ),
            ),
        },
        node_parameters={},
        binding_parameters={},
    )

    with pytest.raises(ValueError, match=message):
        operation.execute(call)


def test_module_package_registers_the_exact_materializer_and_metric_contracts() -> None:
    catalog = build_frozen_catalog((MODULE_PACKAGE,))
    node = catalog.require_contract(
        "node_type",
        "structure_prediction.materialize_confidence",
        "1.0.0",
    )
    binding = catalog.require_contract(
        "binding",
        "structure_prediction.materialize_confidence.direct",
        "1.0.0",
    )
    method = catalog.require_contract(
        "method",
        "structure_prediction.materialize_confidence.exact_reference_join",
        "1.0.0",
    )

    assert {
        item["name"]: (
            item["port_type"]["contract_id"],
            item["port_type"]["contract_version"],
        )
        for item in node.descriptor["inputs"]
    } == {
        "structure_candidates": ("candidate.collection", "3.0.0"),
        "confidence_facts": (
            "structure_prediction.confidence_facts",
            "1.0.0",
        ),
    }
    assert [item["name"] for item in node.descriptor["outputs"]] == [
        "observations"
    ]
    assert node.descriptor["outputs"][0]["port_type"]["contract_id"] == (
        "score.collection"
    )
    assert binding.descriptor["execution_route"] == "direct"
    assert binding.descriptor["method"] == method.reference()
    produced = {
        item["metric"]["contract_id"]: item
        for item in binding.descriptor["produced_observations"]
    }
    assert set(produced) == {
        "structure.ptm",
        "structure.plddt.per_residue",
        "structure.plddt.mean_residue",
        "structure.pae",
    }
    assert all(
        item["method_direction"] == "input"
        and item["method_port"] == "confidence_facts"
        and item["output_port"] == "observations"
        and item["output_partition"] == "prediction_confidence"
        for item in produced.values()
    )
    assert {
        metric_id
        for metric_id, item in produced.items()
        if item["axis_port"] == "confidence_facts"
    } == {
        "structure.plddt.per_residue",
        "structure.plddt.mean_residue",
        "structure.pae",
    }
    assert produced["structure.ptm"]["axis_port"] is None
    mean_metric = catalog.require_contract(
        "metric",
        "structure.plddt.mean_residue",
        "3.0.0",
    )
    assert mean_metric.descriptor["aggregation_semantics"][
        "included_values"
    ] == "non_null_per_residue_values_on_exact_axis"
