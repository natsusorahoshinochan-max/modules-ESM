"""Public collection-scoring contract for structure.batch_tm_score."""

import pytest

from core.run_context import RunContext
from datatypes import (
    Candidate,
    CandidateCollection,
    ScoreCollection,
    StructureAlignment,
)
from modules.structure_batch_tm_score.module import BatchTMScoreModule


_BASE_COORDINATES = [
    [0.0, 0.0, 0.0],
    [2.0, 1.0, 0.0],
    [4.0, 0.0, 1.0],
    [6.0, 1.0, 0.0],
]


def _alignment(
    reference_coordinates: list[list[float]],
    mobile_coordinates: list[list[float]],
    *,
    reference_length: int | None = None,
    mobile_length: int | None = None,
    reference_indices: list[int] | None = None,
    mobile_indices: list[int] | None = None,
    rmsd: float = 0.0,
) -> StructureAlignment:
    aligned_residues = len(reference_coordinates)
    reference_indices = reference_indices or list(range(aligned_residues))
    mobile_indices = mobile_indices or list(range(aligned_residues))
    return StructureAlignment(
        residue_map=[
            (f"A:{reference_index + 1}", f"B:{mobile_index + 1}")
            for reference_index, mobile_index in zip(
                reference_indices,
                mobile_indices,
            )
        ],
        rmsd=rmsd,
        coverage=(
            aligned_residues
            / max(reference_length or aligned_residues, mobile_length or aligned_residues)
        ),
        reference_length=reference_length or aligned_residues,
        mobile_length=mobile_length or aligned_residues,
        aligned_reference_indices=reference_indices,
        aligned_mobile_indices=mobile_indices,
        aligned_reference_coordinates=reference_coordinates,
        aligned_mobile_coordinates=mobile_coordinates,
        aligned_distances=[0.0] * aligned_residues,
    )


def _collection(*items: tuple[str, StructureAlignment]) -> CandidateCollection:
    return CandidateCollection(
        collection_id="alignments",
        item_type="structure.alignment",
        items=[
            Candidate(candidate_id=candidate_id, data=alignment)
            for candidate_id, alignment in items
        ],
    )


class TestBatchTMScoreAlignmentPath:
    def test_missing_alignments_raises(self) -> None:
        with pytest.raises(ValueError, match="alignments"):
            BatchTMScoreModule().run(
                {},
                {},
                RunContext("/tmp/test", "missing-alignments"),
            )

    def test_alignments_produce_candidate_scores(self) -> None:
        identical = _alignment(
            _BASE_COORDINATES[:3],
            _BASE_COORDINATES[:3],
        )
        outlier = _alignment(
            _BASE_COORDINATES,
            [*_BASE_COORDINATES[:3], [30.0, 20.0, 10.0]],
            rmsd=10.0,
        )

        result = BatchTMScoreModule().run(
            {
                "alignments": _collection(
                    ("identical", identical),
                    ("outlier", outlier),
                )
            },
            {},
            RunContext("/tmp/test", "collection-scores"),
        )
        scores = result["scores"]

        assert isinstance(scores, ScoreCollection)
        assert [score.subjects for score in scores.entries] == [
            ["identical"],
            ["outlier"],
        ]
        assert scores.entries[0].value == pytest.approx(1.0)
        assert 0.0 < scores.entries[1].value < 1.0

    def test_empty_alignments_raise(self) -> None:
        with pytest.raises(ValueError, match="empty"):
            BatchTMScoreModule().run(
                {
                    "alignments": CandidateCollection(
                        collection_id="empty",
                        item_type="structure.alignment",
                        items=[],
                    )
                },
                {},
                RunContext("/tmp/test", "empty-alignments"),
            )

    def test_wrong_collection_item_type_raises(self) -> None:
        with pytest.raises(ValueError, match="item_type"):
            BatchTMScoreModule().run(
                {
                    "alignments": CandidateCollection(
                        collection_id="wrong",
                        item_type="protein.structure",
                        items=[Candidate(candidate_id="c1", data=None)],
                    )
                },
                {},
                RunContext("/tmp/test", "wrong-item-type"),
            )

    def test_non_alignment_candidate_data_raises(self) -> None:
        with pytest.raises(ValueError, match="not a StructureAlignment"):
            BatchTMScoreModule().run(
                {
                    "alignments": CandidateCollection(
                        collection_id="wrong-data",
                        item_type="structure.alignment",
                        items=[Candidate(candidate_id="c1", data=None)],
                    )
                },
                {},
                RunContext("/tmp/test", "wrong-data"),
            )

    def test_custom_score_id_is_preserved(self) -> None:
        result = BatchTMScoreModule().run(
            {
                "alignments": _collection(
                    (
                        "candidate",
                        _alignment(
                            _BASE_COORDINATES[:3],
                            _BASE_COORDINATES[:3],
                        ),
                    )
                )
            },
            {"score_id": "tm_vs_3gb1"},
            RunContext("/tmp/test", "custom-score-id"),
        )

        assert result["scores"].entries[0].score_id == "tm_vs_3gb1"

    def test_zero_correspondence_scores_zero(self) -> None:
        alignment = _alignment(
            [],
            [],
            reference_length=3,
            mobile_length=3,
        )

        result = BatchTMScoreModule().run(
            {"alignments": _collection(("no-overlap", alignment))},
            {},
            RunContext("/tmp/test", "zero-correspondence"),
        )
        score = result["scores"].entries[0]

        assert score.value == 0.0
        assert score.details["aligned_residues"] == 0
