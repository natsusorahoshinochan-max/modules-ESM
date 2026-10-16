"""Read immutable candidate pages using their published references."""
from collections.abc import Mapping
from dataclasses import asdict
from typing import Any, cast

from core.catalog.builtins import restore_candidate_collection_slice
from core.catalog.result_actions import ResultActionDefinition, ResultActionError
from core.parameters.contract import admit_declarations
from datatypes.candidate import CandidateDataReference
from datatypes.i_json import thaw_i_json
from datatypes.sequence import ProteinSequence
from datatypes.structure import ProteinStructure


def read_candidate_page(
    body: bytes, parameters: Mapping[str, Any],
    references: tuple[CandidateDataReference, ...],
) -> dict[str, Any]:
    offset = parameters["offset"]
    collection = restore_candidate_collection_slice(body, offset=offset, limit=parameters["limit"])
    published = {reference.candidate_id: reference for reference in references}
    return {
        "collection_id": collection.collection_id,
        "item_type": collection.item_type,
        "total": collection.total,
        "offset": offset,
        "items": [{
            "item_index": index,
            "reference": asdict(published[candidate.candidate_id]),
            "parent_ids": list(candidate.parent_ids),
            "metadata": thaw_i_json(candidate.metadata),
            "sequence": cast(ProteinSequence, candidate.data).sequence if collection.item_type == "protein.sequence" else None,
            "has_structure": collection.item_type == "protein.structure",
        } for index, candidate in enumerate(collection.items, start=offset)],
    }


CANDIDATE_PAGE_ACTION = ResultActionDefinition(
    action_id="protein_io.candidate_page", port_type_id="candidate.collection",
    parameters=admit_declarations({
        "offset": {"parameter_scope": "scientific", "scientific_meaning": "First item in the published collection.", "required": True, "value_contract": {"type": "integer", "minimum": 0}},
        "limit": {"parameter_scope": "scientific", "scientific_meaning": "Maximum number of items to read.", "required": True, "value_contract": {"type": "integer", "minimum": 1, "maximum": 1000}},
    }, path="protein_io.candidate_page"),
    apply=read_candidate_page,
)


def read_candidate_structure(
    body: bytes, parameters: Mapping[str, Any],
    references: tuple[CandidateDataReference, ...],
) -> dict[str, str]:
    index = parameters["item_index"]
    collection = restore_candidate_collection_slice(body, offset=index, limit=1)
    if index >= collection.total:
        raise ResultActionError("Candidate index is outside the collection")
    if collection.item_type != "protein.structure":
        raise ResultActionError("Selected Candidate has no structure")
    structure = cast(ProteinStructure, collection.items[0].data)
    return {"text": structure.text, "format": structure.format}


CANDIDATE_STRUCTURE_ACTION = ResultActionDefinition(
    action_id="protein_io.candidate_structure", port_type_id="candidate.collection",
    parameters=admit_declarations({
        "item_index": {"parameter_scope": "scientific", "scientific_meaning": "Selected published Candidate index.", "required": True, "value_contract": {"type": "integer", "minimum": 0}},
    }, path="protein_io.candidate_structure"),
    apply=read_candidate_structure,
)
