"""Tests for candidate selection modules (ticket 10)."""

import json

import pytest

from core.run_context import RunContext
from datatypes import (
    Candidate,
    CandidateCollection,
    ProteinSequence,
    ProteinStructure,
    Score,
    ScoreCollection,
)

SAMPLE_PDB = """\
ATOM      1  N   ALA A   1       0.000   0.000   0.000  1.00  0.00           N
ATOM      2  CA  ALA A   1       1.458   0.000   0.000  1.00  0.00           C
END
"""


def _make_candidates(n: int = 5, prefix: str = "c") -> CandidateCollection:
    """Create a test CandidateCollection with sequence candidates."""
    items = []
    for i in range(n):
        cid = f"{prefix}{i}"
        items.append(Candidate(
            candidate_id=cid,
            data=ProteinSequence(sequence=f"SEQ{i}"),
            parent_ids=[f"p{i}"],
            metadata={"sample_index": i},
        ))
    return CandidateCollection(
        collection_id="test-coll",
        item_type="protein.sequence",
        items=items,
    )


def _make_scores(cids: list[str], score_id: str, values: list[float]) -> ScoreCollection:
    """Create a ScoreCollection with one entry per candidate."""
    entries = []
    for cid, val in zip(cids, values):
        entries.append(Score(score_id=score_id, value=val, subjects=[cid]))
    return ScoreCollection(collection_id="test-scores", entries=entries)


# ── Filter Candidates ────────────────────────────────────────────────

class TestFilterCandidates:
    def test_filters_by_threshold(self) -> None:
        from modules.filter_candidates.module import FilterCandidatesModule
        mod = FilterCandidatesModule()
        ctx = RunContext("/tmp/test", "n1")
        coll = _make_candidates(3)
        scores = _make_scores(["c0", "c1", "c2"], "tm_score", [0.5, 0.8, 0.95])

        conditions = json.dumps([
            {"score": "tm_score", "operator": ">=", "value": 0.75},
        ])
        result = mod.run(
            {"candidates": coll, "scores": scores},
            {"conditions": conditions},
            ctx,
        )

        filtered = result["candidates"]
        assert len(filtered) == 2
        kept_ids = {c.candidate_id for c in filtered.items}
        assert kept_ids == {"c1", "c2"}

    def test_multiple_conditions_all_must_pass(self) -> None:
        from modules.filter_candidates.module import FilterCandidatesModule
        mod = FilterCandidatesModule()
        ctx = RunContext("/tmp/test", "n1")
        coll = _make_candidates(3)
        scores = ScoreCollection(
            collection_id="test",
            entries=[
                Score(score_id="tm", value=0.7, subjects=["c0"]),
                Score(score_id="plddt", value=0.6, subjects=["c0"]),
                Score(score_id="tm", value=0.8, subjects=["c1"]),
                Score(score_id="plddt", value=0.9, subjects=["c1"]),
                Score(score_id="tm", value=0.5, subjects=["c2"]),
                Score(score_id="plddt", value=0.5, subjects=["c2"]),
            ],
        )

        conditions = json.dumps([
            {"score": "tm", "operator": ">=", "value": 0.7},
            {"score": "plddt", "operator": ">=", "value": 0.7},
        ])
        result = mod.run(
            {"candidates": coll, "scores": scores},
            {"conditions": conditions},
            ctx,
        )

        filtered = result["candidates"]
        assert len(filtered) == 1
        assert filtered.items[0].candidate_id == "c1"

    def test_no_conditions_returns_all(self) -> None:
        from modules.filter_candidates.module import FilterCandidatesModule
        mod = FilterCandidatesModule()
        ctx = RunContext("/tmp/test", "n1")
        coll = _make_candidates(3)
        scores = _make_scores(["c0", "c1", "c2"], "x", [1.0, 2.0, 3.0])
        result = mod.run(
            {"candidates": coll, "scores": scores},
            {"conditions": "[]"},
            ctx,
        )
        assert len(result["candidates"]) == 3

    def test_missing_inputs_raises(self) -> None:
        from modules.filter_candidates.module import FilterCandidatesModule
        mod = FilterCandidatesModule()
        ctx = RunContext("/tmp/test", "n1")
        with pytest.raises(ValueError, match="candidates"):
            mod.run({}, {}, ctx)
        coll = _make_candidates(1)
        with pytest.raises(ValueError, match="scores"):
            mod.run({"candidates": coll}, {}, ctx)


# ── Sort Candidates ──────────────────────────────────────────────────

