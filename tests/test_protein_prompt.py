"""Tests for ProteinPrompt editor modules (ticket 05)."""

import json
import tempfile
from pathlib import Path

from core.run_context import RunContext
from datatypes import (
    FunctionAnnotations,
    ProteinPrompt,
    ProteinStructure,
    ResidueLayout,
    ResidueMap,
    ResidueTrack,
)

# ── Sample PDB for testing ──────────────────────────────────────────

SAMPLE_PDB = """\
ATOM      1  N   ALA A   1       0.000   0.000   0.000  1.00  0.00           N
ATOM      2  CA  ALA A   1       1.458   0.000   0.000  1.00  0.00           C
ATOM      3  C   ALA A   1       2.009   1.421   0.000  1.00  0.00           C
ATOM      4  O   ALA A   1       1.223   2.371   0.000  1.00  0.00           O
ATOM      5  N   GLY A   2       3.309   1.681   0.000  1.00  0.00           N
ATOM      6  CA  GLY A   2       3.909   3.009   0.000  1.00  0.00           C
ATOM      7  C   GLY A   2       3.309   4.309   0.000  1.00  0.00           C
ATOM      8  O   GLY A   2       2.109   4.409   0.000  1.00  0.00           O
ATOM      9  N   SER A   3       4.109   5.309   0.000  1.00  0.00           N
ATOM     10  CA  SER A   3       3.609   6.609   0.000  1.00  0.00           C
ATOM     11  C   SER A   3       2.509   7.109   0.000  1.00  0.00           C
ATOM     12  O   SER A   3       1.509   6.409   0.000  1.00  0.00           O
END
"""

MULTI_CHAIN_PDB = """\
ATOM      1  N   ALA A   1       0.000   0.000   0.000  1.00  0.00           N
ATOM      2  CA  ALA A   1       1.458   0.000   0.000  1.00  0.00           C
ATOM      3  N   GLY B   1       2.000   2.000   0.000  1.00  0.00           N
ATOM      4  CA  GLY B   1       3.000   2.000   0.000  1.00  0.00           C
END
"""


# ── Build Residue Layout ────────────────────────────────────────────

class TestBuildResidueLayout:
    def test_creates_layout_with_defaults(self) -> None:
        from modules.build_residue_layout.module import BuildResidueLayoutModule
        mod = BuildResidueLayoutModule()
        ctx = RunContext("/tmp/test", "n1")
        result = mod.run({}, {}, ctx)
        layout = result["layout"]
        assert isinstance(layout, ResidueLayout)
        assert layout.chain_id == "A"
        assert layout.length == 1

    def test_custom_chain_and_length(self) -> None:
        from modules.build_residue_layout.module import BuildResidueLayoutModule
        mod = BuildResidueLayoutModule()
        ctx = RunContext("/tmp/test", "n1")
        result = mod.run({}, {"chain_id": "B", "length": 42}, ctx)
        layout = result["layout"]
        assert layout.chain_id == "B"
        assert layout.length == 42

    def test_definition_is_valid(self) -> None:
        from modules.build_residue_layout.module import BuildResidueLayoutModule
        mod = BuildResidueLayoutModule()
        d = mod.definition
        assert d.module_id == "prompt.build_residue_layout"
        assert d.category == "prompt"
        assert len(d.output_ports) == 1
        assert d.output_ports[0].type_id == "residue.layout"


# ── Apply Residue Edits ─────────────────────────────────────────────

