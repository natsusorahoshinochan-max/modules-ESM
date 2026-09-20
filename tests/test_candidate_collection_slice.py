"""Published Candidate slices restore values without repeating admission."""

from dataclasses import FrozenInstanceError
from typing import Any

import pytest

from core.catalog import _port_value_codec
from core.catalog.builder import build_frozen_catalog
from core.catalog.builtins import (
    CandidateCollectionSlice,
    restore_candidate_collection_slice,
)
from core.catalog.port_contract import PortTypeDefinition
from datatypes.candidate import Candidate, CandidateCollection
from datatypes.i_json import FrozenList
from datatypes.sequence import ProteinSequence
from datatypes.structure import ProteinStructure


@pytest.mark.parametrize(
    ("size", "offset", "limit", "expected_ids"),
    [
        (0, 0, 2, ()),
        (3, 0, 2, ("candidate-0", "candidate-1")),
        (3, 2, 2, ("candidate-2",)),
        (3, 3, 2, ()),
        (3, 8, 2, ()),
        (3, 1, 1, ("candidate-1",)),
    ],
)
def test_collection_slice_bounds(
    size: int, offset: int, limit: int, expected_ids: tuple[str, ...],
) -> None:
    collection = CandidateCollection(
        "collection", "protein.sequence",
        tuple(Candidate(f"candidate-{index}", ProteinSequence("ACD")) for index in range(size)),
    )
    body = build_frozen_catalog(()).require_port_type("candidate.collection").encode(collection)

    result = restore_candidate_collection_slice(body, offset=offset, limit=limit)

    assert isinstance(result, CandidateCollectionSlice)
    assert result.collection_id == "collection"
    assert result.item_type == "protein.sequence"
    assert result.total == size
    assert type(result.items) is tuple
    assert tuple(item.candidate_id for item in result.items) == expected_ids
    assert result.items == tuple(collection.items[offset:offset + limit])


@pytest.mark.parametrize(
    ("item_type", "data"),
    [
        ("protein.sequence", ProteinSequence("ACD")),
        ("protein.structure", ProteinStructure(
            "ATOM      1  CA  ALA A   1       1.000   2.000   3.000"
            "  1.00 20.00           C  \nEND\n"
        )),
    ],
)
def test_slice_preserves_candidate_values_and_immutable_metadata(
    item_type: str, data: ProteinSequence | ProteinStructure,
) -> None:
    candidate = Candidate(
        "child", data, ("parent-a", "parent-b"),
        {"nested": {"labels": ["first", {"rank": 2}]}, "optional": None},
    )
    collection = CandidateCollection("collection", item_type, (candidate,))
    body = build_frozen_catalog(()).require_port_type("candidate.collection").encode(collection)

    result = restore_candidate_collection_slice(body, offset=0, limit=1)

    assert result.item_type == item_type
    assert result.items == (candidate,)
    restored = result.items[0]
    assert tuple(restored.parent_ids) == ("parent-a", "parent-b")
    assert isinstance(restored.metadata["nested"]["labels"], FrozenList)
    with pytest.raises(TypeError):
        restored.metadata["nested"]["labels"][1]["rank"] = 3
    with pytest.raises(FrozenInstanceError):
        setattr(result, "total", 2)
    with pytest.raises(FrozenInstanceError):
        setattr(restored, "candidate_id", "changed")


def test_slice_restores_only_requested_candidates_without_admission_or_digest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    collection = CandidateCollection(
        "collection", "protein.sequence",
        tuple(Candidate(f"candidate-{index}", ProteinSequence("ACD")) for index in range(5)),
    )
    body = build_frozen_catalog(()).require_port_type("candidate.collection").encode(collection)
    original_restore = _port_value_codec._wire_to_value
    restored_ids: list[str] = []

    def observe_restore(value: Any, *, path: str = "$.value") -> Any:
        restored = original_restore(value, path=path)
        if isinstance(restored, Candidate):
            restored_ids.append(restored.candidate_id)
        return restored

    def unexpected_admission(*args: object, **kwargs: object) -> None:
        pytest.fail("Published slice must not repeat admission or content identity work")

    monkeypatch.setattr(_port_value_codec, "_wire_to_value", observe_restore)
    for name in ("validate", "decode", "content_digest"):
        monkeypatch.setattr(PortTypeDefinition, name, unexpected_admission)
    monkeypatch.setattr(_port_value_codec, "_validate_domain_value", unexpected_admission)

    result = restore_candidate_collection_slice(body, offset=1, limit=2)

    assert restored_ids == ["candidate-1", "candidate-2"]
    assert result.items == tuple(collection.items[1:3])
