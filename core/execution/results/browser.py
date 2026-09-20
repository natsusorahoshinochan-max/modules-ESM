"""Read-only, paged Candidate projections over published Typed Outputs."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict
from typing import Any, cast

from core.catalog.builtins import (
    CandidateCollectionSlice,
    restore_candidate_collection_slice,
)
from core.execution.ledger import V2RunError
from datatypes.candidate import Candidate, CandidateDataReference
from datatypes.i_json import thaw_i_json
from datatypes.sequence import ProteinSequence
from datatypes.structure import ProteinStructure


class ResultBrowser:
    """Keep data identity at its nominal owner; do not reinterpret structures."""

    def __init__(
        self,
        read_value: Callable[..., tuple[dict[str, Any], bytes, tuple[CandidateDataReference, ...]]],
    ) -> None:
        self._read_value = read_value

    def _collection(
        self, project_id: str, run_id: str, node_id: str,
        output_port: str, value_index: int, *, offset: int, limit: int,
    ) -> tuple[CandidateCollectionSlice, dict[str, CandidateDataReference]]:
        metadata, body, references = self._read_value(
            project_id, run_id, node_id, output_port, value_index,
        )
        type_id = metadata["typed_value"]["port_type"]["contract_id"]
        if type_id != "candidate.collection":
            raise V2RunError(
                "malformed_request", "Output is not a Candidate Collection",
                details={"field_path": ["output_port"]},
            )
        return restore_candidate_collection_slice(body, offset=offset, limit=limit), {
            reference.candidate_id: reference for reference in references
        }

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
        collection, references = self._collection(
            project_id, run_id, node_id, output_port, value_index,
            offset=offset, limit=limit,
        )
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

    def candidate(
        self, project_id: str, run_id: str, node_id: str,
        output_port: str, value_index: int, item_index: int,
    ) -> dict[str, Any]:
        collection, references = self._collection(
            project_id, run_id, node_id, output_port, value_index,
            offset=item_index, limit=1,
        )
        if item_index >= collection.total:
            raise V2RunError(
                "typed_output_not_found", "Candidate index is outside the collection",
                details={"node_id": node_id, "output_port": output_port,
                         "value_index": value_index},
            )
        candidate = collection.items[0]
        return {
            **self._item(candidate, collection.item_type, item_index, references[candidate.candidate_id]),
            "pdb": (
                cast(ProteinStructure, candidate.data).pdb_string
                if collection.item_type == "protein.structure" else None
            ),
        }
