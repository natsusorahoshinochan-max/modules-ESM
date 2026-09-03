"""Explicit projections from residue conditioning values."""

from __future__ import annotations

from datatypes.candidate import Candidate, CandidateCollection
from datatypes.sequence import ProteinSequence

from core.operation import OperationCall


class MaterializeSequenceImplementation:
    """Project one complete single-chain sequence conditioning value.

    The input conditioning track must be complete (no missing residue) and
    single-chain. The outputs preserve the input residue identities: one
    ProteinSequence and one root sequence Candidate collection.
    """

    def execute(self, call: OperationCall) -> dict[str, object]:
        track = call.inputs["sequence"].value
        for index, value in enumerate(track.values):
            if value is None:
                raise ValueError(
                    "materialize_sequence requires complete sequence "
                    f"conditioning; residue index {index} is missing"
                )
        chain_ids = track.layout.chain_ids
        if len(chain_ids) != 1:
            raise ValueError(
                "materialize_sequence requires single-chain sequence "
                f"conditioning; found chains {', '.join(chain_ids)}"
            )
        sequence = ProteinSequence(
            "".join(track.values),
            residue_ids=tuple(track.layout.residue_ids),
        )
        candidate = Candidate(
            "materialized-sequence",
            sequence,
            [],
            {
                "operation": "materialize_sequence",
                "classification": "sequence",
                "source": "residue.condition.sequence",
            },
        )
        return {
            "sequence": sequence,
            "sequence_candidates": CandidateCollection(
                "materialized-sequences",
                "protein.sequence",
                [candidate],
            ),
        }
