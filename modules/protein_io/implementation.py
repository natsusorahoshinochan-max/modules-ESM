"""Provider-free sequence and structure I/O implementations."""

from __future__ import annotations

from typing import Any

from core.operation import (
    OperationResources,
    ArtifactPayload,
    EngineInvocationProvenance,
    OperationCall,
)
from datatypes.candidate import (
    Candidate,
    CandidateCollection,
)
from datatypes.sequence import ProteinSequence
from datatypes.structure import ProteinStructure

from .fasta import admit_fasta_record, parse_fasta_entries, parse_fasta_sequence
from .inspection import read_structure_input


def _native_structure_bytes(structure: ProteinStructure) -> bytes:
    return structure.text.encode("utf-8")


class SequenceImportImplementation:
    """Parse one immutable Project-scoped FASTA value."""

    def __init__(self, run_resources: OperationResources) -> None:
        self._run_resources = run_resources

    def execute(self, call: OperationCall) -> dict[str, Any]:
        node_parameters = call.node_parameters
        reference = node_parameters["project_input_ref"]
        descriptor, payload = self._run_resources.read_project_input(reference)
        with self._run_resources.engine_invocation(
            invocation_provenance=EngineInvocationProvenance(
                project_input_filename=descriptor.filename
            )
        ):
            imported = ProteinSequence(
                sequence=parse_fasta_sequence(payload),
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


class SequenceBatchImportImplementation:
    """Import every FASTA record as an independent, source-addressed Candidate."""

    def __init__(self, run_resources: OperationResources) -> None:
        self._run_resources = run_resources

    def execute(self, call: OperationCall) -> dict[str, CandidateCollection]:
        descriptor, payload = self._run_resources.read_project_input(
            call.node_parameters["project_input_ref"]
        )
        with self._run_resources.engine_invocation(
            invocation_provenance=EngineInvocationProvenance(
                project_input_filename=descriptor.filename
            )
        ):
            candidates = [
                Candidate(
                    candidate_id=f"imported-record-{index}",
                    data=admit_fasta_record(record, index),
                    metadata={
                        "fasta_header": record.header,
                        "display_name": record.header or f"Record {index}",
                        "record_index": index,
                        "source_line": record.line_number,
                        "source_filename": descriptor.filename,
                    },
                )
                for index, record in enumerate(
                    parse_fasta_entries(payload), start=1
                )
            ]
        return {
            "sequence_candidates": CandidateCollection(
                collection_id="imported-sequence-records",
                item_type="protein.sequence",
                items=candidates,
            )
        }


class StructureImportImplementation:
    """Parse one immutable Project-scoped PDB or mmCIF value."""

    def __init__(self, run_resources: OperationResources) -> None:
        self._run_resources = run_resources

    def execute(self, call: OperationCall) -> dict[str, Any]:
        node_parameters = call.node_parameters
        reference = node_parameters["project_input_ref"]
        descriptor, payload = self._run_resources.read_project_input(reference)
        with self._run_resources.engine_invocation(
            invocation_provenance=EngineInvocationProvenance(
                project_input_filename=descriptor.filename
            )
        ):
            structure = read_structure_input(payload)
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

    def __init__(self, run_resources: OperationResources) -> None:
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
    """Serialize one ProteinStructure in its declared source format."""

    def __init__(self, run_resources: OperationResources) -> None:
        self._run_resources = run_resources

    def execute(self, call: OperationCall) -> dict[str, Any]:
        inputs = call.inputs
        if "structures" in inputs:
            structures = inputs["structures"].value
            with self._run_resources.engine_invocation():
                artifacts: dict[str, list[ArtifactPayload]] = {}
                for index, candidate in enumerate(structures.items):
                    body = _native_structure_bytes(candidate.data)
                    is_mmcif = candidate.data.format == "mmcif"
                    port = "candidate_mmcif_artifacts" if is_mmcif else "candidate_artifacts"
                    artifacts.setdefault(port, []).append(
                        ArtifactPayload(
                            body=body,
                            media_type="chemical/x-mmcif" if is_mmcif else "chemical/x-pdb",
                            filename=f"structure-{index:04d}.{'cif' if is_mmcif else 'pdb'}",
                            candidate_id=candidate.candidate_id,
                        )
                    )
            return artifacts
        structure = inputs["structure"].value
        with self._run_resources.engine_invocation():
            body = _native_structure_bytes(structure)
        is_mmcif = structure.format == "mmcif"
        return {
            "standalone_mmcif_artifact" if is_mmcif else "standalone_artifact": ArtifactPayload(
                body=body,
                media_type="chemical/x-mmcif" if is_mmcif else "chemical/x-pdb",
                filename="structure.cif" if is_mmcif else "structure.pdb",
            )
        }
