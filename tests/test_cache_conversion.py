"""Tests for cache, cancellation, conversion modules (ticket 11)."""

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from core.run_context import RunContext
from datatypes import (
    Candidate,
    CandidateCollection,
    ProteinSequence,
    ProteinStructure,
    ResidueLayout,
    ResidueMap,
    ResidueTrack,
    Score,
    ScoreCollection,
)

SAMPLE_PDB = """\
ATOM      1  N   ALA A   1       0.000   0.000   0.000  1.00  0.00           N
ATOM      2  CA  ALA A   1       1.458   0.000   0.000  1.00  0.00           C
ATOM      3  C   ALA A   1       2.009   1.421   0.000  1.00  0.00           C
ATOM      4  O   ALA A   1       1.223   2.371   0.000  1.00  0.00           O
ATOM      5  CB  ALA A   1       2.009  -0.710   1.229  1.00  0.00           C
ATOM      6  N   GLY A   2       3.309   1.681   0.000  1.00  0.00           N
ATOM      7  CA  GLY A   2       3.909   3.009   0.000  1.00  0.00           C
ATOM      8  C   GLY A   2       3.309   4.309   0.000  1.00  0.00           C
ATOM      9  O   GLY A   2       2.109   4.409   0.000  1.00  0.00           O
ATOM     10  N   SER A   3       4.109   5.309   0.000  1.00  0.00           N
ATOM     11  CA  SER A   3       3.609   6.609   0.000  1.00  0.00           C
ATOM     12  C   SER A   3       2.509   7.109   0.000  1.00  0.00           C
ATOM     13  O   SER A   3       1.509   6.409   0.000  1.00  0.00           O
END
"""

MULTI_CHAIN_PDB = """\
ATOM      1  N   ALA A   1       0.000   0.000   0.000  1.00  0.00           N
ATOM      2  CA  ALA A   1       1.458   0.000   0.000  1.00  0.00           C
ATOM      3  N   GLY B   1       2.000   2.000   0.000  1.00  0.00           N
ATOM      4  CA  GLY B   1       3.000   2.000   0.000  1.00  0.00           C
END
"""


# ── Cache Tests ───────────────────────────────────────────────────────

class TestCache:
    def test_cache_key_changes_with_input(self) -> None:
        from core.executor import Executor
        ex = Executor()
        key1 = ex._compute_cache_key("test", "1.0", {"x": 1}, {"p": 2}, 42)
        key2 = ex._compute_cache_key("test", "1.0", {"x": 2}, {"p": 2}, 42)
        assert key1 != key2

    def test_cache_key_changes_with_seed(self) -> None:
        from core.executor import Executor
        ex = Executor()
        key1 = ex._compute_cache_key("test", "1.0", {}, {}, 42)
        key2 = ex._compute_cache_key("test", "1.0", {}, {}, 43)
        assert key1 != key2

    def test_cache_key_deterministic(self) -> None:
        from core.executor import Executor
        ex = Executor()
        key1 = ex._compute_cache_key("test", "1.0", {"a": 1, "b": 2}, {"z": 3}, 42)
        key2 = ex._compute_cache_key("test", "1.0", {"b": 2, "a": 1}, {"z": 3}, 42)
        assert key1 == key2  # sorted keys ensure deterministic hash

    def test_cache_save_and_load_round_trip(self) -> None:
        from core.executor import Executor
        ex = Executor()
        with tempfile.TemporaryDirectory() as tmpdir:
            path = ex._get_cache_path(tmpdir, "node1", "abc123")
            data = {"out": 42, "text": "hello"}
            ex._save_to_cache(path, data)
            loaded = ex._load_from_cache(path)
            assert loaded == data

    def test_cache_miss_on_nonexistent(self) -> None:
        from core.executor import Executor
        ex = Executor()
        with tempfile.TemporaryDirectory() as tmpdir:
            path = ex._get_cache_path(tmpdir, "node1", "no-such-key")
            assert ex._load_from_cache(path) is None


# ── Extract Sequence from Structure ───────────────────────────────────

class TestExtractSequence:
    def test_extracts_from_3_residue_pdb(self) -> None:
        from modules.extract_sequence_from_structure.module import (
            ExtractSequenceFromStructureModule,
        )
        mod = ExtractSequenceFromStructureModule()
        ctx = RunContext("/tmp/test", "n1")
        struct = ProteinStructure(pdb_string=SAMPLE_PDB)
        result = mod.run({"structure": struct}, {}, ctx)
        seq = result["sequence"]
        assert isinstance(seq, ProteinSequence)
        assert seq.sequence == "AGS"

    def test_missing_structure_raises(self) -> None:
        from modules.extract_sequence_from_structure.module import (
            ExtractSequenceFromStructureModule,
        )
        mod = ExtractSequenceFromStructureModule()
        ctx = RunContext("/tmp/test", "n1")
        with pytest.raises(ValueError, match="structure"):
            mod.run({}, {}, ctx)

    def test_empty_pdb_raises(self) -> None:
        from modules.extract_sequence_from_structure.module import (
            ExtractSequenceFromStructureModule,
        )
        mod = ExtractSequenceFromStructureModule()
        ctx = RunContext("/tmp/test", "n1")
        empty = ProteinStructure(pdb_string="HEADER EMPTY\nEND\n")
        with pytest.raises(ValueError, match="No amino acid"):
            mod.run({"structure": empty}, {}, ctx)


# ── Extract Backbone ──────────────────────────────────────────────────

