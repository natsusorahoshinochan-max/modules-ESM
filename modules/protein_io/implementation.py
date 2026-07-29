"""Provider-free sequence and structure I/O implementations."""

from __future__ import annotations

import re
from io import StringIO
from typing import Any, Mapping

from Bio.PDB import PDBParser

from core import ArtifactPayload
from datatypes import (
    CandidateCollection,
    ProteinSequence,
    ProteinStructure,
)


_AMINO_ACIDS = re.compile(r"^[ACDEFGHIKLMNPQRSTVWYBXZJUO]+$")


def _native_pdb_bytes(structure: ProteinStructure, *, subject: str) -> bytes:
    if type(structure) is not ProteinStructure:
        raise ValueError(f"{subject} must be a ProteinStructure")
    try:
        body = structure.pdb_string.encode("utf-8")
    except UnicodeEncodeError as error:
        raise ValueError(
            "structure export requires UTF-8 PDB text"
        ) from error
    if not body:
        raise ValueError(f"{subject} contains empty PDB text")
    return body


class SequenceImportImplementation:
    """Parse one immutable Project-scoped FASTA value."""

    def __init__(self, run_resources: Any) -> None:
        self._run_resources = run_resources

    def execute(
        self,
        *,
        inputs: Mapping[str, Any],
        node_parameters: Mapping[str, Any],
        binding_parameters: Mapping[str, Any],
    ) -> dict[str, Any]:
        if inputs or binding_parameters:
            raise ValueError("sequence import accepts no connected inputs")
        reference = node_parameters["project_input_ref"]
        _, payload = self._run_resources.read_project_input(reference)
        with self._run_resources.engine_invocation(
            engine_identity="protein_io.import_sequence.method/2.0.0",
        ):
            try:
                text = payload.decode("utf-8")
            except UnicodeDecodeError as error:
                raise ValueError("Sequence input must be UTF-8 text") from error
            sequence_parts = [
                re.sub(r"\s+", "", line)
                for line in text.splitlines()
                if line.strip() and not line.lstrip().startswith(">")
            ]
            sequence = "".join(sequence_parts).upper()
            if not sequence or _AMINO_ACIDS.fullmatch(sequence) is None:
                raise ValueError(
                    "Sequence input does not contain canonical amino-acid text"
                )
        return {"sequence": ProteinSequence(sequence=sequence)}


class StructureImportImplementation:
    """Parse one immutable Project-scoped PDB value."""

    def __init__(self, run_resources: Any) -> None:
        self._run_resources = run_resources

    def execute(
        self,
        *,
        inputs: Mapping[str, Any],
        node_parameters: Mapping[str, Any],
        binding_parameters: Mapping[str, Any],
    ) -> dict[str, Any]:
        if inputs or binding_parameters:
            raise ValueError("structure import accepts no connected inputs")
        reference = node_parameters["project_input_ref"]
        _, payload = self._run_resources.read_project_input(reference)
        with self._run_resources.engine_invocation(
            engine_identity="protein_io.import_structure.method/2.0.0",
        ):
            try:
                text = payload.decode("utf-8")
            except UnicodeDecodeError as error:
                raise ValueError("Structure input must be UTF-8 text") from error
            canonical = text.replace("\r\n", "\n").replace("\r", "\n")
            canonical = canonical.rstrip("\n") + "\n"
            lines = canonical.splitlines()
            if not any(
                line.startswith(("ATOM  ", "HETATM"))
                for line in lines
            ):
                raise ValueError("Structure input contains no PDB atoms")
            if not any(line.startswith("END") for line in lines):
                raise ValueError("Structure input lacks a terminal END record")
            try:
                parsed = PDBParser(QUIET=True).get_structure(
                    "project-input",
                    StringIO(canonical),
                )
            except Exception as error:
                raise ValueError("Structure input is malformed PDB text") from error
            if next(parsed.get_atoms(), None) is None:
                raise ValueError("Structure input contains no parseable PDB atoms")
        return {
            "structure": ProteinStructure(
                pdb_string=canonical,
                source="project_input",
            )
        }


class SequenceExportImplementation:
    """Serialize one validated ProteinSequence without exposing a path."""

    def __init__(self, run_resources: Any) -> None:
        self._run_resources = run_resources

    def execute(
        self,
        *,
        inputs: Mapping[str, Any],
        node_parameters: Mapping[str, Any],
        binding_parameters: Mapping[str, Any],
    ) -> dict[str, Any]:
        if node_parameters or binding_parameters:
            raise ValueError("sequence export takes no parameters")
        sequence = inputs.get("sequence")
        if type(sequence) is not ProteinSequence or len(inputs) != 1:
            raise ValueError("sequence export requires one ProteinSequence")
        with self._run_resources.engine_invocation(
            engine_identity="protein_io.export_sequence.method/2.0.0",
        ):
            chars = sequence.sequence
            if not chars.isascii():
                raise ValueError(
                    "sequence export requires ASCII amino-acid text"
                )
            lines = [
                chars[index:index + 60]
                for index in range(0, len(chars), 60)
            ]
            body = (
                ">protein-workbench-sequence\n"
                + "\n".join(lines)
                + "\n"
            ).encode("ascii")
        return {
            "standalone_artifact": ArtifactPayload(
                body=body,
                media_type="text/x-fasta",
                filename="sequence.fasta",
            )
        }


class StructureExportImplementation:
    """Serialize one ProteinStructure without changing its PDB text."""

    def __init__(self, run_resources: Any) -> None:
        self._run_resources = run_resources

    def execute(
        self,
        *,
        inputs: Mapping[str, Any],
        node_parameters: Mapping[str, Any],
        binding_parameters: Mapping[str, Any],
    ) -> dict[str, Any]:
        if node_parameters or binding_parameters:
            raise ValueError("structure export takes no parameters")
        structure = inputs.get("structure")
        structures = inputs.get("structures")
        if (structure is None) == (structures is None) or len(inputs) != 1:
            raise ValueError(
                "structure export requires exactly one structure input"
            )
        if structures is not None:
            if (
                type(structures) is not CandidateCollection
                or structures.item_type != "protein.structure"
                or not structures.items
            ):
                raise ValueError(
                    "structures must be a nonempty structure Candidate Collection"
                )
            if len(structures.items) > 2_048:
                raise ValueError("structures exceed the artifact count bound")
            with self._run_resources.engine_invocation(
                engine_identity="protein_io.export_structure.method/2.0.0",
            ):
                artifacts = []
                for index, candidate in enumerate(structures.items):
                    body = _native_pdb_bytes(
                        candidate.data,
                        subject="structure Candidate",
                    )
                    artifacts.append(
                        ArtifactPayload(
                            body=body,
                            media_type="chemical/x-pdb",
                            filename=f"structure-{index:04d}.pdb",
                            candidate_id=candidate.candidate_id,
                        )
                    )
            return {"candidate_artifacts": artifacts}
        with self._run_resources.engine_invocation(
            engine_identity="protein_io.export_structure.method/2.0.0",
        ):
            body = _native_pdb_bytes(
                structure,
                subject="structure input",
            )
        return {
            "standalone_artifact": ArtifactPayload(
                body=body,
                media_type="chemical/x-pdb",
                filename="structure.pdb",
            )
        }
