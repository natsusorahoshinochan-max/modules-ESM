"""Closed-interface tests for one-pass Operation Output Admission."""

from __future__ import annotations

from collections import Counter
from contextlib import nullcontext
import hashlib

from core.catalog.builtins import builtin_frozen_catalog
from core.catalog.port_contract import BehaviorReference, PortTypeDefinition
from core.execution.output_admission.admission import (
    NodeOutputPlan,
    OutputPortPlan,
    admit_node_output,
)
from core.execution.output_admission.artifacts import (
    ArtifactOutputDeclaration,
)
from core.operation import ArtifactPayload, OperationCall
from core.scoring.observation_plan import ProducedObservationPlan
from datatypes.exact_reference import ExactContractReference
from datatypes.candidate import (
    Candidate,
    CandidateCollection,
    CandidateDataReference,
)
from datatypes.prediction import (
    ConfidenceFactCollection,
    PendingConfidenceFact,
    materialize_confidence_fact,
)
from datatypes.sequence import ProteinSequence
from datatypes.structure import ProteinStructure
from modules.folding._output_construction import (
    CompletedFoldingSample,
    CompletedFoldingSampleBatch,
    FoldingOutputConstruction,
)
from modules.structure_prediction.port_types import (
    CONFIDENCE_FACTS_PORT_TYPE,
    PREDICTION_RESIDUE_AXIS_PORT_TYPE,
)
from modules.structure_transform.candidate_transforms import (
    NormalizeCshParentSpanCandidatesImplementation,
)
from modules.structure_transform.csh_normalization import (
    normalize_csh_parent_span,
)
from modules.structure_transform.domain import (
    CandidateNormalizationFactCollection,
    PendingCandidateNormalizationFact,
    materialize_candidate_normalization_fact,
)
from modules.structure_transform.port_types import (
    CANDIDATE_NORMALIZATION_FACTS_PORT_TYPE,
    MODIFIED_RESIDUE_NORMALIZATIONS_PORT_TYPE,
)
from tests.fixtures.scientific_operation import admitted_port_fixture
from tests.fixtures.structure_transform_sources.package import _FIXTURES


_METHOD = ExactContractReference(
    "method",
    "test.output-admission.method",
    "1.0.0",
    "sha256:" + "1" * 64,
)


def _port_type(
    *,
    validate,
    to_wire,
    from_wire,
) -> PortTypeDefinition:
    return PortTypeDefinition(
        type_id="test.output-admission.value",
        version="1.0.0",
        validator=BehaviorReference(
            "test.output-admission/validate",
            "1.0.0",
            {},
        ),
        codec=BehaviorReference(
            "test.output-admission/codec",
            "1.0.0",
            {},
        ),
        content_identity=BehaviorReference(
            "test.output-admission/content",
            "1.0.0",
            {},
        ),
        runtime_validator=validate,
        runtime_to_wire=to_wire,
        runtime_from_wire=from_wire,
    )


def _plan(
    port_type: PortTypeDefinition,
    *,
    artifact_outputs: tuple[ArtifactOutputDeclaration, ...] = (),
) -> NodeOutputPlan:
    return NodeOutputPlan(
        node_id="producer",
        producing_method=_METHOD,
        output_ports={
            "value": OutputPortPlan(
                required=True,
                multiplicity="one",
                port_type=port_type,
            )
        },
        candidate_data_port_types={},
        produced_observations=ProducedObservationPlan(
            binding_method=_METHOD,
        ),
        artifact_outputs=artifact_outputs,
    )


def test_fresh_output_encodes_once_without_decoding_or_revalidation() -> None:
    calls = {"validate": 0, "to_wire": 0, "from_wire": 0}

    def validate(value: object) -> None:
        calls["validate"] += 1
        if type(value) is not str:
            raise ValueError("expected a string")

    def to_wire(value: object) -> object:
        calls["to_wire"] += 1
        return {"text": value}

    def from_wire(value: object) -> object:
        calls["from_wire"] += 1
        return value

    admitted = admit_node_output(
        node_plan=_plan(
            _port_type(
                validate=validate,
                to_wire=to_wire,
                from_wire=from_wire,
            )
        ),
        admitted_inputs={},
        raw_outputs={"value": "exact-runtime-value"},
        result_identity="sha256:" + "2" * 64,
    )

    assert admitted.ports["value"].value == "exact-runtime-value"
    assert calls == {"validate": 1, "to_wire": 1, "from_wire": 0}
    assert admitted.evidence_descriptors[0].content_digest == (
        admitted.ports["value"].content_digest
    )


