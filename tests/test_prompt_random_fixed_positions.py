"""Tests for prompt.random_fixed_positions module (ticket 14)."""

import pytest

from core.run_context import RunContext
from datatypes import ProteinMPNNConstraints


class TestRandomFixedPositions:
    def test_length_56_fraction_0_5_yields_28(self) -> None:
        from modules.prompt_random_fixed_positions.module import (
            RandomFixedPositionsModule,
        )
        mod = RandomFixedPositionsModule()
        ctx = RunContext("/tmp/test", "n1", seed=42)

        result = mod.run({}, {"length": 56, "fraction": 0.5}, ctx)
        constraints = result["constraints"]

        assert isinstance(constraints, ProteinMPNNConstraints)
        assert constraints.fixed_positions is not None
        assert len(constraints.fixed_positions) == 28

    def test_positions_in_range_no_duplicates(self) -> None:
        from modules.prompt_random_fixed_positions.module import (
            RandomFixedPositionsModule,
        )
        mod = RandomFixedPositionsModule()
        ctx = RunContext("/tmp/test", "n1", seed=42)

        result = mod.run({}, {"length": 56, "fraction": 0.5}, ctx)
        fixed = result["constraints"].fixed_positions

        assert all(0 <= p < 56 for p in fixed)
        assert len(fixed) == len(set(fixed))
        assert fixed == sorted(fixed)

    def test_fraction_zero_empty_list(self) -> None:
        from modules.prompt_random_fixed_positions.module import (
            RandomFixedPositionsModule,
        )
        mod = RandomFixedPositionsModule()
        ctx = RunContext("/tmp/test", "n1", seed=42)

        result = mod.run({}, {"length": 56, "fraction": 0.0}, ctx)
        fixed = result["constraints"].fixed_positions

        assert fixed == []

    def test_fraction_one_all_positions(self) -> None:
        from modules.prompt_random_fixed_positions.module import (
            RandomFixedPositionsModule,
        )
        mod = RandomFixedPositionsModule()
        ctx = RunContext("/tmp/test", "n1", seed=42)

        result = mod.run({}, {"length": 56, "fraction": 1.0}, ctx)
        fixed = result["constraints"].fixed_positions

        assert fixed == list(range(56))

    def test_identical_seed_yields_same_positions(self) -> None:
        from modules.prompt_random_fixed_positions.module import (
            RandomFixedPositionsModule,
        )
        mod = RandomFixedPositionsModule()

        ctx1 = RunContext("/tmp/test", "n1", seed=12345)
        out1 = mod.run({}, {"length": 100, "fraction": 0.3}, ctx1)

        ctx2 = RunContext("/tmp/test", "n2", seed=12345)
        out2 = mod.run({}, {"length": 100, "fraction": 0.3}, ctx2)

        assert out1["constraints"].fixed_positions == out2["constraints"].fixed_positions

    def test_different_seed_yields_different_positions(self) -> None:
        from modules.prompt_random_fixed_positions.module import (
            RandomFixedPositionsModule,
        )
        mod = RandomFixedPositionsModule()

        ctx1 = RunContext("/tmp/test", "n1", seed=1)
        out1 = mod.run({}, {"length": 100, "fraction": 0.3}, ctx1)

        ctx2 = RunContext("/tmp/test", "n1", seed=2)
        out2 = mod.run({}, {"length": 100, "fraction": 0.3}, ctx2)

        assert out1["constraints"].fixed_positions != out2["constraints"].fixed_positions

    def test_fraction_out_of_range_raises(self) -> None:
        from modules.prompt_random_fixed_positions.module import (
            RandomFixedPositionsModule,
        )
        mod = RandomFixedPositionsModule()
        ctx = RunContext("/tmp/test", "n1", seed=42)

        with pytest.raises(ValueError, match="fraction"):
            mod.run({}, {"length": 10, "fraction": 1.5}, ctx)

        with pytest.raises(ValueError, match="fraction"):
            mod.run({}, {"length": 10, "fraction": -0.1}, ctx)

    def test_length_zero_raises(self) -> None:
        from modules.prompt_random_fixed_positions.module import (
            RandomFixedPositionsModule,
        )
        mod = RandomFixedPositionsModule()
        ctx = RunContext("/tmp/test", "n1", seed=42)

        with pytest.raises(ValueError, match="length"):
            mod.run({}, {"length": 0, "fraction": 0.5}, ctx)

    def test_odd_length_truncates(self) -> None:
        from modules.prompt_random_fixed_positions.module import (
            RandomFixedPositionsModule,
        )
        mod = RandomFixedPositionsModule()
        ctx = RunContext("/tmp/test", "n1", seed=42)

        result = mod.run({}, {"length": 7, "fraction": 0.5}, ctx)
        fixed = result["constraints"].fixed_positions

        assert len(fixed) == 3

    def test_other_fields_are_none(self) -> None:
        from modules.prompt_random_fixed_positions.module import (
            RandomFixedPositionsModule,
        )
        mod = RandomFixedPositionsModule()
        ctx = RunContext("/tmp/test", "n1", seed=42)

        result = mod.run({}, {"length": 10, "fraction": 0.3}, ctx)
        c = result["constraints"]

        assert c.designable_positions is None
        assert c.omit_amino_acids is None
        assert c.tied_positions is None
        assert c.designed_chains is None
        assert c.fixed_chains is None
