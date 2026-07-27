"""Tests for Import/Export modules."""

import tempfile
from pathlib import Path

from core.run_context import RunContext
from modules.import_structure.module import ImportStructureModule
from modules.import_sequence.module import ImportSequenceModule
from modules.export_structure.module import ExportStructureModule
from modules.export_sequence.module import ExportSequenceModule
from datatypes import (
    Candidate,
    CandidateCollection,
    ProteinSequence,
    ProteinStructure,
)


SAMPLE_PDB = """\
ATOM      1  N   ALA A   1       0.000   0.000   0.000  1.00  0.00           N
ATOM      2  CA  ALA A   1       1.458   0.000   0.000  1.00  0.00           C
ATOM      3  C   ALA A   1       2.009   1.421   0.000  1.00  0.00           C
ATOM      4  O   ALA A   1       1.223   2.371   0.000  1.00  0.00           O
END
"""

SAMPLE_FASTA = """>test_sequence
MKFLILFNILVSTLAFLVSS
>secondary header  
YQIPRADKHG"""


class TestImportStructure:
    def test_reads_pdb_produces_structure(self) -> None:
        with tempfile.TemporaryDirectory() as project_dir:
            input_path = Path(project_dir) / "inputs" / "source.pdb"
            input_path.parent.mkdir()
            input_path.write_text(SAMPLE_PDB)
            mod = ImportStructureModule()
            ctx = RunContext(project_dir, "n1")
            result = mod.run({}, {"file_path": str(input_path)}, ctx)
            ps = result["structure"]
            assert isinstance(ps, ProteinStructure)
            assert "ATOM" in ps.pdb_string
            assert "END" in ps.pdb_string

    def test_missing_file_path_raises(self) -> None:
        mod = ImportStructureModule()
        ctx = RunContext("/tmp/test", "n1")
        try:
            mod.run({}, {}, ctx)
            assert False, "should have raised"
        except ValueError as e:
            assert "file_path" in str(e)


class TestImportSequence:
    def test_reads_fasta_produces_sequence(self) -> None:
        with tempfile.TemporaryDirectory() as project_dir:
            input_path = Path(project_dir) / "inputs" / "source.fasta"
            input_path.parent.mkdir()
            input_path.write_text(SAMPLE_FASTA)
            mod = ImportSequenceModule()
            ctx = RunContext(project_dir, "n1")
            result = mod.run({}, {"file_path": str(input_path)}, ctx)
            ps = result["sequence"]
            assert isinstance(ps, ProteinSequence)
            assert ps.sequence == "MKFLILFNILVSTLAFLVSSYQIPRADKHG"

    def test_ignores_fasta_headers(self) -> None:
        with tempfile.TemporaryDirectory() as project_dir:
            input_path = Path(project_dir) / "inputs" / "source.fasta"
            input_path.parent.mkdir()
            input_path.write_text(">header line\nAAAA\n")
            mod = ImportSequenceModule()
            ctx = RunContext(project_dir, "n1")
            result = mod.run({}, {"file_path": str(input_path)}, ctx)
            assert result["sequence"].sequence == "AAAA"


class TestExportStructure:
    def test_round_trip_pdb_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            mod = ExportStructureModule()
            ps = ProteinStructure(pdb_string=SAMPLE_PDB)
            ctx = RunContext(tmp, "n1")
            result = mod.run({"structure": ps}, {"filename": "out.pdb"}, ctx)
            out_path = result["file_path"]
            assert Path(out_path).exists()
            exported = Path(out_path).read_text()
            # PDB text should match (allowing for trailing newline)
            assert exported.strip() == SAMPLE_PDB.strip()

    def test_missing_input_raises(self) -> None:
        mod = ExportStructureModule()
        ctx = RunContext("/tmp/test", "n1")
        try:
            mod.run({}, {}, ctx)
            assert False, "should have raised"
        except ValueError as e:
            assert "Missing input" in str(e)

    def test_candidate_collection_materializes_stable_pdb_mapping(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            candidates = CandidateCollection(
                collection_id="final-folds",
                item_type="protein.structure",
                items=[
                    Candidate(
                        candidate_id=f"fold-run-mpnn-parent-{index}",
                        data=ProteinStructure(
                            pdb_string=SAMPLE_PDB.replace(
                                "ALA A   1",
                                f"ALA A{index + 1:4d}",
                            )
                        ),
                    )
                    for index in range(3)
                ],
            )

            result = ExportStructureModule().run(
                {"structures": candidates},
                {"directory": "final"},
                RunContext(tmp, "export-final", run_id="canonical-run"),
            )

            references = result["file_paths"]
            assert references == [
                "final/fold-run-mpnn-parent-0.pdb",
                "final/fold-run-mpnn-parent-1.pdb",
                "final/fold-run-mpnn-parent-2.pdb",
            ]
            paths = [
                Path(tmp).resolve() / "outputs" / "canonical-run" / reference
                for reference in references
            ]
            assert [path.name for path in paths] == [
                "fold-run-mpnn-parent-0.pdb",
                "fold-run-mpnn-parent-1.pdb",
                "fold-run-mpnn-parent-2.pdb",
            ]
            assert all(path.is_file() and path.stat().st_size > 0 for path in paths)
            assert all(path.parent.name == "final" for path in paths)


class TestExportSequence:
    def test_round_trip_fasta(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            mod = ExportSequenceModule()
            ps = ProteinSequence(sequence="MKFLILFNILV")
            ctx = RunContext(tmp, "n1")
            result = mod.run({"sequence": ps}, {"filename": "out.fasta"}, ctx)
            out_path = result["file_path"]
            assert Path(out_path).exists()
            exported = Path(out_path).read_text()
            assert ">exported_sequence" in exported
            assert "MKFLILFNILV" in exported

    def test_fasta_lines_are_60_chars(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            mod = ExportSequenceModule()
            long_seq = "A" * 150
            ps = ProteinSequence(sequence=long_seq)
            ctx = RunContext(tmp, "n1")
            result = mod.run({"sequence": ps}, {}, ctx)
            exported = Path(result["file_path"]).read_text()
            lines = exported.strip().split("\n")
            # First line is header, rest are sequence lines
            seq_lines = lines[1:]
            for line in seq_lines[:-1]:
                assert len(line) == 60


class TestModuleDefinitions:
    def test_all_four_modules_discoverable(self) -> None:
        from core import TypeRegistry, ModuleRegistry, discover_modules
        tr = TypeRegistry()
        mr = ModuleRegistry(tr)
        discover_modules(mr)
        modules = {m.module_id for m in mr.list_all()}
        assert "import.structure" in modules
        assert "import.sequence" in modules
        assert "export.structure" in modules
        assert "export.sequence" in modules
        assert "stub.echo" in modules

    def test_types_registered(self) -> None:
        from core import TypeRegistry, ModuleRegistry, discover_modules
        tr = TypeRegistry()
        mr = ModuleRegistry(tr)
        discover_modules(mr)
        types = tr.list_all()
        assert "protein.structure" in types
        assert "protein.sequence" in types
        assert "text" in types
