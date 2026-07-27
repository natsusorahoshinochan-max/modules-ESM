"""Candidate-bound structure scoring and fail-closed weighted ranking."""

import pytest

from core.run_context import RunContext
from datatypes import (
    Candidate,
    CandidateCollection,
    ProteinStructure,
    Score,
    ScoreCollection,
    StructureAlignment,
)
from modules.merge_scores.module import MergeScoresModule
from modules.structure_rmsd.module import StructureRMSDModule
from modules.structure_tm_score.module import StructureTMScoreModule
from modules.top_k.module import TopKModule
from modules.weighted_rank.module import WeightedRankModule


def _alignment(*, rmsd: float = 0.0) -> StructureAlignment:
    coordinates = [
        [0.0, 0.0, 0.0],
        [2.0, 1.0, 0.0],
        [4.0, 0.0, 1.0],
    ]
    return StructureAlignment(
        residue_map=[("A:1", "B:1"), ("A:2", "B:2"), ("A:3", "B:3")],
        rmsd=rmsd,
        coverage=1.0,
        reference_length=3,
        mobile_length=3,
        aligned_reference_indices=[0, 1, 2],
        aligned_mobile_indices=[0, 1, 2],
        aligned_reference_coordinates=coordinates,
        aligned_mobile_coordinates=coordinates,
        aligned_distances=[0.0, 0.0, 0.0],
    )


def _candidates(*candidate_ids: str) -> CandidateCollection:
    return CandidateCollection(
        collection_id="folded-candidates",
        item_type="protein.structure",
        items=[
            Candidate(
                candidate_id=candidate_id,
                data=ProteinStructure(pdb_string="END\n"),
            )
            for candidate_id in candidate_ids
        ],
    )


def test_tm_score_names_its_candidate_and_preserves_its_objective_id() -> None:
    result = StructureTMScoreModule().run(
        {"alignment": _alignment()},
        {"candidate_id": "folded-7", "score_id": "tm_vs_3gb1"},
        RunContext("/tmp/test", "candidate-bound-tm"),
    )

    score = result["scores"].entries[0]
    assert score.score_id == "tm_vs_3gb1"
    assert score.subjects == ["folded-7"]
    assert score.value == pytest.approx(1.0)


def test_tm_score_rejects_a_missing_candidate_subject() -> None:
    with pytest.raises(ValueError, match="candidate_id"):
        StructureTMScoreModule().run(
            {"alignment": _alignment()},
            {},
            RunContext("/tmp/test", "missing-tm-subject"),
        )


def test_rmsd_score_names_its_candidate() -> None:
    result = StructureRMSDModule().run(
        {"alignment": _alignment(rmsd=2.345)},
        {"candidate_id": "folded-7"},
        RunContext("/tmp/test", "candidate-bound-rmsd"),
    )

    score = result["scores"].entries[0]
    assert score.score_id == "rmsd"
    assert score.subjects == ["folded-7"]
    assert score.value == pytest.approx(2.345)


def test_rmsd_score_rejects_a_missing_candidate_subject() -> None:
    with pytest.raises(ValueError, match="candidate_id"):
        StructureRMSDModule().run(
            {"alignment": _alignment()},
            {},
            RunContext("/tmp/test", "missing-rmsd-subject"),
        )


def test_complete_distinct_objectives_produce_exact_weighted_top_three() -> None:
    candidates = _candidates("delta", "charlie", "bravo", "alpha")
    tm_vs_3gb1 = ScoreCollection(
        collection_id="tm-vs-3gb1",
        entries=[
            Score("tm_vs_3gb1", 0.5, ["delta"]),
            Score("tm_vs_3gb1", 0.8, ["charlie"]),
            Score("tm_vs_3gb1", 0.6, ["bravo"]),
            Score("tm_vs_3gb1", 0.123456, ["alpha"]),
        ],
    )
    tm_vs_esm3 = ScoreCollection(
        collection_id="tm-vs-esm3",
        entries=[
            Score("tm_vs_esm3", 0.5, ["delta"]),
            Score("tm_vs_esm3", 0.4, ["charlie"]),
            Score("tm_vs_esm3", 0.9, ["bravo"]),
            Score("tm_vs_esm3", 0.654321, ["alpha"]),
        ],
    )
    context = RunContext("/tmp/test", "weighted-top-three")

    merged = MergeScoresModule().run(
        {"scores_a": tm_vs_3gb1, "scores_b": tm_vs_esm3},
        {},
        context,
    )["scores"]
    ranked = WeightedRankModule().run(
        {"candidates": candidates, "scores": merged},
        {
            "metrics": [
                {"score": "tm_vs_3gb1", "weight": 0.7},
                {"score": "tm_vs_esm3", "weight": 0.3},
            ]
        },
        context,
    )
    top_three = TopKModule().run(
        {"candidates": ranked["candidates"]},
        {"k": 3},
        context,
    )["candidates"]

    assert [candidate.candidate_id for candidate in top_three.items] == [
        "bravo",
        "charlie",
        "delta",
    ]
    assert {score.score_id for score in ranked["scores"].entries} == {
        "tm_vs_3gb1",
        "tm_vs_esm3",
        "weighted_rank",
    }
    alpha_rank = next(
        score
        for score in ranked["scores"].entries
        if score.score_id == "weighted_rank" and score.subjects == ["alpha"]
    )
    assert alpha_rank.value == pytest.approx(0.2827155)


