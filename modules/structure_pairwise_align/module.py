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
        ref_coll: CandidateCollection | None = inputs.get("reference_candidates")
        mob_coll: CandidateCollection | None = inputs.get("mobile_candidates")

        if ref_coll is None:
            raise ValueError("reference_candidates input is required")
        if mob_coll is None:
            raise ValueError("mobile_candidates input is required")

        if len(ref_coll) == 0:
            raise ValueError("reference_candidates collection is empty")
        if len(mob_coll) == 0:
            raise ValueError("mobile_candidates collection is empty")

        if len(ref_coll) != len(mob_coll):
            raise ValueError(
                f"Collections must have equal length: "
                f"reference has {len(ref_coll)}, mobile has {len(mob_coll)}"
            )

        if ref_coll.item_type != "protein.structure":
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

        for ref_item, mob_item in zip(ref_coll.items, mob_coll.items):
            ref_struct = ref_item.data
            mob_struct = mob_item.data

            if not isinstance(ref_struct, ProteinStructure):
                raise ValueError(
                    f"Reference candidate {ref_item.candidate_id} data "
                    f"is not a ProteinStructure"
                )
            if not isinstance(mob_struct, ProteinStructure):
                raise ValueError(
                    f"Mobile candidate {mob_item.candidate_id} data "
                    f"is not a ProteinStructure"
                )

            alignment = align_structures(ref_struct, mob_struct)

            alignment_candidates.append(
                Candidate(
                    candidate_id=ref_item.candidate_id,
                    data=alignment,
                )
            )

        return {
            "alignments": CandidateCollection(
                collection_id=str(uuid.uuid4()),
                item_type="structure.alignment",
                items=alignment_candidates,
            ),
        }
