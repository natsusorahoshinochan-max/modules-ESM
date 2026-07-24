"""Tests for prompt.random_mask module (ticket 12)."""

import pytest

from core.run_context import RunContext
from datatypes import ResidueTrack


def _make_track(values: list, sentinel=None) -> ResidueTrack:
    """Create a ResidueTrack with explicit sentinel."""
    return ResidueTrack(values=list(values), sentinel=sentinel)


class TestRandomMask:
    def test_masks_exactly_count_positions(self) -> None:
        from modules.prompt_random_mask.module import RandomMaskModule
        mod = RandomMaskModule()
        ctx = RunContext("/tmp/test", "n1", seed=42)
        track = _make_track(["A"] * 56)

        result = mod.run({"track": track}, {"count": 20}, ctx)
        out = result["track"]

        assert isinstance(out, ResidueTrack)
        assert len(out) == 56
        assert out.specified_count() == 36
        assert out.values.count(out.sentinel) == 20

    def test_preserves_original_non_masked_values(self) -> None:
        from modules.prompt_random_mask.module import RandomMaskModule
        mod = RandomMaskModule()
        ctx = RunContext("/tmp/test", "n1", seed=42)
        values = [f"R{i}" for i in range(56)]
        track = _make_track(values)

        result = mod.run({"track": track}, {"count": 20}, ctx)
        out = result["track"]

        for i, v in enumerate(out.values):
            if v is not out.sentinel:
                assert v == values[i]

    def test_respects_existing_sentinels(self) -> None:
        from modules.prompt_random_mask.module import RandomMaskModule
        mod = RandomMaskModule()
        ctx = RunContext("/tmp/test", "n1", seed=42)
        # Pre-mask 5 positions
        values = ["A"] * 20
        values[3] = None
        values[7] = None
        values[11] = None
        values[15] = None
        values[19] = None
        track = _make_track(values, sentinel=None)

        result = mod.run({"track": track}, {"count": 5}, ctx)
        out = result["track"]

        # Original sentinel positions still sentinel
        for i in [3, 7, 11, 15, 19]:
            assert out.values[i] is out.sentinel
        # Exactly 10 total sentinels: 5 original + 5 new
        assert out.specified_count() == 10
        assert out.values.count(out.sentinel) == 10

    def test_identical_seed_yields_same_mask(self) -> None:
        from modules.prompt_random_mask.module import RandomMaskModule
        mod = RandomMaskModule()
        track = _make_track(["A"] * 56)

        ctx1 = RunContext("/tmp/test", "n1", seed=12345)
        out1 = mod.run({"track": track}, {"count": 20}, ctx1)["track"]

        ctx2 = RunContext("/tmp/test", "n2", seed=12345)
        out2 = mod.run({"track": track}, {"count": 20}, ctx2)["track"]

        assert out1.values == out2.values

    def test_different_seed_yields_different_mask(self) -> None:
        from modules.prompt_random_mask.module import RandomMaskModule
        mod = RandomMaskModule()
        track = _make_track(["A"] * 200)

        ctx1 = RunContext("/tmp/test", "n1", seed=1)
        out1 = mod.run({"track": track}, {"count": 50}, ctx1)["track"]

        ctx2 = RunContext("/tmp/test", "n1", seed=2)
        out2 = mod.run({"track": track}, {"count": 50}, ctx2)["track"]

        # With 200 positions and 50 masks, different seeds should very likely differ
        assert out1.values != out2.values

    def test_count_zero_no_change(self) -> None:
        from modules.prompt_random_mask.module import RandomMaskModule
        mod = RandomMaskModule()
        ctx = RunContext("/tmp/test", "n1", seed=42)
        values = ["A", "B", "C", "D", "E"]
        track = _make_track(values)

        result = mod.run({"track": track}, {"count": 0}, ctx)
        out = result["track"]

        assert out.values == values

    def test_count_exceeds_specified_raises(self) -> None:
        from modules.prompt_random_mask.module import RandomMaskModule
        mod = RandomMaskModule()
        ctx = RunContext("/tmp/test", "n1", seed=42)
        track = _make_track(["A"] * 5)

        with pytest.raises(ValueError, match="exceeds"):
            mod.run({"track": track}, {"count": 6}, ctx)

    def test_missing_track_raises(self) -> None:
        from modules.prompt_random_mask.module import RandomMaskModule
        mod = RandomMaskModule()
        ctx = RunContext("/tmp/test", "n1", seed=42)

        with pytest.raises(ValueError, match="track"):
            mod.run({}, {"count": 5}, ctx)

    def test_negative_count_raises(self) -> None:
        from modules.prompt_random_mask.module import RandomMaskModule
        mod = RandomMaskModule()
        ctx = RunContext("/tmp/test", "n1", seed=42)
        track = _make_track(["A"] * 10)

        with pytest.raises(ValueError, match="non-negative"):
            mod.run({"track": track}, {"count": -1}, ctx)

    def test_custom_sentinel(self) -> None:
        from modules.prompt_random_mask.module import RandomMaskModule
        mod = RandomMaskModule()
        ctx = RunContext("/tmp/test", "n1", seed=42)
        track = _make_track(["X"] * 10, sentinel="MASK")

        result = mod.run({"track": track}, {"count": 3}, ctx)
        out = result["track"]

        assert out.sentinel == "MASK"
        assert out.values.count("MASK") == 3
        assert out.specified_count() == 7