def test_weighted_ranking_rejects_a_missing_required_candidate_score() -> None:
    scores = ScoreCollection(
        collection_id="incomplete",
        entries=[
            Score("tm_vs_3gb1", 0.8, ["alpha"]),
            Score("tm_vs_esm3", 0.9, ["alpha"]),
            Score("tm_vs_3gb1", 0.7, ["bravo"]),
        ],
    )

    with pytest.raises(
        ValueError,
        match="tm_vs_esm3.*bravo",
    ):
        WeightedRankModule().run(
            {
                "candidates": _candidates("alpha", "bravo"),
                "scores": scores,
            },
            {
                "metrics": [
                    {"score": "tm_vs_3gb1", "weight": 0.7},
                    {"score": "tm_vs_esm3", "weight": 0.3},
                ]
            },
            RunContext("/tmp/test", "missing-required-score"),
        )


def test_weighted_ranking_rejects_a_required_score_without_subjects() -> None:
    scores = ScoreCollection(
        collection_id="missing-subject",
        entries=[
            Score("tm_vs_3gb1", 0.8, ["alpha"]),
            Score("tm_vs_esm3", 0.9, []),
        ],
    )

    with pytest.raises(ValueError, match="tm_vs_esm3.*subjects"):
        WeightedRankModule().run(
            {"candidates": _candidates("alpha"), "scores": scores},
            {
                "metrics": [
                    {"score": "tm_vs_3gb1", "weight": 0.7},
                    {"score": "tm_vs_esm3", "weight": 0.3},
                ]
            },
            RunContext("/tmp/test", "missing-score-subject"),
        )


def test_weighted_ranking_rejects_a_duplicate_candidate_score_pair() -> None:
    scores = ScoreCollection(
        collection_id="duplicate-pair",
        entries=[
            Score("tm_vs_3gb1", 0.8, ["alpha"]),
            Score("tm_vs_3gb1", 0.7, ["alpha"]),
            Score("tm_vs_esm3", 0.9, ["alpha"]),
        ],
    )

    with pytest.raises(
        ValueError,
        match="Duplicate.*alpha.*tm_vs_3gb1",
    ):
        WeightedRankModule().run(
            {"candidates": _candidates("alpha"), "scores": scores},
            {
                "metrics": [
                    {"score": "tm_vs_3gb1", "weight": 0.7},
                    {"score": "tm_vs_esm3", "weight": 0.3},
                ]
            },
            RunContext("/tmp/test", "duplicate-score-pair"),
        )


def test_weighted_ranking_rejects_a_required_score_for_an_unknown_candidate() -> None:
    scores = ScoreCollection(
        collection_id="unknown-candidate",
        entries=[
            Score("tm_vs_3gb1", 0.8, ["alpha"]),
            Score("tm_vs_esm3", 0.9, ["alpha"]),
            Score("tm_vs_3gb1", 0.7, ["ghost"]),
        ],
    )

    with pytest.raises(
        ValueError,
        match="ghost.*not present",
    ):
        WeightedRankModule().run(
            {"candidates": _candidates("alpha"), "scores": scores},
            {
                "metrics": [
                    {"score": "tm_vs_3gb1", "weight": 0.7},
                    {"score": "tm_vs_esm3", "weight": 0.3},
                ]
            },
            RunContext("/tmp/test", "unknown-score-subject"),
        )


def test_weighted_ranking_rejects_duplicate_objective_ids() -> None:
    scores = ScoreCollection(
        collection_id="duplicate-objective",
        entries=[Score("tm_vs_3gb1", 0.8, ["alpha"])],
    )

    with pytest.raises(ValueError, match="Duplicate metric.*tm_vs_3gb1"):
        WeightedRankModule().run(
            {"candidates": _candidates("alpha"), "scores": scores},
            {
                "metrics": [
                    {"score": "tm_vs_3gb1", "weight": 0.7},
                    {"score": "tm_vs_3gb1", "weight": 0.3},
                ]
            },
            RunContext("/tmp/test", "duplicate-objective"),
        )


def test_weighted_ranking_rejects_duplicate_candidate_ids() -> None:
    candidates = _candidates("alpha", "alpha")
    scores = ScoreCollection(
        collection_id="duplicate-candidate",
        entries=[
            Score("tm_vs_3gb1", 0.8, ["alpha"]),
            Score("tm_vs_esm3", 0.9, ["alpha"]),
        ],
    )

    with pytest.raises(ValueError, match="Duplicate Candidate ID.*alpha"):
        WeightedRankModule().run(
            {"candidates": candidates, "scores": scores},
            {
                "metrics": [
                    {"score": "tm_vs_3gb1", "weight": 0.7},
                    {"score": "tm_vs_esm3", "weight": 0.3},
                ]
            },
            RunContext("/tmp/test", "duplicate-candidate"),
        )


def test_weighted_ranking_breaks_ties_by_candidate_id_before_top_three() -> None:
    candidate_ids = ["delta", "charlie", "bravo", "alpha"]
    scores = ScoreCollection(
        collection_id="tied-scores",
        entries=[
            Score(score_id, 0.5, [candidate_id])
            for candidate_id in candidate_ids
            for score_id in ("tm_vs_3gb1", "tm_vs_esm3")
        ],
    )
    context = RunContext("/tmp/test", "deterministic-ties")

    ranked = WeightedRankModule().run(
        {
            "candidates": _candidates(*candidate_ids),
            "scores": scores,
        },
        {
            "metrics": [
                {"score": "tm_vs_3gb1", "weight": 0.7},
                {"score": "tm_vs_esm3", "weight": 0.3},
            ]
        },
        context,
    )["candidates"]
    top_three = TopKModule().run(
        {"candidates": ranked},
        {"k": 3},
        context,
    )["candidates"]

    assert [candidate.candidate_id for candidate in top_three.items] == [
        "alpha",
        "bravo",
        "charlie",
    ]
