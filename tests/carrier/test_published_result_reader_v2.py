"""The result view retains exact data associations while paging published values."""

from typing import Any

import pytest

from datatypes.i_json import thaw_i_json
from core.catalog.builder import build_frozen_catalog
from core.catalog.port_contract import PortTypeDefinition
from core.execution.ledger import V2RunError
from protein_workbench_public.published_results import PublishedResultReader
from datatypes.candidate import Candidate, CandidateCollection, CandidateDataReference
from datatypes.sequence import ProteinSequence
from datatypes.structure import ProteinStructure


def test_result_pages_keep_order_all_parents_and_exact_data_references(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    catalog = build_frozen_catalog(())
    collection = CandidateCollection(
        "collection", "protein.sequence",
        (
            Candidate("first", ProteinSequence("ACD"), ("parent-a", "parent-b")),
            Candidate("second", ProteinSequence("EFG")),
            Candidate("third", ProteinSequence("HIK")),
        ),
    )
    port = catalog.require_port_type("candidate.collection")
    body = port.encode(collection)
    references = tuple(
        CandidateDataReference(
            item.candidate_id, collection.item_type,
            catalog.require_port_type(collection.item_type).content_digest(item.data),
        )
        for item in reversed(collection.items)
    )

    def unexpected_digest(*args: object, **kwargs: object) -> None:
        pytest.fail("Browsing must reuse published references")

    monkeypatch.setattr(PortTypeDefinition, "content_digest", unexpected_digest)

    def published(*location: object) -> tuple[dict, bytes, tuple[CandidateDataReference, ...]]:
        assert location == ("project", "run", "source", "candidates", 0)
        return {"typed_value": {"port_type": port.reference()}}, body, references

    browser = PublishedResultReader(published)
    first = browser.page("project", "run", "source", "candidates", 0, 0, 2)
    second = browser.page("project", "run", "source", "candidates", 0, 2, 2)
    assert first["total"] == 3
    assert [item["reference"]["candidate_id"] for item in first["items"] + second["items"]] == ["first", "second", "third"]
    assert second["items"][0]["item_index"] == 2
    assert second["items"][0]["sequence"] == "HIK"
    candidate = first["items"][0]
    assert candidate["parent_ids"] == ["parent-a", "parent-b"]
    assert candidate["reference"] == {
        "candidate_id": "first", "data_type_id": "protein.sequence",
        "content_digest": references[-1].content_digest,
    }
    with pytest.raises(V2RunError, match="Candidate has no structure"):
        browser.structure("project", "run", "source", "candidates", 0, 2)


def test_same_candidate_name_with_changed_data_does_not_share_reference() -> None:
    catalog = build_frozen_catalog(())
    port = catalog.require_port_type("candidate.collection")
    collections = {
        name: CandidateCollection("collection", "protein.sequence", (Candidate("same", ProteinSequence(sequence)),))
        for name, sequence in (("old", "ACD"), ("new", "ACE"))
    }
    bodies = {name: port.encode(collection) for name, collection in collections.items()}
    references = {
        name: tuple(
            CandidateDataReference(
                item.candidate_id, collection.item_type,
                catalog.require_port_type(collection.item_type).content_digest(item.data),
            )
            for item in collection.items
        )
        for name, collection in collections.items()
    }

    def published(project: str, run: str, node: str, output: str, index: int) -> tuple[dict, bytes, tuple[CandidateDataReference, ...]]:
        return {"typed_value": {"port_type": port.reference()}}, bodies[run], references[run]

    browser = PublishedResultReader(published)
    old = browser.page("project", "old", "source", "candidates", 0, 0, 1)["items"][0]
    new = browser.page("project", "new", "source", "candidates", 0, 0, 1)["items"][0]
    assert old["reference"]["candidate_id"] == new["reference"]["candidate_id"]
    assert old["reference"]["content_digest"] != new["reference"]["content_digest"]


def test_structure_page_omits_pdb_and_detail_preserves_original_text() -> None:
    catalog = build_frozen_catalog(())
    pdb = (
        "ATOM      1  CA  ALA A   1       1.000   2.000   3.000"
        "  1.00 20.00           C  \nEND\n"
    )
    structure = ProteinStructure(pdb)
    collection = CandidateCollection(
        "structures", "protein.structure",
        (Candidate("structure", structure, ("parent",), {"source": {"rank": 1}}),),
    )
    port = catalog.require_port_type("candidate.collection")
    body = port.encode(collection)
    reference = CandidateDataReference(
        "structure", "protein.structure",
        catalog.require_port_type("protein.structure").content_digest(structure),
    )

    def published(*location: object) -> tuple[dict[str, Any], bytes, tuple[CandidateDataReference, ...]]:
        return {"typed_value": {"port_type": port.reference()}}, body, (reference,)

    browser = PublishedResultReader(published)
    page = browser.page("project", "run", "source", "candidates", 0, 0, 1)
    item = page["items"][0]
    assert page["collection_id"] == "structures"
    assert page["item_type"] == "protein.structure"
    assert "pdb" not in item
    assert item["sequence"] is None
    assert item["has_structure"] is True
    assert item["metadata"] == {"source": {"rank": 1}}
    detail = browser.structure("project", "run", "source", "candidates", 0, 0)
    assert detail == {"text": pdb, "format": "pdb"}


@pytest.mark.parametrize("operation", ("page", "structure"))
def test_non_collection_output_keeps_request_error(operation: str) -> None:
    port = build_frozen_catalog(()).require_port_type("protein.sequence")
    body = port.encode(ProteinSequence("ACD"))

    def published(*location: object) -> tuple[dict[str, Any], bytes, tuple[CandidateDataReference, ...]]:
        return {"typed_value": {"port_type": port.reference()}}, body, ()

    browser = PublishedResultReader(published)
    with pytest.raises(V2RunError, match="Output is not a Candidate Collection") as error:
        if operation == "page":
            browser.page("project", "run", "source", "output", 0, 0, 1)
        else:
            browser.structure("project", "run", "source", "output", 0, 0)
    assert error.value.code == "malformed_request"
    assert thaw_i_json(error.value.details) == {"field_path": ["output_port"]}


@pytest.mark.parametrize(("size", "item_index"), [(0, 0), (1, 1), (1, 8)])
def test_candidate_detail_keeps_out_of_bounds_error(size: int, item_index: int) -> None:
    catalog = build_frozen_catalog(())
    port = catalog.require_port_type("candidate.collection")
    collection = CandidateCollection(
        "collection", "protein.sequence",
        tuple(Candidate(f"candidate-{index}", ProteinSequence("ACD")) for index in range(size)),
    )
    body = port.encode(collection)
    references = tuple(
        CandidateDataReference(
            item.candidate_id, collection.item_type,
            catalog.require_port_type(collection.item_type).content_digest(item.data),
        )
        for item in collection.items
    )

    def published(*location: object) -> tuple[dict[str, Any], bytes, tuple[CandidateDataReference, ...]]:
        return {"typed_value": {"port_type": port.reference()}}, body, references

    with pytest.raises(V2RunError, match="Candidate index is outside the collection") as error:
        PublishedResultReader(published).structure("project", "run", "source", "candidates", 0, item_index)
    assert error.value.code == "typed_output_not_found"
    assert thaw_i_json(error.value.details) == {"node_id": "source", "output_port": "candidates", "value_index": 0}


def _value_reader(type_id: str, body: bytes) -> PublishedResultReader:
    def published(*location: object) -> tuple[dict[str, Any], bytes, tuple[CandidateDataReference, ...]]:
        assert location == ("project", "run", "source", "output", 0)
        return {"typed_value": {"port_type": {"contract_id": type_id}}}, body, ()
    return PublishedResultReader(published)


def _read_value(type_id: str, body: bytes) -> dict[str, Any]:
    from protein_workbench_public.protocol import validate_schema
    result = _value_reader(type_id, body).value("project", "run", "source", "output", 0)
    validate_schema("#/$defs/PublishedResultValue", result)
    return result


def test_score_reading_preserves_full_context_axis_and_adds_only_profile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from dataclasses import asdict
    from datatypes.exact_reference import ExactContractReference, ResidueAxisReference
    from datatypes.observation import (
        PairwiseObservationContext, PairwiseParticipant, ScoreCollection, ScoreObservation,
    )
    from datatypes.residue import ResidueLayout

    subject = CandidateDataReference("subject", "protein.structure", "sha256:" + "1" * 64)
    reference = CandidateDataReference("reference", "protein.structure", "sha256:" + "2" * 64)
    method = ExactContractReference("method", "alignment.method")
    context = PairwiseObservationContext(
        PairwiseParticipant("subject", subject), PairwiseParticipant("reference", reference),
        "explicit_relation", "reference_length", evidence_content_digest="sha256:" + "3" * 64,
        evidence_method=method, subject_axis_content_digest="sha256:" + "4" * 64,
        reference_axis_content_digest="sha256:" + "5" * 64,
        normalization_length=1, aligned_atom_count=1,
    )
    axis = ResidueAxisReference(
        "resolved_structure", ExactContractReference("port_type", "structure_transform.resolved_residue_axis"),
        "sha256:" + "4" * 64, subject, ResidueLayout(("A:1",)),
    )
    score = ScoreObservation(subject, ExactContractReference("metric", "score.metric"), method,
                             context, "measured", {"value": [1.0, None]}, axis)
    body = build_frozen_catalog(()).require_port_type("score.collection").encode(
        ScoreCollection("scores", (score,)),
    )

    def unexpected_admission(*args: object, **kwargs: object) -> None:
        pytest.fail("Published reading must not admit or hash values")
    monkeypatch.setattr(PortTypeDefinition, "decode", unexpected_admission)
    monkeypatch.setattr(PortTypeDefinition, "content_digest", unexpected_admission)
    result = _read_value("score.collection", body)
    entry = result["value"]["entries"][0]
    assert result["value"]["collection_id"] == "scores"
    assert entry["context"] == asdict(context)
    assert entry["subject"] == asdict(subject)
    assert entry["value"] == {"value": [1.0, None]}
    assert entry["residue_axis"]["layout"] == {"residue_ids": ["A:1"]}
    assert entry["residue_axis"]["axis_content_digest"] == axis.axis_content_digest
    assert entry["context_profile"] == {
        "kind": "pairwise", "subject_role": "subject", "reference_role": "reference",
        "pairing_mode": "explicit_relation", "normalization": "reference_length",
    }
    assert entry["source_partition"] == "measured"


@pytest.mark.parametrize("secondary_structure", [None, (None, None)])
def test_prompt_reading_preserves_absent_mask_named_atoms_and_functions(secondary_structure: Any) -> None:
    from modules.prompt_authoring.prompt_types import PROTEIN_PROMPT_PORT_TYPE
    from datatypes.prompt import FunctionAnnotation, ProteinPrompt
    from datatypes.residue import ResidueLayout
    from datatypes.structure import NamedAtomCoordinates
    prompt = ProteinPrompt(
        ResidueLayout(("A:1", "A:2")), ("A", None),
        (NamedAtomCoordinates((("CA", (1.0, 2.0, 3.0)), ("CB", (4.0, 5.0, 6.0)))), None),
        secondary_structure, (None, 0.25),
        (FunctionAnnotation("binding", "A:1", "A:2"),),
    )
    result = _read_value("protein.prompt", PROTEIN_PROMPT_PORT_TYPE.encode(prompt))
    assert result == {"kind": "prompt", "value": {
        "residue_ids": ["A:1", "A:2"], "sequence": ["A", None],
        "coordinates": [{"atoms": [["CA", [1.0, 2.0, 3.0]], ["CB", [4.0, 5.0, 6.0]]]}, None],
        "secondary_structure": None if secondary_structure is None else [None, None],
        "sasa": [None, 0.25],
        "function_annotations": [{"label": "binding", "start_residue_id": "A:1", "end_residue_id": "A:2"}],
    }}


def test_standalone_values_keep_sequence_layout_and_original_pdb() -> None:
    catalog = build_frozen_catalog(())
    sequence = ProteinSequence("AC", ("A:1", "A:2"))
    assert _read_value("protein.sequence", catalog.require_port_type("protein.sequence").encode(sequence)) == {
        "kind": "sequence", "value": {"sequence": "AC", "residue_ids": ["A:1", "A:2"]},
    }
    without_layout = catalog.require_port_type("protein.sequence").encode(ProteinSequence("AC"))
    assert _read_value("protein.sequence", without_layout)["value"]["residue_ids"] is None
    pdb = "ATOM      1  CA  ALA A   1       1.000   2.000   3.000  1.00 20.00           C  \nEND\n"
    body = catalog.require_port_type("protein.structure").encode(ProteinStructure(pdb))
    assert _read_value("protein.structure", body) == {"kind": "structure", "value": {"text": pdb, "format": "pdb"}}


def test_axis_reading_uses_exact_subject_sequence_and_published_layout() -> None:
    from dataclasses import asdict
    from modules.structure_transform.domain import (
        CandidateResolvedResidueAxisAssociation, CandidateResolvedResidueAxisAssociations,
    )
    from modules.structure_transform.port_types import (
        CANDIDATE_RESOLVED_AXIS_ASSOCIATIONS_PORT_TYPE, RESOLVED_AXIS_PORT_TYPE,
    )
    from modules.structure_transform.residue_axis import resolve_residue_axis
    from tests.fixtures.structure_transform_sources.package import _FIXTURES
    subject = CandidateDataReference("candidate", "protein.structure", "sha256:" + "1" * 64)
    axis = resolve_residue_axis(ProteinStructure(_FIXTURES["canonical"]()))
    associations = CandidateResolvedResidueAxisAssociations((
        CandidateResolvedResidueAxisAssociation(subject, axis),
    ))
    result = _read_value(CANDIDATE_RESOLVED_AXIS_ASSOCIATIONS_PORT_TYPE.type_id,
                         CANDIDATE_RESOLVED_AXIS_ASSOCIATIONS_PORT_TYPE.encode(associations))
    assert result == {"kind": "candidate_sequences", "value": {"entries": [
        {"subject": asdict(subject), "sequence": axis.sequence},
    ]}}
    assert _read_value(RESOLVED_AXIS_PORT_TYPE.type_id, RESOLVED_AXIS_PORT_TYPE.encode(axis)) == {
        "kind": "axis_layout", "value": {
            "residue_ids": list(axis.layout.residue_ids),
            "chain_ids": [segment.chain_id for segment in axis.segments],
        },
    }


def test_unknown_extension_reading_is_explicitly_inapplicable() -> None:
    with pytest.raises(V2RunError, match="no specialized reading projection") as error:
        _value_reader("extension.custom", b"unchanged canonical content").value("project", "run", "source", "output", 0)
    assert error.value.code == "malformed_request"


def test_alignment_reading_retains_the_complete_owner_projection() -> None:
    from modules.structure_comparison.alignment import align_resolved_axes
    from modules.structure_comparison.domain import StructureAlignmentEvidence
    from modules.structure_comparison.port_types import (
        ALIGNMENT_EVIDENCE_PORT_TYPE, SEQUENCE_PRIMARY_AFFINE_METHOD_REFERENCE,
        alignment_evidence_to_wire,
    )
    from modules.structure_transform.residue_axis import resolve_residue_axis
    from tests.fixtures.structure_transform_sources.package import _FIXTURES
    axis = resolve_residue_axis(ProteinStructure(_FIXTURES["canonical"]()))
    alignment = align_resolved_axes(axis, axis)
    evidence = StructureAlignmentEvidence(
        subject=CandidateDataReference("subject", "protein.structure", "sha256:" + "1" * 64),
        reference=CandidateDataReference("reference", "protein.structure", "sha256:" + "2" * 64),
        subject_axis_content_digest="sha256:" + "3" * 64,
        reference_axis_content_digest="sha256:" + "4" * 64,
        segment_map=alignment.segment_map, policy=alignment.policy,
        correspondence=alignment.correspondence, transform=alignment.transform,
        normalization=alignment.normalization, rmsd=alignment.rmsd,
        coverage=alignment.coverage, method=SEQUENCE_PRIMARY_AFFINE_METHOD_REFERENCE,
    )
    result = _read_value(ALIGNMENT_EVIDENCE_PORT_TYPE.type_id, ALIGNMENT_EVIDENCE_PORT_TYPE.encode(evidence))
    assert result == {"kind": "alignment", "value": alignment_evidence_to_wire(evidence)}
    assert result["value"]["correspondence"]
    assert result["value"]["segment_map"]
    assert result["value"]["normalization"]["aligned_atom_count"] > 0


def test_public_read_routes_share_published_location_and_keep_errors() -> None:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from protein_workbench_public.http.result_routes import register_result_routes
    from protein_workbench_public.protocol import load_bundle
    from tests.support.protocol import validate_response
    from tests.support.public_request import prepare_rest_request
    catalog = build_frozen_catalog(())
    port = catalog.require_port_type("protein.sequence")
    reader = _value_reader(port.type_id, port.encode(ProteinSequence("AC")))
    app = FastAPI()
    register_result_routes(app, reader, load_bundle()["rest_operations"])
    payload = {"project_id": "project", "run_id": "run", "node_id": "source",
               "output_port": "output", "value_index": 0}
    with TestClient(app) as client:
        request = prepare_rest_request("result_value", payload)
        response = client.request(request.method, request.route, json=request.json_body)
        assert response.status_code == 200
        validate_response("result_value", response.status_code, response.json())
        assert response.json() == {"kind": "sequence", "value": {"sequence": "AC", "residue_ids": None}}
        request = prepare_rest_request("result_structure", {**payload, "item_index": 0})
        response = client.request(request.method, request.route, json=request.json_body)
        assert response.status_code == 400
        validate_response("result_structure", response.status_code, response.json())
        assert response.json()["error"]["code"] == "malformed_request"
        assert response.json()["error"]["details"] == {"field_path": ["output_port"]}
        assert response.json()["error"]["message"] == "Output is not a Candidate Collection"