def test_artifact_intent_consumes_admitted_value_and_typed_declaration() -> None:
    calls = {"validate": 0}

    def validate(value: object) -> None:
        calls["validate"] += 1
        if type(value) is not ArtifactPayload:
            raise ValueError("expected an ArtifactPayload")

    port_type = _port_type(
        validate=validate,
        to_wire=lambda value: {
            "body": value.body.hex(),
            "media_type": value.media_type,
            "filename": value.filename,
            "candidate_id": value.candidate_id,
        },
        from_wire=lambda value: value,
    )
    admitted = admit_node_output(
        node_plan=_plan(
            port_type,
            artifact_outputs=(
                ArtifactOutputDeclaration(
                    output_port="value",
                    artifact_kind="standalone",
                    artifact_media_type="text/plain",
                    accepted_media_types=("text/plain",),
                ),
            ),
        ),
        admitted_inputs={},
        raw_outputs={
            "value": ArtifactPayload(
                body=b"exact bytes",
                media_type="text/plain",
                filename="result.txt",
            )
        },
        result_identity="sha256:" + "3" * 64,
    )

    publication = admitted.artifact_publication_plan.publications[0]
    assert calls == {"validate": 1}
    assert publication.body == b"exact bytes"
    assert publication.media_type == "text/plain"
    assert publication.filename == "result.txt"


def _count_port_codec_calls(monkeypatch) -> Counter[tuple[str, str]]:
    calls: Counter[tuple[str, str]] = Counter()
    original_encode = PortTypeDefinition.encode
    original_decode = PortTypeDefinition.decode
    original_content_digest = PortTypeDefinition.content_digest

    def encode(self: PortTypeDefinition, value: object) -> bytes:
        calls[("encode", self.type_id)] += 1
        return original_encode(self, value)

    def decode(self: PortTypeDefinition, encoded: bytes) -> object:
        calls[("decode", self.type_id)] += 1
        return original_decode(self, encoded)

    def content_digest(self: PortTypeDefinition, value: object) -> str:
        calls[("content_digest", self.type_id)] += 1
        return original_content_digest(self, value)

    monkeypatch.setattr(PortTypeDefinition, "encode", encode)
    monkeypatch.setattr(PortTypeDefinition, "decode", decode)
    monkeypatch.setattr(
        PortTypeDefinition,
        "content_digest",
        content_digest,
    )
    return calls


def _candidate_output_plan(
    *,
    method: ExactContractReference,
    fact_port_type: PortTypeDefinition,
) -> NodeOutputPlan:
    builtins = builtin_frozen_catalog()
    return NodeOutputPlan(
        node_id="producer",
        producing_method=method,
        output_ports={
            "structure_candidates": OutputPortPlan(
                required=True,
                multiplicity="one",
                port_type=builtins.require_port_type(
                    "candidate.collection",
                    "4.0.0",
                ),
            ),
            (
                "confidence_facts"
                if fact_port_type is CONFIDENCE_FACTS_PORT_TYPE
                else "normalization_facts"
            ): OutputPortPlan(
                required=True,
                multiplicity="one",
                port_type=fact_port_type,
            ),
        },
        candidate_data_port_types={
            "protein.structure": builtins.require_port_type(
                "protein.structure",
                "4.0.0",
            )
        },
        produced_observations=ProducedObservationPlan(
            binding_method=method,
        ),
    )


def test_confidence_identity_sources_encode_once_and_preserve_canonical_fact(
    monkeypatch,
) -> None:
    method = ExactContractReference(
        "method",
        "test.output-admission.folding",
        "1.0.0",
        "sha256:" + "4" * 64,
    )
    parent = Candidate("parent", ProteinSequence("A", ("A:1",)))
    parent_reference = CandidateDataReference(
        "parent",
        "protein.sequence",
        "sha256:" + "5" * 64,
    )
    parent_record = admitted_port_fixture(
        CandidateCollection(
            "parents",
            "protein.sequence",
            (parent,),
        ),
        port_type_id="candidate.collection",
        value_content_digests=("sha256:" + "6" * 64,),
        candidate_data=(parent_reference,),
    )
    construction = FoldingOutputConstruction(
        parent_record=parent_record,
        sample_count=1,
        observation_method=method,
    )
    structure = ProteinStructure(
        "ATOM      1  CA  ALA A   1       1.000   2.000   3.000"
        "  1.00 20.00           C  \n"
        "TER\n"
        "END\n"
    )
    sample = CompletedFoldingSample(
        parent_slot=0,
        sample_slot=0,
        structure=structure,
        per_residue_plddt=(75.0,),
        ptm=0.7,
        pae=((0.0,),),
    )
    structure_type = builtin_frozen_catalog().require_port_type(
        "protein.structure",
        "4.0.0",
    )
    structure_bytes = structure_type.encode(structure)
    structure_digest = "sha256:" + hashlib.sha256(structure_bytes).hexdigest()
    axis = construction.parents[0].prediction_axis
    axis_bytes = PREDICTION_RESIDUE_AXIS_PORT_TYPE.encode(axis)
    axis_digest = "sha256:" + hashlib.sha256(axis_bytes).hexdigest()
    expected = materialize_confidence_fact(
        PendingConfidenceFact(
            candidate_id="fold-parent-0-sample-0",
            output_role="structure_candidates",
            output_slot=0,
            structure=structure,
            prediction_axis=axis,
            plddt_per_residue=(75.0,),
            ptm=0.7,
            pae=((0.0,),),
        ),
        structure_content_digest=structure_digest,
        prediction_axis_contract=ExactContractReference(
            **PREDICTION_RESIDUE_AXIS_PORT_TYPE.reference()
        ),
        prediction_axis_content_digest=axis_digest,
    )
    expected_fact_bytes = CONFIDENCE_FACTS_PORT_TYPE.encode(
        ConfidenceFactCollection(method, (expected.fact,))
    )

    calls = _count_port_codec_calls(monkeypatch)
    raw_outputs = construction.construct(
        CompletedFoldingSampleBatch((sample,))
    )
    admitted = admit_node_output(
        node_plan=_candidate_output_plan(
            method=method,
            fact_port_type=CONFIDENCE_FACTS_PORT_TYPE,
        ),
        admitted_inputs={"sequence_candidates": parent_record},
        raw_outputs=raw_outputs,
        result_identity="sha256:" + "7" * 64,
    )

    candidate = admitted.ports["structure_candidates"].value.items[0]
    facts = admitted.ports["confidence_facts"]
    assert candidate.metadata["prediction_key"] == expected.prediction_key
    assert facts.value.entries == (expected.fact,)
    assert facts.values[0].canonical_bytes == expected_fact_bytes
    assert facts.scientific_axes == (expected.scientific_axis,)
    assert admitted.ports["structure_candidates"].candidate_data[0].content_digest == (
        structure_digest
    )
    assert calls[("encode", "protein.structure")] == 1
    assert calls[
        ("encode", "structure_prediction.prediction_residue_axis")
    ] == 1
    assert calls[("encode", "candidate.collection")] == 1
    assert calls[
        ("encode", "structure_prediction.confidence_facts")
    ] == 1
    assert not {
        call: count for call, count in calls.items() if call[0] != "encode"
    }