class TestExtractBackbone:
    def test_keeps_only_backbone_atoms(self) -> None:
        from modules.extract_backbone.module import ExtractBackboneModule
        mod = ExtractBackboneModule()
        ctx = RunContext("/tmp/test", "n1")
        struct = ProteinStructure(pdb_string=SAMPLE_PDB)
        result = mod.run({"structure": struct}, {}, ctx)
        bb = result["structure"]
        assert isinstance(bb, ProteinStructure)
        lines = [l for l in bb.pdb_string.splitlines() if l.startswith("ATOM")]
        for line in lines:
            atom_name = line[12:16].strip()
            assert atom_name in {"N", "CA", "C", "O"}

    def test_removes_side_chain_cb(self) -> None:
        from modules.extract_backbone.module import ExtractBackboneModule
        mod = ExtractBackboneModule()
        ctx = RunContext("/tmp/test", "n1")
        struct = ProteinStructure(pdb_string=SAMPLE_PDB)
        result = mod.run({"structure": struct}, {}, ctx)
        bb_str = result["structure"].pdb_string
        # CB should not be present
        assert "CB " not in bb_str or " CB " not in bb_str

    def test_missing_structure_raises(self) -> None:
        from modules.extract_backbone.module import ExtractBackboneModule
        mod = ExtractBackboneModule()
        ctx = RunContext("/tmp/test", "n1")
        with pytest.raises(ValueError, match="structure"):
            mod.run({}, {}, ctx)


# ── Select Chains ─────────────────────────────────────────────────────

class TestSelectChains:
    def test_filters_to_specified_chain(self) -> None:
        from modules.select_chains.module import SelectChainsModule
        mod = SelectChainsModule()
        ctx = RunContext("/tmp/test", "n1")
        struct = ProteinStructure(pdb_string=MULTI_CHAIN_PDB)
        result = mod.run(
            {"structure": struct},
            {"chains": json.dumps(["A"])},
            ctx,
        )
        filtered = result["structure"]
        lines = [l for l in filtered.pdb_string.splitlines() if l.startswith("ATOM")]
        for line in lines:
            chain = line[21:22].strip()
            assert chain == "A"

    def test_selects_multiple_chains(self) -> None:
        from modules.select_chains.module import SelectChainsModule
        mod = SelectChainsModule()
        ctx = RunContext("/tmp/test", "n1")
        struct = ProteinStructure(pdb_string=MULTI_CHAIN_PDB)
        result = mod.run(
            {"structure": struct},
            {"chains": json.dumps(["A", "B"])},
            ctx,
        )
        filtered = result["structure"]
        lines = [l for l in filtered.pdb_string.splitlines() if l.startswith("ATOM")]
        chains = {l[21:22].strip() for l in lines}
        assert chains == {"A", "B"}

    def test_no_matching_chain_raises(self) -> None:
        from modules.select_chains.module import SelectChainsModule
        mod = SelectChainsModule()
        ctx = RunContext("/tmp/test", "n1")
        struct = ProteinStructure(pdb_string=MULTI_CHAIN_PDB)
        with pytest.raises(ValueError, match="No atoms found"):
            mod.run(
                {"structure": struct},
                {"chains": json.dumps(["C"])},
                ctx,
            )

    def test_empty_chains_raises(self) -> None:
        from modules.select_chains.module import SelectChainsModule
        mod = SelectChainsModule()
        ctx = RunContext("/tmp/test", "n1")
        struct = ProteinStructure(pdb_string=MULTI_CHAIN_PDB)
        with pytest.raises(ValueError, match="At least one chain"):
            mod.run({"structure": struct}, {"chains": "[]"}, ctx)


# ── Map Residue Track ─────────────────────────────────────────────────

class TestMapResidueTrack:
    def test_remaps_match_operations(self) -> None:
        from modules.map_residue_track.module import MapResidueTrackModule
        mod = MapResidueTrackModule()
        ctx = RunContext("/tmp/test", "n1")

        src_layout = ResidueLayout(chain_id="A", length=3)
        tgt_layout = ResidueLayout(chain_id="A", length=3)
        rmap = ResidueMap(
            source_layout=src_layout,
            target_layout=tgt_layout,
            mappings=[(0, 0, "match"), (1, 1, "match"), (2, 2, "match")],
        )
        track = ResidueTrack(values=["H", "E", "-"], sentinel=None)

        result = mod.run({"track": track, "residue_map": rmap}, {}, ctx)
        mapped = result["track"]
        assert mapped.values == ["H", "E", "-"]

    def test_handles_insert_and_delete(self) -> None:
        from modules.map_residue_track.module import MapResidueTrackModule
        mod = MapResidueTrackModule()
        ctx = RunContext("/tmp/test", "n1")

        src_layout = ResidueLayout(chain_id="A", length=2)
        tgt_layout = ResidueLayout(chain_id="A", length=3)
        rmap = ResidueMap(
            source_layout=src_layout,
            target_layout=tgt_layout,
            mappings=[
                (0, 0, "match"),
                (0, 1, "insert"),
                (1, 2, "match"),
            ],
        )
        track = ResidueTrack(values=["H", "E"], sentinel=None)

        result = mod.run({"track": track, "residue_map": rmap}, {}, ctx)
        mapped = result["track"]
        assert mapped.values == ["H", None, "E"]  # insert gives None sentinel

    def test_missing_inputs_raises(self) -> None:
        from modules.map_residue_track.module import MapResidueTrackModule
        mod = MapResidueTrackModule()
        ctx = RunContext("/tmp/test", "n1")
        with pytest.raises(ValueError, match="track"):
            mod.run({}, {}, ctx)
        track = ResidueTrack(values=["H"], sentinel=None)
        with pytest.raises(ValueError, match="residue_map"):
            mod.run({"track": track}, {}, ctx)
