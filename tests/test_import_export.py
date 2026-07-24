"""Tests for Import/Export modules."""

import tempfile
from pathlib import Path

from core.run_context import RunContext
from modules.import_structure.module import ImportStructureModule
from modules.import_sequence.module import ImportSequenceModule
from modules.export_structure.module import ExportStructureModule
from modules.export_sequence.module import ExportSequenceModule
from datatypes import ProteinSequence, ProteinStructure


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
        with tempfile.NamedTemporaryFile(mode="w", suffix=".pdb", delete=False) as f:
            f.write(SAMPLE_PDB)
            path = f.name

        try:
            mod = ImportStructureModule()
            ctx = RunContext("/tmp/test", "n1")
            result = mod.run({}, {"file_path": path}, ctx)
            ps = result["structure"]
            assert isinstance(ps, ProteinStructure)
            assert "ATOM" in ps.pdb_string
            assert "END" in ps.pdb_string
        finally:
            Path(path).unlink()

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
        with tempfile.NamedTemporaryFile(mode="w", suffix=".fasta", delete=False) as f:
            f.write(SAMPLE_FASTA)
            path = f.name

        try:
            mod = ImportSequenceModule()
            ctx = RunContext("/tmp/test", "n1")
            result = mod.run({}, {"file_path": path}, ctx)
            ps = result["sequence"]
            assert isinstance(ps, ProteinSequence)
            assert ps.sequence == "MKFLILFNILVSTLAFLVSSYQIPRADKHG"
        finally:
            Path(path).unlink()

    def test_ignores_fasta_headers(self) -> None:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".fasta", delete=False) as f:
            f.write(">header line\nAAAA\n")
            path = f.name

        try:
            mod = ImportSequenceModule()
            ctx = RunContext("/tmp/test", "n1")
            result = mod.run({}, {"file_path": path}, ctx)
            assert result["sequence"].sequence == "AAAA"
        finally:
            Path(path).unlink()


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