class _RunResources:
    @staticmethod
    def engine_invocation(**kwargs):
        del kwargs
        return nullcontext()


def test_normalization_identity_sources_encode_once_and_preserve_canonical_fact(
    monkeypatch,
) -> None:
    method = ExactContractReference(
        "method",
        "test.output-admission.normalization",
        "1.0.0",
        "sha256:" + "8" * 64,
    )
    raw_structure = ProteinStructure(_FIXTURES["csh"]())
    normalized_structure, normalizations = normalize_csh_parent_span(
        raw_structure
    )
    structure_type = builtin_frozen_catalog().require_port_type(
        "protein.structure",
        "4.0.0",
    )
    structure_bytes = structure_type.encode(normalized_structure)
    structure_digest = "sha256:" + hashlib.sha256(structure_bytes).hexdigest()
    normalizations_bytes = MODIFIED_RESIDUE_NORMALIZATIONS_PORT_TYPE.encode(
        normalizations
    )
    normalizations_digest = (
        "sha256:" + hashlib.sha256(normalizations_bytes).hexdigest()
    )
    expected = materialize_candidate_normalization_fact(
        PendingCandidateNormalizationFact(
            candidate_id="normalized-csh-0",
            output_role="structure_candidates",
            output_slot=0,
            structure=normalized_structure,
            normalizations=normalizations,
        ),
        structure_content_digest=structure_digest,
        normalizations_content_digest=normalizations_digest,
    )
    expected_fact_bytes = CANDIDATE_NORMALIZATION_FACTS_PORT_TYPE.encode(
        CandidateNormalizationFactCollection((expected.fact,))
    )
    parent_reference = CandidateDataReference(
        "raw-csh",
        "protein.structure",
        "sha256:" + "9" * 64,
    )
    call = OperationCall(
        inputs={
            "structure_candidates": admitted_port_fixture(
                CandidateCollection(
                    "raw-structures",
                    "protein.structure",
                    (Candidate("raw-csh", raw_structure),),
                ),
                port_type_id="candidate.collection",
                value_content_digests=("sha256:" + "a" * 64,),
                candidate_data=(parent_reference,),
            )
        },
        node_parameters={},
        binding_parameters={},
        effective_randomness={},
    )

    calls = _count_port_codec_calls(monkeypatch)
    raw_outputs = NormalizeCshParentSpanCandidatesImplementation(
        _RunResources()
    ).execute(call)
    admitted = admit_node_output(
        node_plan=_candidate_output_plan(
            method=method,
            fact_port_type=CANDIDATE_NORMALIZATION_FACTS_PORT_TYPE,
        ),
        admitted_inputs=call.inputs,
        raw_outputs=raw_outputs,
        result_identity="sha256:" + "b" * 64,
    )

    candidate = admitted.ports["structure_candidates"].value.items[0]
    facts = admitted.ports["normalization_facts"]
    assert candidate.metadata["normalization_key"] == expected.normalization_key
    assert facts.value.entries == (expected.fact,)
    assert facts.values[0].canonical_bytes == expected_fact_bytes
    assert admitted.ports["structure_candidates"].candidate_data[0].content_digest == (
        structure_digest
    )
    assert calls[("encode", "protein.structure")] == 1
    assert calls[
        (
            "encode",
            "structure_transform.modified_residue_normalizations",
        )
    ] == 1
    assert calls[("encode", "candidate.collection")] == 1
    assert calls[
        (
            "encode",
            "structure_transform.candidate_normalization_facts",
        )
    ] == 1
    assert not {
        call: count for call, count in calls.items() if call[0] != "encode"
    }