class TestSortCandidates:
    def test_sorts_descending(self) -> None:
        from modules.sort_candidates.module import SortCandidatesModule
        mod = SortCandidatesModule()
        ctx = RunContext("/tmp/test", "n1")
        coll = _make_candidates(3)
        scores = _make_scores(["c0", "c1", "c2"], "plddt", [0.5, 0.9, 0.7])

        result = mod.run(
            {"candidates": coll, "scores": scores},
            {"score": "plddt", "order": "descending"},
            ctx,
        )
        sorted_ids = [c.candidate_id for c in result["candidates"].items]
        assert sorted_ids == ["c1", "c2", "c0"]

    def test_sorts_ascending(self) -> None:
        from modules.sort_candidates.module import SortCandidatesModule
        mod = SortCandidatesModule()
        ctx = RunContext("/tmp/test", "n1")
        coll = _make_candidates(3)
        scores = _make_scores(["c0", "c1", "c2"], "plddt", [0.5, 0.9, 0.7])

        result = mod.run(
            {"candidates": coll, "scores": scores},
            {"score": "plddt", "order": "ascending"},
            ctx,
        )
        sorted_ids = [c.candidate_id for c in result["candidates"].items]
        assert sorted_ids == ["c0", "c2", "c1"]


# ── Top-K ────────────────────────────────────────────────────────────

class TestTopK:
    def test_keeps_first_k(self) -> None:
        from modules.top_k.module import TopKModule
        mod = TopKModule()
        ctx = RunContext("/tmp/test", "n1")
        coll = _make_candidates(10)

        result = mod.run({"candidates": coll}, {"k": 3}, ctx)
        assert len(result["candidates"]) == 3
        assert result["candidates"].items[0].candidate_id == "c0"
        assert result["candidates"].items[2].candidate_id == "c2"

    def test_k_larger_than_collection_returns_all(self) -> None:
        from modules.top_k.module import TopKModule
        mod = TopKModule()
        ctx = RunContext("/tmp/test", "n1")
        coll = _make_candidates(3)

        result = mod.run({"candidates": coll}, {"k": 10}, ctx)
        assert len(result["candidates"]) == 3

    def test_k_zero_raises(self) -> None:
        from modules.top_k.module import TopKModule
        mod = TopKModule()
        ctx = RunContext("/tmp/test", "n1")
        coll = _make_candidates(1)
        with pytest.raises(ValueError, match="k must be at least 1"):
            mod.run({"candidates": coll}, {"k": 0}, ctx)

    def test_missing_input_raises(self) -> None:
        from modules.top_k.module import TopKModule
        mod = TopKModule()
        ctx = RunContext("/tmp/test", "n1")
        with pytest.raises(ValueError, match="candidates"):
            mod.run({}, {}, ctx)


# ── Weighted Rank ─────────────────────────────────────────────────────

class TestWeightedRank:
    def test_ranks_by_weighted_sum(self) -> None:
        from modules.weighted_rank.module import WeightedRankModule
        mod = WeightedRankModule()
        ctx = RunContext("/tmp/test", "n1")
        coll = _make_candidates(3)
        scores = ScoreCollection(
            collection_id="test",
            entries=[
                Score(score_id="tm", value=0.7, subjects=["c0"]),
                Score(score_id="plddt", value=0.6, subjects=["c0"]),
                Score(score_id="tm", value=0.8, subjects=["c1"]),
                Score(score_id="plddt", value=0.9, subjects=["c1"]),
                Score(score_id="tm", value=0.5, subjects=["c2"]),
                Score(score_id="plddt", value=0.5, subjects=["c2"]),
            ],
        )

        metrics = json.dumps([
            {"score": "tm", "weight": 1.0},
            {"score": "plddt", "weight": 0.5},
        ])
        result = mod.run(
            {"candidates": coll, "scores": scores},
            {"metrics": metrics},
            ctx,
        )

        sorted_ids = [c.candidate_id for c in result["candidates"].items]
        # c1: 0.8 + 0.5*0.9 = 1.25, c0: 0.7 + 0.5*0.6 = 1.0, c2: 0.5 + 0.5*0.5 = 0.75
        assert sorted_ids[0] == "c1"  # highest sum (1.25)
        assert sorted_ids[1] == "c0"  # middle (1.0)
        assert sorted_ids[2] == "c2"  # lowest sum (0.75)

        # Check weighted rank scores
        out_scores = result["scores"]
        assert len(out_scores.entries) == 9
        rank_entry = [s for s in out_scores.entries if s.score_id == "weighted_rank"]
        assert len(rank_entry) == 3

    def test_negative_weight_minimizes(self) -> None:
        from modules.weighted_rank.module import WeightedRankModule
        mod = WeightedRankModule()
        ctx = RunContext("/tmp/test", "n1")
        coll = _make_candidates(3)
        scores = _make_scores(["c0", "c1", "c2"], "rmsd", [2.0, 1.0, 3.0])

        metrics = json.dumps([{"score": "rmsd", "weight": -1.0}])
        result = mod.run(
            {"candidates": coll, "scores": scores},
            {"metrics": metrics},
            ctx,
        )

        sorted_ids = [c.candidate_id for c in result["candidates"].items]
        # c1: -1.0, c0: -2.0, c2: -3.0 -> sorted desc: c1, c0, c2
        assert sorted_ids == ["c1", "c0", "c2"]

    def test_missing_metrics_raises(self) -> None:
        from modules.weighted_rank.module import WeightedRankModule
        mod = WeightedRankModule()
        ctx = RunContext("/tmp/test", "n1")
        coll = _make_candidates(1)
        scores = _make_scores(["c0"], "x", [1.0])
        with pytest.raises(ValueError, match="At least one metric"):
            mod.run({"candidates": coll, "scores": scores}, {"metrics": "[]"}, ctx)


