"""Pairwise Structure Alignment: index-matched SVD alignment of two CandidateCollections."""

import uuid
from pathlib import Path
from typing import Any

from core.module_definition import ModuleDefinition
from core.run_context import RunContext
from core.workflow_module import WorkflowModule
from datatypes import Candidate, CandidateCollection, ProteinStructure
from modules.structure_alignment import align_structures


class PairwiseAlignModule(WorkflowModule):
    def __init__(self) -> None:
        d = Path(__file__).parent / "definition.yaml"
        self._definition = ModuleDefinition.from_yaml(d)

    @property
    def definition(self) -> ModuleDefinition:
        return self._definition

    def run(
        self,
        inputs: dict[str, Any],
        parameters: dict[str, Any],
        context: RunContext,
    ) -> dict[str, Any]:
        reference: ProteinStructure | None = inputs.get("reference")
        ref_coll: CandidateCollection | None = inputs.get("reference_candidates")
        mob_coll: CandidateCollection | None = inputs.get("mobile_candidates")

        if (reference is None) == (ref_coll is None):
            raise ValueError(
                "exactly one of reference or reference_candidates is required"
            )
        if mob_coll is None:
            raise ValueError("mobile_candidates input is required")

        if ref_coll is not None and len(ref_coll) == 0:
            raise ValueError("reference_candidates collection is empty")
        if len(mob_coll) == 0:
            raise ValueError("mobile_candidates collection is empty")

        if ref_coll is not None and len(ref_coll) != len(mob_coll):
            raise ValueError(
                f"Collections must have equal length: "
                f"reference has {len(ref_coll)}, mobile has {len(mob_coll)}"
            )

        if (
            ref_coll is not None
            and ref_coll.item_type != "protein.structure"
        ):
            raise ValueError(
                f"reference_candidates item_type must be protein.structure, "
                f"got {ref_coll.item_type}"
            )
        if mob_coll.item_type != "protein.structure":
            raise ValueError(
                f"mobile_candidates item_type must be protein.structure, "
                f"got {mob_coll.item_type}"
            )

        alignment_candidates: list[Candidate] = []

        reference_items = (
            ref_coll.items
            if ref_coll is not None
            else [None] * len(mob_coll)
        )
        for ref_item, mob_item in zip(reference_items, mob_coll.items):
            ref_struct = (
                reference if ref_item is None else ref_item.data
            )
            mob_struct = mob_item.data

            if not isinstance(ref_struct, ProteinStructure):
                candidate_id = (
                    "shared reference"
                    if ref_item is None
                    else f"Reference candidate {ref_item.candidate_id}"
                )
                raise ValueError(
                    f"{candidate_id} data is not a ProteinStructure"
                )
            if not isinstance(mob_struct, ProteinStructure):
                raise ValueError(
                    f"Mobile candidate {mob_item.candidate_id} data "
                    f"is not a ProteinStructure"
                )

            alignment = align_structures(
                ref_struct,
                mob_struct,
                call_details={
                    "candidate_id": (
                        mob_item.candidate_id
                        if ref_item is None
                        else ref_item.candidate_id
                    ),
                    "reference_candidate_id": (
                        None if ref_item is None else ref_item.candidate_id
                    ),
                    "mobile_candidate_id": mob_item.candidate_id,
                },
                separate_tiebreak_evidence=False,
            )

            alignment_candidates.append(
                Candidate(
                    candidate_id=(
                        mob_item.candidate_id
                        if ref_item is None
                        else ref_item.candidate_id
                    ),
                    data=alignment,
                    parent_ids=(
                        []
                        if ref_item is None
                        else [mob_item.candidate_id]
                    ),
                )
            )

        return {
            "alignments": CandidateCollection(
                collection_id=str(uuid.uuid4()),
                item_type="structure.alignment",
                items=alignment_candidates,
            ),
        }