class TestApplyResidueEdits:
    def test_basic_mapping_same_length(self) -> None:
        from modules.apply_residue_edits.module import ApplyResidueEditsModule
        mod = ApplyResidueEditsModule()
        ctx = RunContext("/tmp/test", "n1")
        ps = ProteinStructure(pdb_string=SAMPLE_PDB)
        layout = ResidueLayout(chain_id="A", length=3)
        result = mod.run(
            {"template_structure": ps, "target_layout": layout},
            {"edits": "[]"},
            ctx,
        )
        seq = result["sequence_track"]
        struct = result["structure_track"]
        vis = result["visibility_track"]
        rmap = result["residue_map"]
        assert isinstance(seq, ResidueTrack)
        assert isinstance(struct, ResidueTrack)
        assert isinstance(vis, ResidueTrack)
        assert isinstance(rmap, ResidueMap)
        assert len(seq) == 3
        assert seq.values == ["A", "G", "S"]
        assert len(struct) == 3
        # All 3 residues have CA atoms
        assert struct.values[0] is not None
        assert vis.values == [True, True, True]
        assert rmap.source_layout.length == 3
        assert rmap.target_layout.length == 3

    def test_set_edit_changes_amino_acid(self) -> None:
        from modules.apply_residue_edits.module import ApplyResidueEditsModule
        mod = ApplyResidueEditsModule()
        ctx = RunContext("/tmp/test", "n1")
        ps = ProteinStructure(pdb_string=SAMPLE_PDB)
        layout = ResidueLayout(chain_id="A", length=3)
        edits = json.dumps([{"op": "set", "position": 1, "value": "W"}])
        result = mod.run(
            {"template_structure": ps, "target_layout": layout},
            {"edits": edits},
            ctx,
        )
        seq = result["sequence_track"]
        assert seq.values == ["A", "W", "S"]

    def test_mask_edit_unsets_residue(self) -> None:
        from modules.apply_residue_edits.module import ApplyResidueEditsModule
        mod = ApplyResidueEditsModule()
        ctx = RunContext("/tmp/test", "n1")
        ps = ProteinStructure(pdb_string=SAMPLE_PDB)
        layout = ResidueLayout(chain_id="A", length=3)
        edits = json.dumps([{"op": "mask", "position": 0}])
        result = mod.run(
            {"template_structure": ps, "target_layout": layout},
            {"edits": edits},
            ctx,
        )
        seq = result["sequence_track"]
        assert seq.values[0] is None
        assert seq.values[1] == "G"

    def test_insert_increases_length(self) -> None:
        from modules.apply_residue_edits.module import ApplyResidueEditsModule
        mod = ApplyResidueEditsModule()
        ctx = RunContext("/tmp/test", "n1")
        ps = ProteinStructure(pdb_string=SAMPLE_PDB)
        layout = ResidueLayout(chain_id="A", length=3)
        edits = json.dumps([{"op": "insert", "position": 1, "value": "K"}])
        result = mod.run(
            {"template_structure": ps, "target_layout": layout},
            {"edits": edits},
            ctx,
        )
        seq = result["sequence_track"]
        assert len(seq) == 4
        assert seq.values[0] == "A"
        assert seq.values[1] == "K"
        assert seq.values[2] == "G"
        assert seq.values[3] == "S"

    def test_delete_decreases_length(self) -> None:
        from modules.apply_residue_edits.module import ApplyResidueEditsModule
        mod = ApplyResidueEditsModule()
        ctx = RunContext("/tmp/test", "n1")
        ps = ProteinStructure(pdb_string=SAMPLE_PDB)
        layout = ResidueLayout(chain_id="A", length=3)
        edits = json.dumps([{"op": "delete", "position": 1}])
        result = mod.run(
            {"template_structure": ps, "target_layout": layout},
            {"edits": edits},
            ctx,
        )
        seq = result["sequence_track"]
        assert len(seq) == 2
        assert seq.values == ["A", "S"]

    def test_extra_target_positions_are_inserts(self) -> None:
        from modules.apply_residue_edits.module import ApplyResidueEditsModule
        mod = ApplyResidueEditsModule()
        ctx = RunContext("/tmp/test", "n1")
        ps = ProteinStructure(pdb_string=SAMPLE_PDB)
        layout = ResidueLayout(chain_id="A", length=5)  # template has 3
        result = mod.run(
            {"template_structure": ps, "target_layout": layout},
            {"edits": "[]"},
            ctx,
        )
        seq = result["sequence_track"]
        assert len(seq) == 5
        assert seq.values[0] == "A"
        assert seq.values[1] == "G"
        assert seq.values[2] == "S"
        assert seq.values[3] is None  # inserted
        assert seq.values[4] is None  # inserted

    def test_extra_template_residues_are_deleted(self) -> None:
        from modules.apply_residue_edits.module import ApplyResidueEditsModule
        mod = ApplyResidueEditsModule()
        ctx = RunContext("/tmp/test", "n1")
        ps = ProteinStructure(pdb_string=SAMPLE_PDB)
        layout = ResidueLayout(chain_id="A", length=1)
        result = mod.run(
            {"template_structure": ps, "target_layout": layout},
            {"edits": "[]"},
            ctx,
        )
        seq = result["sequence_track"]
        assert len(seq) == 1
        assert seq.values[0] == "A"
        # Residues 2,3 should be mapped as delete
        rmap = result["residue_map"]
        delete_ops = [m for m in rmap.mappings if m[2] == "delete"]
        assert len(delete_ops) == 2

    def test_filter_by_chain(self) -> None:
        from modules.apply_residue_edits.module import ApplyResidueEditsModule
        mod = ApplyResidueEditsModule()
        ctx = RunContext("/tmp/test", "n1")
        ps = ProteinStructure(pdb_string=MULTI_CHAIN_PDB)
        layout = ResidueLayout(chain_id="B", length=1)
        result = mod.run(
            {"template_structure": ps, "target_layout": layout},
            {"edits": "[]"},
            ctx,
        )
        seq = result["sequence_track"]
        assert seq.values == ["G"]

    def test_missing_template_raises(self) -> None:
        from modules.apply_residue_edits.module import ApplyResidueEditsModule
        mod = ApplyResidueEditsModule()
        ctx = RunContext("/tmp/test", "n1")
        try:
            mod.run({}, {}, ctx)
            assert False, "should have raised"
        except ValueError as e:
            assert "template_structure" in str(e)

    def test_missing_layout_raises(self) -> None:
        from modules.apply_residue_edits.module import ApplyResidueEditsModule
        mod = ApplyResidueEditsModule()
        ctx = RunContext("/tmp/test", "n1")
        ps = ProteinStructure(pdb_string=SAMPLE_PDB)
        try:
            mod.run({"template_structure": ps}, {}, ctx)
            assert False, "should have raised"
        except ValueError as e:
            assert "target_layout" in str(e)


