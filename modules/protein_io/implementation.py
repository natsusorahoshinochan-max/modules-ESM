"""Provider-free sequence and structure I/O implementations."""

from __future__ import annotations

import re
import string
from typing import Any

from core import ArtifactPayload, OperationCall, RunResources
from datatypes import (
    Candidate,
    CandidateCollection,
    ProteinSequence,
    ProteinStructure,
)


_ASCII_UPPER_TRANSLATION = str.maketrans(
    string.ascii_lowercase,
    string.ascii_uppercase,
)


def _native_pdb_bytes(structure: ProteinStructure) -> bytes:
    return structure.pdb_string.encode("ascii")


class SequenceImportImplementation:
    """Parse one immutable Project-scoped FASTA value."""

    def __init__(self, run_resources: RunResources) -> None:
        self._run_resources = run_resources

    def execute(self, call: OperationCall) -> dict[str, Any]:
        node_parameters = call.node_parameters
        reference = node_parameters["project_input_ref"]
        descriptor, payload = self._run_resources.read_project_input(reference)
        with self._run_resources.engine_invocation(
            invocation_provenance={
                "project_input_filename": descriptor["filename"]
            }
        ):
            try:
                text = payload.decode("utf-8")
            except UnicodeDecodeError as error:
                raise ValueError("Sequence input must be UTF-8 text") from error
            nonempty_lines = [line for line in text.splitlines() if line.strip()]
            header_indices = [
                index
                for index, line in enumerate(nonempty_lines)
                if line.lstrip().startswith(">")
            ]
            if len(header_indices) > 1:
                raise ValueError("Sequence input must contain exactly one record")
            if header_indices and header_indices != [0]:
                raise ValueError("Sequence input has a misplaced FASTA header")
            sequence_parts = [
                re.sub(r"\s+", "", line)
                for line in nonempty_lines[len(header_indices) :]
            ]
            raw_sequence = "".join(sequence_parts)
            imported = ProteinSequence(
                sequence=raw_sequence.translate(_ASCII_UPPER_TRANSLATION),
            )
        return {
            "sequence": imported,
            "sequence_candidates": CandidateCollection(
                collection_id="imported-sequence-reference",
                item_type="protein.sequence",
                items=[
                    Candidate(
                        candidate_id="imported-sequence",
                        data=imported,
                        parent_ids=[],
                        metadata={"input_role": "reference"},
                    )
                ],
            ),
        }


class StructureImportImplementation:
    """Parse one immutable Project-scoped PDB value."""

    def __init__(self, run_resources: RunResources) -> None:
        self._run_resources = run_resources

    def execute(self, call: OperationCall) -> dict[str, Any]:
        node_parameters = call.node_parameters
        reference = node_parameters["project_input_ref"]
        descriptor, payload = self._run_resources.read_project_input(reference)
        with self._run_resources.engine_invocation(
            invocation_provenance={
                "project_input_filename": descriptor["filename"]
            }
        ):
            try:
                text = payload.decode("utf-8")
            except UnicodeDecodeError as error:
                raise ValueError("Structure input must be UTF-8 text") from error
            canonical = text.replace("\r\n", "\n").replace("\r", "\n")
            canonical = canonical.rstrip("\n") + "\n"
            structure = ProteinStructure(pdb_string=canonical)
        return {
            "structure": structure,
            "structure_candidates": CandidateCollection(
                collection_id="imported-structure-reference",
                item_type="protein.structure",
                items=[
                    Candidate(
                        candidate_id="imported-structure",
                        data=structure,
                        parent_ids=[],
                        metadata={"input_role": "reference"},
                    )
                ],
            ),
        }


class SequenceExportImplementation:
    """Serialize one validated ProteinSequence without exposing a path."""

    def __init__(self, run_resources: RunResources) -> None:
        self._run_resources = run_resources

    def execute(self, call: OperationCall) -> dict[str, Any]:
        inputs = call.inputs
        sequence = inputs["sequence"].value
        with self._run_resources.engine_invocation():
            chars = sequence.sequence
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

    def __init__(self, run_resources: RunResources) -> None:
        self._run_resources = run_resources

    def execute(self, call: OperationCall) -> dict[str, Any]:
        inputs = call.inputs
        if "structures" in inputs:
            structures = inputs["structures"].value
            with self._run_resources.engine_invocation():
                artifacts = []
                for index, candidate in enumerate(structures.items):
                    body = _native_pdb_bytes(candidate.data)
                    artifacts.append(
                        ArtifactPayload(
                            body=body,
                            media_type="chemical/x-pdb",
                            filename=f"structure-{index:04d}.pdb",
                            candidate_id=candidate.candidate_id,
                        )
                    )
            return {"candidate_artifacts": artifacts}
        structure = inputs["structure"].value
        with self._run_resources.engine_invocation():
            body = _native_pdb_bytes(structure)
        return {
            "standalone_artifact": ArtifactPayload(
                body=body,
                media_type="chemical/x-pdb",
                filename="structure.pdb",
            )
        }
