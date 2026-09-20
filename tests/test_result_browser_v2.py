"""The result view retains exact data associations while paging published values."""

from typing import Any

import pytest

from core.catalog.builder import build_frozen_catalog
from core.catalog.port_contract import PortTypeDefinition
from core.execution.ledger import V2RunError
from core.execution.results.browser import ResultBrowser
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

    browser = ResultBrowser(published)
    first = browser.page("project", "run", "source", "candidates", 0, 0, 2)
    second = browser.page("project", "run", "source", "candidates", 0, 2, 2)
    assert first["total"] == 3
    assert [item["reference"]["candidate_id"] for item in first["items"] + second["items"]] == ["first", "second", "third"]
    assert second["items"][0]["item_index"] == 2
    candidate = first["items"][0]
    assert candidate["parent_ids"] == ["parent-a", "parent-b"]
    assert candidate["reference"] == {
        "candidate_id": "first", "data_type_id": "protein.sequence",
        "content_digest": references[-1].content_digest,
    }
    detail = browser.candidate("project", "run", "source", "candidates", 0, 2)
    assert detail["sequence"] == "HIK"
    assert detail["pdb"] is None
    assert detail["has_structure"] is False


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

    browser = ResultBrowser(published)
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

    browser = ResultBrowser(published)
    page = browser.page("project", "run", "source", "candidates", 0, 0, 1)
    item = page["items"][0]
    assert page["collection_id"] == "structures"
    assert page["item_type"] == "protein.structure"
    assert "pdb" not in item
    assert item["sequence"] is None
    assert item["has_structure"] is True
    assert item["metadata"] == {"source": {"rank": 1}}
    detail = browser.candidate("project", "run", "source", "candidates", 0, 0)
    assert detail == {**item, "pdb": pdb}


@pytest.mark.parametrize("operation", ("page", "candidate"))
def test_non_collection_output_keeps_request_error(operation: str) -> None:
    port = build_frozen_catalog(()).require_port_type("protein.sequence")
    body = port.encode(ProteinSequence("ACD"))

    def published(*location: object) -> tuple[dict[str, Any], bytes, tuple[CandidateDataReference, ...]]:
        return {"typed_value": {"port_type": port.reference()}}, body, ()

    browser = ResultBrowser(published)
    with pytest.raises(V2RunError, match="Output is not a Candidate Collection") as error:
        if operation == "page":
            browser.page("project", "run", "source", "output", 0, 0, 1)
        else:
            browser.candidate("project", "run", "source", "output", 0, 0)
    assert error.value.code == "malformed_request"
    assert error.value.details == {"field_path": ["output_port"]}


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
        ResultBrowser(published).candidate("project", "run", "source", "candidates", 0, item_index)
    assert error.value.code == "typed_output_not_found"
    assert error.value.details == {"node_id": "source", "output_port": "candidates", "value_index": 0}
