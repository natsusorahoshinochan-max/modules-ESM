"""Export Structure: writes structures to Candidate-bound PDB files."""

from pathlib import Path
from typing import Any

from core.module_definition import ModuleDefinition
from core.recovery import (
    MAX_PUBLIC_ARTIFACTS,
    MAX_PUBLIC_ARTIFACT_BYTES,
    MAX_PUBLIC_ARTIFACT_TOTAL_BYTES,
)
from core.run_context import RunContext
from core.storage import (
    validate_identifier,
    validate_relative_path,
    write_private_new_file,
)
from core.workflow_module import WorkflowModule
from datatypes import CandidateCollection, ProteinStructure


class ExportStructureModule(WorkflowModule):
    def __init__(self) -> None:
        d = Path(__file__).parent / "definition.yaml"
        self._definition = ModuleDefinition.from_yaml(d)

    @property
    def definition(self) -> ModuleDefinition:
        return self._definition

    def run(self, inputs: dict[str, Any], parameters: dict[str, Any],
            context: RunContext) -> dict[str, Any]:
        structure: ProteinStructure | None = inputs.get("structure")
        structures: CandidateCollection | None = inputs.get("structures")
        if (structure is None) == (structures is None):
            raise ValueError(
                "Missing input: exactly one of structure or structures is required"
            )

        if structure is not None:
            if not isinstance(structure, ProteinStructure):
                raise ValueError("structure input must be a ProteinStructure")
            self._require_nonempty_pdb(structure)
            filename = parameters.get("filename", "exported.pdb")
            filename_parts = validate_relative_path(filename, "artifact_name")
            payload = self._bounded_payload(structure.pdb_string)
            out_path = write_private_new_file(
                context.output_dir or "",
                filename_parts,
                payload,
                field="artifact_name",
            )
            return {"file_path": str(out_path)}

        if not isinstance(structures, CandidateCollection):
            raise ValueError("structures input must be a CandidateCollection")
        if structures.item_type != "protein.structure":
            raise ValueError(
                "structures must contain protein.structure Candidates"
            )
        if not structures.items:
            raise ValueError("structures CandidateCollection is empty")
        if len(structures.items) > MAX_PUBLIC_ARTIFACTS:
            raise ValueError("structures contains too many public artifacts")

        candidate_ids = [
            validate_identifier(candidate.candidate_id, "candidate_id")
            for candidate in structures.items
        ]
        if len(candidate_ids) != len(set(candidate_ids)):
            raise ValueError(
                "structures CandidateCollection has duplicate Candidate IDs"
            )
        directory = parameters.get("directory", "structures")
        directory_parts = validate_relative_path(directory, "directory")
        directory_reference = "/".join(directory_parts)
        candidate_structures: list[ProteinStructure] = []
        for candidate, candidate_id in zip(
            structures.items,
            candidate_ids,
            strict=True,
        ):
            if not isinstance(candidate.data, ProteinStructure):
                raise ValueError(
                    f"Candidate {candidate_id} data is not a ProteinStructure"
                )
            self._require_nonempty_pdb(candidate.data)
            candidate_structures.append(candidate.data)
        payloads: list[bytes] = []
        total_bytes = 0
        for candidate_structure in candidate_structures:
            payload = self._bounded_payload(
                candidate_structure.pdb_string,
            )
            total_bytes += len(payload)
            if total_bytes > MAX_PUBLIC_ARTIFACT_TOTAL_BYTES:
                raise ValueError(
                    "PDB artifacts exceed the public retrieval limit"
                )
            payloads.append(payload)

        file_paths: list[str] = []
        created_paths: list[Path] = []
        artifact_facts: list[dict[str, Any]] = []
        try:
            for payload, candidate_id in zip(
                payloads,
                candidate_ids,
                strict=True,
            ):
                reference = f"{directory_reference}/{candidate_id}.pdb"
                out_path = write_private_new_file(
                    context.output_dir or "",
                    validate_relative_path(reference, "artifact_name"),
                    payload,
                    field="artifact_name",
                )
                created_paths.append(out_path)
                file_paths.append(reference)
                artifact_facts.append({
                    "path": out_path,
                    "candidate_id": candidate_id,
                    "output_port": "file_paths",
                })
            if (
                context.records_manifest
                and not context.record_artifacts(artifact_facts)
            ):
                raise RuntimeError(
                    "Artifact collection could not be recorded"
                )
        except Exception:
            for created_path in reversed(created_paths):
                created_path.unlink(missing_ok=True)
            raise
        return {"file_paths": file_paths}

    @staticmethod
    def _require_nonempty_pdb(structure: ProteinStructure) -> None:
        if (
            not isinstance(structure.pdb_string, str)
            or not structure.pdb_string.strip()
        ):
            raise ValueError("ProteinStructure must contain a nonempty PDB string")

    @staticmethod
    def _bounded_payload(pdb_string: str) -> bytes:
        if len(pdb_string) > MAX_PUBLIC_ARTIFACT_BYTES:
            raise ValueError("PDB artifact exceeds the public retrieval limit")
        payload = pdb_string.encode("utf-8")
        if len(payload) > MAX_PUBLIC_ARTIFACT_BYTES:
            raise ValueError("PDB artifact exceeds the public retrieval limit")
        return payload
