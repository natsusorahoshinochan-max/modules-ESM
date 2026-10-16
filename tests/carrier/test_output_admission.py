"""Closed-interface tests for one-pass Operation Output Admission."""

from __future__ import annotations

from collections import Counter
from contextlib import nullcontext
from dataclasses import replace
import hashlib

import pytest

from core.catalog.builtins import builtin_frozen_catalog
from core.catalog.errors import PortValueError
from core.catalog.port_contract import BehaviorReference, PortTypeDefinition
from core.execution.output_admission.admission import (
    NodeOutputPlan,
    OutputPortPlan,
    admit_node_output,
    admit_failed_operation_outputs,
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
)


def _port_type(
    *,
    validate,
    to_wire,
    from_wire,
) -> PortTypeDefinition:
    return PortTypeDefinition(
        type_id="test.output-admission.value",
        validator=BehaviorReference(
            "test.output-admission/validate",
            {},
        ),
        codec=BehaviorReference(
            "test.output-admission/codec",
            {},
        ),
        content_identity=BehaviorReference(
            "test.output-admission/content",
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
    original_validate = PortTypeDefinition.validate
    original_encode = PortTypeDefinition.encode
    original_decode = PortTypeDefinition.decode
    original_content_digest = PortTypeDefinition.content_digest

    def validate(self: PortTypeDefinition, value: object) -> None:
        calls[("validate", self.type_id)] += 1
        original_validate(self, value)

    def encode(self: PortTypeDefinition, value: object) -> bytes:
        calls[("encode", self.type_id)] += 1
        return original_encode(self, value)

    def decode(self: PortTypeDefinition, encoded: bytes) -> object:
        calls[("decode", self.type_id)] += 1
        return original_decode(self, encoded)

    def content_digest(self: PortTypeDefinition, value: object) -> str:
        calls[("content_digest", self.type_id)] += 1
        return original_content_digest(self, value)

    monkeypatch.setattr(PortTypeDefinition, "validate", validate)
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
    raw_outputs = construction.construct((sample,))
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
    assert {kind: count for (action, kind), count in calls.items()
            if action == "validate"} == {
        "protein.structure": 1,
        "structure_prediction.prediction_residue_axis": 1,
        "candidate.collection": 1,
        "structure_prediction.confidence_facts": 1,
    }
    assert not {call: count for call, count in calls.items()
                if call[0] not in {"encode", "validate"}}


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
    )
    raw_structure = ProteinStructure(_FIXTURES["csh"]())
    normalized_structure, normalizations = normalize_csh_parent_span(
        raw_structure
    )
    structure_type = builtin_frozen_catalog().require_port_type(
        "protein.structure",
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
    from core.catalog.errors import PortValueError

    with pytest.raises(PortValueError, match="requires an OutputIdentityIntent"):
        admit_node_output(
            node_plan=_plan(CANDIDATE_NORMALIZATION_FACTS_PORT_TYPE),
            admitted_inputs={},
            raw_outputs={"value": CandidateNormalizationFactCollection((expected.fact,))},
            result_identity="sha256:" + "b" * 64,
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
    assert {kind: count for (action, kind), count in calls.items()
            if action == "validate"} == {
        "protein.structure": 1,
        "structure_transform.modified_residue_normalizations": 1,
        "candidate.collection": 1,
        "structure_transform.candidate_normalization_facts": 1,
    }
    assert not {call: count for call, count in calls.items()
                if call[0] not in {"encode", "validate"}}


def test_codec_and_restore_do_not_repeat_scientific_admission() -> None:
    from core.execution.output_admission.port_values import restore_admitted_port

    calls = []
    port_type = _port_type(
        validate=lambda value: calls.append(value),
        to_wire=lambda value: value,
        from_wire=lambda value: value,
    )
    admitted = admit_node_output(
        node_plan=_plan(port_type), admitted_inputs={},
        raw_outputs={"value": "admitted"}, result_identity="sha256:" + "a" * 64,
    ).ports["value"]
    record = admitted.values[0]
    assert calls == ["admitted"]
    assert port_type.decode(record.canonical_bytes) == "admitted"
    assert port_type.content_digest(record.value) == record.content_digest
    restored = restore_admitted_port(
        port_type=port_type, multiplicity="one",
        values=((record.canonical_bytes, record.content_digest, record.candidate_data),),
        content_digest=admitted.content_digest,
    )
    assert restored == admitted
    assert calls == ["admitted"]


@pytest.mark.parametrize("payload", [b"NaN", b"Infinity", b"9007199254740992", b'"\\ud800"'])
def test_decode_reports_noncanonical_json_as_port_error(payload: bytes) -> None:
    from core.catalog.errors import PortValueError

    with pytest.raises(PortValueError):
        builtin_frozen_catalog().require_port_type("protein.sequence").decode(payload)


def test_axis_publication_and_restore_admit_axis_and_structure_once(monkeypatch) -> None:
    from core.execution.output_admission.port_values import restore_admitted_port
    from modules.structure_transform import _candidate_association_codecs as associations
    from modules.structure_transform.domain import (
        CandidateResolvedResidueAxisAssociation,
        CandidateResolvedResidueAxisAssociations,
    )
    from modules.structure_transform.residue_axis import resolve_residue_axis

    structure = ProteinStructure(_FIXTURES["mse_ligand_water"]())
    axis = resolve_residue_axis(structure)
    subject = CandidateDataReference(
        "source", "protein.structure",
        builtin_frozen_catalog().require_port_type("protein.structure").content_digest(structure),
    )
    value = CandidateResolvedResidueAxisAssociations((
        CandidateResolvedResidueAxisAssociation(subject, axis),
    ))
    axis_calls = []
    original = associations.validate_resolved_axis

    def validate_axis(value):
        axis_calls.append(value)
        return original(value)

    monkeypatch.setattr(associations, "validate_resolved_axis", validate_axis)
    calls = _count_port_codec_calls(monkeypatch)
    port_type = associations.CANDIDATE_RESOLVED_AXIS_ASSOCIATIONS_PORT_TYPE
    admitted = admit_node_output(
        node_plan=_plan(port_type), admitted_inputs={}, raw_outputs={"value": value},
        result_identity="sha256:" + "a" * 64,
    ).ports["value"]
    record = admitted.values[0]
    assert restore_admitted_port(
        port_type=port_type, multiplicity="one",
        values=((record.canonical_bytes, record.content_digest, record.candidate_data),),
        content_digest=admitted.content_digest,
    ) == admitted
    assert axis_calls == [axis]
    assert {kind: count for (action, kind), count in calls.items()
            if action == "validate"} == {port_type.type_id: 1, "protein.structure": 1}


def test_direct_candidate_admission_checks_data_without_changing_identity(monkeypatch) -> None:
    import pytest
    from core.catalog import _port_value_codec
    from core.catalog.errors import PortValueError
    from core.execution.output_admission.port_values import restore_admitted_port
    from tests.support.output_admission import admit_fixture_port

    catalog = builtin_frozen_catalog()
    data_types = {name: catalog.require_port_type(name) for name in (
        "protein.sequence", "protein.structure",
    )}
    candidate = Candidate("original", ProteinSequence("AA"), metadata={"source": "input"})
    port_type = catalog.require_port_type("candidate.collection")
    json_calls = []
    original_validate_json = _port_value_codec.validate_i_json

    def validate_json(value, *, path):
        json_calls.append(value)
        return original_validate_json(value, path=path)

    monkeypatch.setattr(_port_value_codec, "validate_i_json", validate_json)
    record = admit_fixture_port(
        port_type=port_type, multiplicity="one",
        values=(CandidateCollection("original-collection", "protein.sequence", [candidate]),),
        candidate_data_port_types=data_types,
    )
    assert record.value.items[0] == candidate
    assert record.candidate_data[0].candidate_id == "original"
    assert restore_admitted_port(
        port_type=port_type, multiplicity="one",
        values=tuple((item.canonical_bytes, item.content_digest, item.candidate_data)
                     for item in record.values),
        content_digest=record.content_digest,
    ) == record
    assert json_calls == [candidate.metadata]
    with pytest.raises(PortValueError, match="uppercase"):
        admit_fixture_port(
            port_type=port_type, multiplicity="one",
            values=(CandidateCollection("invalid", "protein.sequence", [
                Candidate("invalid", ProteinSequence("aa")),
            ]),), candidate_data_port_types=data_types,
        )


def test_materialized_fresh_output_requires_identity_intent() -> None:
    import pytest
    from core.catalog.errors import PortValueError
    from datatypes.prediction import ConfidenceFact, PredictionResidueAxis
    from datatypes.residue import ResidueLayout

    axis = PredictionResidueAxis(
        CandidateDataReference("sequence", "protein.sequence", "sha256:" + "1" * 64),
        ResidueLayout(("A:1",)), ProteinSequence("A", ("A:1",)),
    )
    facts = ConfidenceFactCollection(_METHOD, (
        ConfidenceFact("prediction-" + "2" * 64, "sha256:" + "3" * 64,
                       axis, (75.0,), 0.7, None),
    ))
    with pytest.raises(PortValueError, match="requires an OutputIdentityIntent"):
        admit_node_output(
            node_plan=_plan(CONFIDENCE_FACTS_PORT_TYPE), admitted_inputs={},
            raw_outputs={"value": facts}, result_identity="sha256:" + "4" * 64,
        )


def test_failed_operation_can_retain_one_completed_required_port() -> None:
    text = builtin_frozen_catalog().require_port_type("text")
    plan = replace(_plan(text), output_ports={
        "sequence": OutputPortPlan(required=True, multiplicity="one", port_type=text),
        "structure": OutputPortPlan(required=True, multiplicity="one", port_type=text),
    })
    arguments = {
        "node_plan": plan, "admitted_inputs": {},
        "raw_outputs": {"sequence": "completed sequence"},
        "result_identity": "sha256:" + "4" * 64,
    }
    retained = admit_failed_operation_outputs(**arguments)
    assert set(retained.ports) == {"sequence"}
    assert retained.ports["sequence"].value == "completed sequence"
    assert retained.evidence_descriptors[0].content_digest == text.content_digest("completed sequence")
    with pytest.raises(PortValueError, match="Required output Port 'structure' is missing"):
        admit_node_output(**arguments)


@pytest.mark.parametrize("outputs", [{"sequence": 42}, {"unknown": "value"}])
def test_failed_operation_outputs_still_require_valid_declared_values(outputs) -> None:
    text = builtin_frozen_catalog().require_port_type("text")
    plan = replace(_plan(text), output_ports={
        "sequence": OutputPortPlan(required=True, multiplicity="one", port_type=text),
        "structure": OutputPortPlan(required=True, multiplicity="one", port_type=text),
    })
    with pytest.raises(PortValueError):
        admit_failed_operation_outputs(
            node_plan=plan, admitted_inputs={}, raw_outputs=outputs,
            result_identity="sha256:" + "4" * 64,
        )