# ── Compute Secondary Structure ─────────────────────────────────────

class TestComputeSecondaryStructure:
    def test_dssp_parse_known_format(self) -> None:
        from modules.compute_secondary_structure.module import _parse_dssp_mmcif
        dssp_text = """\
loop_
_dssp_struct_summary.entry_id
_dssp_struct_summary.label_asym_id
_dssp_struct_summary.label_seq_id
_dssp_struct_summary.label_comp_id
_dssp_struct_summary.secondary_structure
_dssp_struct_summary.accessibility
nohd A 1 ALA H 100
nohd A 2 GLY E 50
nohd A 3 SER - 75
"""
        ss_codes, sasa_values = _parse_dssp_mmcif(dssp_text)
        assert ss_codes == ["H", "E", "-"]
        assert sasa_values == [100.0, 50.0, 75.0]

    def test_runs_mkdssp_on_sample_pdb(self) -> None:
        from modules.compute_secondary_structure.module import (
            ComputeSecondaryStructureModule,
        )
        mod = ComputeSecondaryStructureModule()
        ctx = RunContext("/tmp/test", "n1")
        ps = ProteinStructure(pdb_string=SAMPLE_PDB)
        result = mod.run({"structure": ps}, {}, ctx)
        track = result["secondary_structure_track"]
        assert isinstance(track, ResidueTrack)
        assert len(track) == 3
        # All values should be valid DSSP codes or "-"
        for v in track.values:
            assert v in ("H", "B", "E", "G", "I", "T", "S", "-")

    def test_missing_structure_raises(self) -> None:
        from modules.compute_secondary_structure.module import (
            ComputeSecondaryStructureModule,
        )
        mod = ComputeSecondaryStructureModule()
        ctx = RunContext("/tmp/test", "n1")
        try:
            mod.run({}, {}, ctx)
            assert False, "should have raised"
        except ValueError as e:
            assert "structure" in str(e)