# ── Pareto Select ─────────────────────────────────────────────────────

class TestParetoSelect:
    def test_returns_non_dominated(self) -> None:
        from modules.pareto_select.module import ParetoSelectModule
        mod = ParetoSelectModule()
        ctx = RunContext("/tmp/test", "n1")
        coll = _make_candidates(4)
        scores = ScoreCollection(
            collection_id="test",
            entries=[
                # c0: (0.9, 0.5) - good tm, bad plddt
                Score(score_id="tm", value=0.9, subjects=["c0"]),
                Score(score_id="plddt", value=0.5, subjects=["c0"]),
                # c1: (0.5, 0.9) - bad tm, good plddt
                Score(score_id="tm", value=0.5, subjects=["c1"]),
                Score(score_id="plddt", value=0.9, subjects=["c1"]),
                # c2: (0.8, 0.8) - balanced, dominates nothing
                Score(score_id="tm", value=0.8, subjects=["c2"]),
                Score(score_id="plddt", value=0.8, subjects=["c2"]),
                # c3: (0.95, 0.3) - great tm, bad plddt, dominated by none overall (c0 beats it on plddt, c1 beats it on plddt)
                Score(score_id="tm", value=0.95, subjects=["c3"]),
                Score(score_id="plddt", value=0.3, subjects=["c3"]),
            ],
        )

        result = mod.run(
            {"candidates": coll, "scores": scores},
            {"scores_list": json.dumps(["tm", "plddt"])},
            ctx,
        )

        pareto_ids = {c.candidate_id for c in result["candidates"].items}
        # c3 has best tm but worst plddt. c0 has best balanced but not dominant.
        # c0 dominates nothing, c1 dominates nothing.
        # c2 (0.8, 0.8) is dominated by nothing since c3 has worse plddt.
        assert "c3" in pareto_ids
        assert "c0" in pareto_ids
        assert "c1" in pareto_ids
        assert "c2" in pareto_ids
        assert "c3" in pareto_ids  # all are non-dominated now

    def test_all_equal_returns_all(self) -> None:
        from modules.pareto_select.module import ParetoSelectModule
        mod = ParetoSelectModule()
        ctx = RunContext("/tmp/test", "n1")
        coll = _make_candidates(3)
        scores = ScoreCollection(
            collection_id="test",
            entries=[
                Score(score_id="x", value=1.0, subjects=["c0"]),
                Score(score_id="x", value=1.0, subjects=["c1"]),
                Score(score_id="x", value=1.0, subjects=["c2"]),
            ],
        )
        result = mod.run(
            {"candidates": coll, "scores": scores},
            {"scores_list": json.dumps(["x"])},
            ctx,
        )
        assert len(result["candidates"]) == 3

    def test_missing_score_list_raises(self) -> None:
        from modules.pareto_select.module import ParetoSelectModule
        mod = ParetoSelectModule()
        ctx = RunContext("/tmp/test", "n1")
        coll = _make_candidates(1)
        scores = _make_scores(["c0"], "x", [1.0])
        with pytest.raises(ValueError, match="At least one score_id"):
            mod.run({"candidates": coll, "scores": scores}, {}, ctx)


# ── Diversity Select ─────────────────────────────────────────────────

class TestDiversitySelect:
    def test_selects_diverse_candidates(self) -> None:
        from modules.diversity_select.module import DiversitySelectModule
        mod = DiversitySelectModule()
        ctx = RunContext("/tmp/test", "n1")
        coll = _make_candidates(10)
        scores = _make_scores(
            [f"c{i}" for i in range(10)],
            "plddt",
            [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0],
        )

        result = mod.run(
            {"candidates": coll, "scores": scores},
            {"k": 3, "diversity_score": "plddt"},
            ctx,
        )
        diverse = result["candidates"]
        assert len(diverse) == 3
        # Should pick extremes: first (0.1), middle (0.5), last (1.0)
        div_scores = [scores.entries[int(c.candidate_id[1])].value for c in diverse.items]
        assert min(div_scores) <= 0.3
        assert max(div_scores) >= 0.8

    def test_k_larger_than_input_returns_all(self) -> None:
        from modules.diversity_select.module import DiversitySelectModule
        mod = DiversitySelectModule()
        ctx = RunContext("/tmp/test", "n1")
        coll = _make_candidates(3)
        scores = _make_scores(["c0", "c1", "c2"], "x", [1.0, 2.0, 3.0])
        result = mod.run(
            {"candidates": coll, "scores": scores},
            {"k": 10},
            ctx,
        )
        assert len(result["candidates"]) == 3

    def test_missing_inputs_raises(self) -> None:
        from modules.diversity_select.module import DiversitySelectModule
        mod = DiversitySelectModule()
        ctx = RunContext("/tmp/test", "n1")
        with pytest.raises(ValueError, match="candidates"):
            mod.run({}, {}, ctx)
