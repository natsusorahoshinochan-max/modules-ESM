"""Tests for prompt.random_insert_masked module (ticket 13)."""

import pytest

from core.run_context import RunContext
from datatypes import ResidueLayout, ResidueTrack


def _make_track(values: list, sentinel=None) -> ResidueTrack:
    return ResidueTrack(values=list(values), sentinel=sentinel)


def _make_layout(length: int, chain_id: str = "A",
                 residue_ids: list | None = None) -> ResidueLayout:
    return ResidueLayout(chain_id=chain_id, length=length, residue_ids=residue_ids)


class TestRandomInsertMasked:
    def test_inserts_exactly_count_sentinels(self) -> None:
        from modules.prompt_random_insert_masked.module import (
            RandomInsertMaskedModule,
        )
        mod = RandomInsertMaskedModule()
        ctx = RunContext("/tmp/test", "n1", seed=42)
        track = _make_track(["A"] * 56)
        layout = _make_layout(56)

        result = mod.run({"track": track, "layout": layout}, {"count": 15}, ctx)
        out_track = result["track"]
        out_layout = result["layout"]

        assert len(out_track) == 71
        assert out_track.specified_count() == 56
        assert out_track.values.count(out_track.sentinel) == 15
        assert out_layout.length == 71
        assert out_layout.chain_id == "A"

    def test_original_values_preserve_order(self) -> None:
        from modules.prompt_random_insert_masked.module import (
            RandomInsertMaskedModule,
        )
        mod = RandomInsertMaskedModule()
        ctx = RunContext("/tmp/test", "n1", seed=42)
        original = [f"R{i}" for i in range(10)]
        track = _make_track(original)
        layout = _make_layout(10)

        result = mod.run({"track": track, "layout": layout}, {"count": 3}, ctx)
        out_values = result["track"].values

        non_sentinel = [v for v in out_values if v is not track.sentinel]
        assert non_sentinel == original

    def test_identical_seed_yields_same_positions(self) -> None:
        from modules.prompt_random_insert_masked.module import (
            RandomInsertMaskedModule,
        )
        mod = RandomInsertMaskedModule()
        track = _make_track(["A"] * 56)
        layout = _make_layout(56)

        ctx1 = RunContext("/tmp/test", "n1", seed=12345)
        out1 = mod.run(
            {"track": track, "layout": layout}, {"count": 15}, ctx1
        )["track"]

        ctx2 = RunContext("/tmp/test", "n2", seed=12345)
        out2 = mod.run(
            {"track": track, "layout": layout}, {"count": 15}, ctx2
        )["track"]

        assert out1.values == out2.values

    def test_count_zero_no_change(self) -> None:
        from modules.prompt_random_insert_masked.module import (
            RandomInsertMaskedModule,
        )
        mod = RandomInsertMaskedModule()
        ctx = RunContext("/tmp/test", "n1", seed=42)
        track = _make_track(["A", "B", "C"])
        layout = _make_layout(3)

        result = mod.run({"track": track, "layout": layout}, {"count": 0}, ctx)

        assert result["track"].values == ["A", "B", "C"]
        assert result["layout"].length == 3

    def test_missing_track_raises(self) -> None:
        from modules.prompt_random_insert_masked.module import (
            RandomInsertMaskedModule,
        )
        mod = RandomInsertMaskedModule()
        ctx = RunContext("/tmp/test", "n1", seed=42)
        layout = _make_layout(10)

        with pytest.raises(ValueError, match="track"):
            mod.run({"layout": layout}, {"count": 5}, ctx)

    def test_missing_layout_raises(self) -> None:
        from modules.prompt_random_insert_masked.module import (
            RandomInsertMaskedModule,
        )
        mod = RandomInsertMaskedModule()
        ctx = RunContext("/tmp/test", "n1", seed=42)
        track = _make_track(["A"] * 10)

        with pytest.raises(ValueError, match="layout"):
            mod.run({"track": track}, {"count": 5}, ctx)

    def test_negative_count_raises(self) -> None:
        from modules.prompt_random_insert_masked.module import (
            RandomInsertMaskedModule,
        )
        mod = RandomInsertMaskedModule()
        ctx = RunContext("/tmp/test", "n1", seed=42)
        track = _make_track(["A"] * 10)
        layout = _make_layout(10)

        with pytest.raises(ValueError, match="non-negative"):
            mod.run(
                {"track": track, "layout": layout}, {"count": -1}, ctx
            )

    def test_updates_layout_residue_ids(self) -> None:
        from modules.prompt_random_insert_masked.module import (
            RandomInsertMaskedModule,
        )
        mod = RandomInsertMaskedModule()
        ctx = RunContext("/tmp/test", "n1", seed=42)
        track = _make_track(["A", "B", "C"])
        layout = _make_layout(3, residue_ids=["R1", "R2", "R3"])

        result = mod.run({"track": track, "layout": layout}, {"count": 2}, ctx)
        out_layout = result["layout"]

        assert out_layout.length == 5
        assert out_layout.residue_ids is not None
        non_none = [r for r in out_layout.residue_ids if r is not None]
        assert non_none == ["R1", "R2", "R3"]
        assert out_layout.residue_ids.count(None) == 2

    def test_layout_without_residue_ids(self) -> None:
        from modules.prompt_random_insert_masked.module import (
            RandomInsertMaskedModule,
        )
        mod = RandomInsertMaskedModule()
        ctx = RunContext("/tmp/test", "n1", seed=42)
        track = _make_track(["A"] * 5)
        layout = _make_layout(5)

        result = mod.run({"track": track, "layout": layout}, {"count": 3}, ctx)
        out_layout = result["layout"]

        assert out_layout.length == 8
        assert out_layout.residue_ids is None

    def test_custom_sentinel(self) -> None:
        from modules.prompt_random_insert_masked.module import (
            RandomInsertMaskedModule,
        )
        mod = RandomInsertMaskedModule()
        ctx = RunContext("/tmp/test", "n1", seed=42)
        track = _make_track(["X"] * 5, sentinel="MASK")
        layout = _make_layout(5)

        result = mod.run({"track": track, "layout": layout}, {"count": 2}, ctx)
        out = result["track"]

        assert out.sentinel == "MASK"
        assert out.values.count("MASK") == 2
        assert out.specified_count() == 5