# ── Compute SASA ────────────────────────────────────────────────────

class TestComputeSASA:
    def test_dssp_sasa_parse(self) -> None:
        from modules.compute_sasa.module import _parse_dssp_mmcif
        dssp_text = """\
loop_
_dssp_struct_summary.entry_id
_dssp_struct_summary.label_asym_id
_dssp_struct_summary.label_seq_id
_dssp_struct_summary.label_comp_id
_dssp_struct_summary.secondary_structure
_dssp_struct_summary.accessibility
nohd A 1 ALA H 100
nohd A 2 GLY E 50
nohd A 3 SER - 75
"""
        ss_codes, sasa_values = _parse_dssp_mmcif(dssp_text)
        assert sasa_values == [100.0, 50.0, 75.0]

    def test_runs_mkdssp_on_sample_pdb(self) -> None:
        from modules.compute_sasa.module import ComputeSASAModule
        mod = ComputeSASAModule()
        ctx = RunContext("/tmp/test", "n1")
        ps = ProteinStructure(pdb_string=SAMPLE_PDB)
        result = mod.run({"structure": ps}, {}, ctx)
        track = result["sasa_track"]
        assert isinstance(track, ResidueTrack)
        assert len(track) == 3
        for v in track.values:
            assert isinstance(v, float)
            assert v >= 0.0

    def test_missing_structure_raises(self) -> None:
        from modules.compute_sasa.module import ComputeSASAModule
        mod = ComputeSASAModule()
        ctx = RunContext("/tmp/test", "n1")
        try:
            mod.run({}, {}, ctx)
            assert False, "should have raised"
        except ValueError as e:
            assert "structure" in str(e)


# ── Override Residue Track ──────────────────────────────────────────

class TestOverrideResidueTrack:
    def test_overrides_positions(self) -> None:
        from modules.override_residue_track.module import OverrideResidueTrackModule
        mod = OverrideResidueTrackModule()
        ctx = RunContext("/tmp/test", "n1")
        track = ResidueTrack(values=["A", "B", "C"], sentinel=None)
        overrides = json.dumps([{"position": 1, "value": "X"}])
        result = mod.run({"track_input": track}, {"overrides": overrides}, ctx)
        out = result["track_output"]
        assert out.values == ["A", "X", "C"]

    def test_override_out_of_range_raises(self) -> None:
        from modules.override_residue_track.module import OverrideResidueTrackModule
        mod = OverrideResidueTrackModule()
        ctx = RunContext("/tmp/test", "n1")
        track = ResidueTrack(values=["A"], sentinel=None)
        overrides = json.dumps([{"position": 5, "value": "X"}])
        try:
            mod.run({"track_input": track}, {"overrides": overrides}, ctx)
            assert False, "should have raised"
        except ValueError:
            pass

    def test_missing_track_raises(self) -> None:
        from modules.override_residue_track.module import OverrideResidueTrackModule
        mod = OverrideResidueTrackModule()
        ctx = RunContext("/tmp/test", "n1")
        try:
            mod.run({}, {}, ctx)
            assert False, "should have raised"
        except ValueError as e:
            assert "track_input" in str(e)


# ── Add Function Annotation ─────────────────────────────────────────

