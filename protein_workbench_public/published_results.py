"""Public reading composition over published values and their scientific owners."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict
from typing import Any, Literal, TypedDict, cast

from core.catalog.builtins import (
    CandidateCollectionSlice,
    restore_candidate_collection_slice,
)
from core.catalog.published_reading import read_scores, read_sequence, read_structure
from core.execution.ledger import V2RunError
from datatypes.candidate import Candidate, CandidateDataReference
from datatypes.i_json import thaw_i_json
from datatypes.sequence import ProteinSequence
from datatypes.structure import ProteinStructure

from modules.prompt_authoring.published_reading import read_prompt
from modules.structure_comparison.published_reading import read_alignment
from modules.structure_transform.published_reading import (
    read_axis_layout, read_candidate_sequences,
)


class PublishedResultValue(TypedDict):
    kind: Literal[
        "scores", "candidate_sequences", "alignment", "sequence",
        "structure", "prompt", "axis_layout",
    ]
    value: dict[str, Any]


class PublishedResultReader:
    """Keep data identity at its nominal owner; do not reinterpret structures."""

    def __init__(
        self,
        read_value: Callable[..., tuple[dict[str, Any], bytes, tuple[CandidateDataReference, ...]]],
    ) -> None:
        self._read_value = read_value

    def _collection(
        self, project_id: str, run_id: str, node_id: str,
        output_port: str, value_index: int, *, offset: int, limit: int,
    ) -> tuple[CandidateCollectionSlice, tuple[CandidateDataReference, ...]]:
        metadata, body, references = self._read_value(
            project_id, run_id, node_id, output_port, value_index,
        )
        type_id = metadata["typed_value"]["port_type"]["contract_id"]
        if type_id != "candidate.collection":
            raise V2RunError(
                "malformed_request", "Output is not a Candidate Collection",
                details={"field_path": ["output_port"]},
            )
        return restore_candidate_collection_slice(body, offset=offset, limit=limit), references

    def _item(
        self, candidate: Candidate, item_type: str, item_index: int,
        reference: CandidateDataReference,
    ) -> dict[str, Any]:
        return {
            "item_index": item_index,
            "reference": asdict(reference),
            "parent_ids": list(candidate.parent_ids),
            "metadata": thaw_i_json(candidate.metadata),
            "sequence": (
                cast(ProteinSequence, candidate.data).sequence
                if item_type == "protein.sequence" else None
            ),
            "has_structure": item_type == "protein.structure",
        }

    def page(
        self, project_id: str, run_id: str, node_id: str,
        output_port: str, value_index: int, offset: int, limit: int,
    ) -> dict[str, Any]:
        collection, published_references = self._collection(
            project_id, run_id, node_id, output_port, value_index,
            offset=offset, limit=limit,
        )
        references = {reference.candidate_id: reference for reference in published_references}
        return {
            "collection_id": collection.collection_id,
            "item_type": collection.item_type,
            "total": collection.total,
            "offset": offset,
            "items": [
                self._item(candidate, collection.item_type, index, references[candidate.candidate_id])
                for index, candidate in enumerate(collection.items, start=offset)
            ],
        }

    def structure(
        self, project_id: str, run_id: str, node_id: str,
        output_port: str, value_index: int, item_index: int,
    ) -> dict[str, str]:
        collection, _references = self._collection(
            project_id, run_id, node_id, output_port, value_index,
            offset=item_index, limit=1,
        )
        if item_index >= collection.total:
            raise V2RunError(
                "typed_output_not_found", "Candidate index is outside the collection",
                details={"node_id": node_id, "output_port": output_port,
                         "value_index": value_index},
            )
        if collection.item_type != "protein.structure":
            raise V2RunError(
                "malformed_request", "Candidate has no structure",
                details={"field_path": ["output_port"]},
            )
        return {"pdb": cast(ProteinStructure, collection.items[0].data).pdb_string}

    def value(
        self, project_id: str, run_id: str, node_id: str,
        output_port: str, value_index: int,
    ) -> PublishedResultValue:
        metadata, body, _references = self._read_value(
            project_id, run_id, node_id, output_port, value_index,
        )
        type_id = metadata["typed_value"]["port_type"]["contract_id"]
        if type_id == "score.collection":
            return {"kind": "scores", "value": read_scores(body)}
        if type_id == "structure_transform.candidate_resolved_residue_axis_associations":
            return {"kind": "candidate_sequences", "value": read_candidate_sequences(body)}
        if type_id == "structure_comparison.alignment_evidence":
            return {"kind": "alignment", "value": read_alignment(body)}
        if type_id == "protein.sequence":
            return {"kind": "sequence", "value": read_sequence(body)}
        if type_id == "protein.structure":
            return {"kind": "structure", "value": read_structure(body)}
        if type_id == "protein.prompt":
            return {"kind": "prompt", "value": read_prompt(body)}
        if type_id == "structure_transform.resolved_residue_axis":
            return {"kind": "axis_layout", "value": read_axis_layout(body)}
        raise V2RunError(
            "malformed_request", "Output has no specialized reading projection",
            details={"field_path": ["output_port"]},
        )
