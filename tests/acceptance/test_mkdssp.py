"""Acceptance: mkdssp secondary structure computation (local)."""

import pytest

from datatypes import ProteinStructure, ResidueTrack
from tests.acceptance.conftest import require_ready

VALID_DSSP_CODES = {"H", "B", "E", "G", "I", "T", "S", "-", " "}


@pytest.mark.acceptance
class TestMKDSSP:
    def test_dssp_3gb1(self, readiness, pdb_3gb1):
        require_ready("mkdssp", readiness)

        from modules.compute_dssp.module import ComputeDSSPModule
        from core.run_context import RunContext

        mod = ComputeDSSPModule()
        ctx = RunContext("/tmp/acceptance-test", "n1")
        result = mod.run({"structure": pdb_3gb1}, {}, ctx)

        track = result["secondary_structure_track"]
        assert isinstance(track, ResidueTrack)
        assert len(track) == 56
        for code in track.values:
            assert code in VALID_DSSP_CODES, f"Invalid DSSP code: {code}"

    def test_dssp_1pga(self, readiness, pdb_1pga):
        require_ready("mkdssp", readiness)

        from modules.compute_dssp.module import ComputeDSSPModule
        from core.run_context import RunContext

        mod = ComputeDSSPModule()
        ctx = RunContext("/tmp/acceptance-test", "n1")
        result = mod.run({"structure": pdb_1pga}, {}, ctx)

        track = result["secondary_structure_track"]
        assert isinstance(track, ResidueTrack)
        assert len(track) == 75
        for code in track.values:
            assert code in VALID_DSSP_CODES, f"Invalid DSSP code: {code}"