class TestAddFunctionAnnotation:
    def test_adds_to_empty(self) -> None:
        from modules.add_function_annotation.module import AddFunctionAnnotationModule
        mod = AddFunctionAnnotationModule()
        ctx = RunContext("/tmp/test", "n1")
        result = mod.run(
            {},
            {"label": "active_site", "start": 10, "end": 25},
            ctx,
        )
        fa = result["updated_annotations"]
        assert isinstance(fa, FunctionAnnotations)
        assert len(fa) == 1
        assert fa.annotations[0]["label"] == "active_site"
        assert fa.annotations[0]["start"] == 10
        assert fa.annotations[0]["end"] == 25

    def test_adds_to_existing(self) -> None:
        from modules.add_function_annotation.module import AddFunctionAnnotationModule
        mod = AddFunctionAnnotationModule()
        ctx = RunContext("/tmp/test", "n1")
        existing = FunctionAnnotations()
        existing.add("binding", 5, 15)
        result = mod.run(
            {"existing_annotations": existing},
            {"label": "catalytic", "start": 20, "end": 30},
            ctx,
        )
        fa = result["updated_annotations"]
        assert len(fa) == 2
        assert fa.annotations[0]["label"] == "binding"
        assert fa.annotations[1]["label"] == "catalytic"

    def test_empty_label_adds_nothing(self) -> None:
        from modules.add_function_annotation.module import AddFunctionAnnotationModule
        mod = AddFunctionAnnotationModule()
        ctx = RunContext("/tmp/test", "n1")
        result = mod.run({}, {"label": "", "start": 1, "end": 1}, ctx)
        fa = result["updated_annotations"]
        assert len(fa) == 0


# ── Assemble ProteinPrompt ──────────────────────────────────────────

class TestAssembleProteinPrompt:
    def test_assembles_all_tracks(self) -> None:
        from modules.assemble_protein_prompt.module import AssembleProteinPromptModule
        mod = AssembleProteinPromptModule()
        ctx = RunContext("/tmp/test", "n1")
        layout = ResidueLayout(chain_id="A", length=3)
        result = mod.run(
            {
                "layout": layout,
                "sequence_track": ResidueTrack(values=["A", "G", "S"], sentinel=None),
                "structure_track": ResidueTrack(values=[(1,2,3),(4,5,6),(7,8,9)], sentinel=None),
                "visibility_track": ResidueTrack(values=[True, True, False], sentinel=None),
                "secondary_structure_track": ResidueTrack(values=["H", "E", "-"], sentinel=None),
                "sasa_track": ResidueTrack(values=[50.0, 75.0, 100.0], sentinel=None),
                "function_annotations": FunctionAnnotations(),
            },
            {},
            ctx,
        )
        prompt = result["protein_prompt"]
        assert isinstance(prompt, ProteinPrompt)
        assert prompt.target_layout == layout
        assert prompt.sequence_track is not None
        assert len(prompt.sequence_track) == 3
        assert prompt.structure_visibility_track is not None
        assert prompt.structure_visibility_track.values == [True, True, False]
        assert prompt.num_residues == 3

    def test_rejects_mismatched_track_length(self) -> None:
        from modules.assemble_protein_prompt.module import AssembleProteinPromptModule
        mod = AssembleProteinPromptModule()
        ctx = RunContext("/tmp/test", "n1")
        layout = ResidueLayout(chain_id="A", length=3)
        bad_track = ResidueTrack(values=["A", "G"], sentinel=None)  # length 2
        try:
            mod.run(
                {
                    "layout": layout,
                    "sequence_track": bad_track,
                },
                {},
                ctx,
            )
            assert False, "should have raised"
        except ValueError as e:
            assert "length" in str(e)

    def test_missing_layout_raises(self) -> None:
        from modules.assemble_protein_prompt.module import AssembleProteinPromptModule
        mod = AssembleProteinPromptModule()
        ctx = RunContext("/tmp/test", "n1")
        try:
            mod.run({}, {}, ctx)
            assert False, "should have raised"
        except ValueError as e:
            assert "layout" in str(e)

    def test_partial_tracks_allowed(self) -> None:
        """Assemble should work with only a subset of tracks provided."""
        from modules.assemble_protein_prompt.module import AssembleProteinPromptModule
        mod = AssembleProteinPromptModule()
        ctx = RunContext("/tmp/test", "n1")
        layout = ResidueLayout(chain_id="A", length=2)
        result = mod.run(
            {"layout": layout},
            {},
            ctx,
        )
        prompt = result["protein_prompt"]
        assert prompt.sequence_track is None
        assert prompt.structure_track is None

    def test_applies_function_annotations(self) -> None:
        from modules.assemble_protein_prompt.module import AssembleProteinPromptModule
        mod = AssembleProteinPromptModule()
        ctx = RunContext("/tmp/test", "n1")
        layout = ResidueLayout(chain_id="A", length=3)
        fa = FunctionAnnotations()
        fa.add("site", 1, 10)
        result = mod.run(
            {"layout": layout, "function_annotations": fa},
            {},
            ctx,
        )
        prompt = result["protein_prompt"]
        assert len(prompt.function_annotations) == 1


# ── Track Independence ──────────────────────────────────────────────

class TestTrackIndependence:
    """Sequence and structure visibility tracks are fully independent."""

    def test_changing_sequence_does_not_affect_visibility(self) -> None:
        from modules.apply_residue_edits.module import ApplyResidueEditsModule
        mod = ApplyResidueEditsModule()
        ctx = RunContext("/tmp/test", "n1")
        ps = ProteinStructure(pdb_string=SAMPLE_PDB)
        layout = ResidueLayout(chain_id="A", length=3)
        edits = json.dumps([{"op": "set", "position": 0, "value": "W"}])
        result = mod.run(
            {"template_structure": ps, "target_layout": layout},
            {"edits": edits},
            ctx,
        )
        seq = result["sequence_track"]
        vis = result["visibility_track"]
        assert seq.values[0] == "W"
        # Visibility should be unchanged
        assert vis.values[0] is True
        assert vis.values[1] is True
        assert vis.values[2] is True


# ── Module Discovery Integration ────────────────────────────────────

class TestModuleDiscovery:
    def test_all_40_modules_discoverable(self) -> None:
        from core import TypeRegistry, ModuleRegistry, discover_modules
        tr = TypeRegistry()
        mr = ModuleRegistry(tr)
        discover_modules(mr)
        module_ids = {m.module_id for m in mr.list_all()}
        expected = {
            "stub.echo",
            "import.structure", "import.sequence",
            "export.structure", "export.sequence",
            "prompt.build_residue_layout",
            "prompt.apply_residue_edits",
            "prompt.compute_secondary_structure",
            "prompt.compute_sasa",
            "prompt.override_residue_track",
            "prompt.add_function_annotation",
            "prompt.assemble_protein_prompt",
            "prompt.random_mask",
            "prompt.random_insert_masked",
            "esm3.generate_sequence",
            "esm3.update_prompt_sequence",
            "esm3.generate_structure",
            "proteinmpnn.design",
            "proteinmpnn.score",
            "proteinmpnn.constraints",
            "esmfold2.fold",
            "simplefold.fold",
            "simplefold.evaluate",
            "structure.align",
            "structure.tm_score",
            "structure.rmsd",
            "compute.dssp",
            "scoring.ss_agreement",
            "scoring.aggregate_confidence",
            "scoring.merge",
            "selection.filter",
            "selection.sort",
            "selection.top_k",
            "selection.weighted_rank",
            "selection.pareto",
            "selection.diversity",
            "convert.extract_sequence",
            "convert.extract_backbone",
            "convert.select_chains",
            "convert.map_track",
        }
        assert module_ids == expected

    def test_all_16_types_registered(self) -> None:
        from core import TypeRegistry, ModuleRegistry, discover_modules
        tr = TypeRegistry()
        mr = ModuleRegistry(tr)
        discover_modules(mr)
        types = set(tr.list_all())
        expected = {
            "text",
            "protein.sequence", "protein.structure",
            "residue.layout", "residue.map", "residue.track",
            "residue.track.secondary_structure", "residue.track.sasa",
            "function.annotations", "protein.prompt",
            "candidate.collection", "score.collection",
            "proteinmpnn.constraints",
            "structure.alignment",
        }
        assert types == expected
