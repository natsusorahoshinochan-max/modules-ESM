"""Deep Prompt Studio authoring interface and graph materialization."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import hashlib
import math
import re
from typing import Any, cast

from core.catalog.canonical import canonical_json_bytes
from core.project.manager import ProjectInputDescriptor, ProjectManager
from core.workflow.authoring import (
    ManagedCompositionRecord,
    ManagedRoleEndpoint,
    WorkflowAuthoringError,
    WorkflowAuthoringService,
    WorkflowDraft,
)
from core.workflow.document import (
    WorkflowDocument,
    WorkflowEdge,
    WorkflowNodeInstance,
    _thaw_json,
)
from datatypes.prompt import FunctionAnnotations, ProteinPrompt
from datatypes.residue import ResidueLayout, ResidueTrack
from datatypes.structure import ProteinStructure
from modules.structure_transform.csh_normalization import (
    contains_csh_component,
    normalize_csh_parent_span,
)
from modules.structure_transform.projections import select_chains
from modules.structure_transform.residue_axis import resolve_residue_axis

from .annotations import replace_function_annotations
from .deterministic import (
    edit_protein_prompt_layout,
    merge_protein_prompt_source,
)
from .domain import build_layout, residue_chain
from .implementation import _prompt_from_structure
from .prompts import (
    assemble_protein_prompt,
    override_protein_prompt_track,
)
from .stochastic import (
    normalize_random_insert_effective_randomness,
    normalize_random_mask_effective_randomness,
    random_insert_masked,
    random_mask_prompt,
)


_CAPABILITY_ID = "protein_prompt.authoring"
_TRACK_NAMES = (
    "sequence",
    "structure",
    "secondary_structure",
    "sasa",
)
_TRACK_ATTRIBUTES = {
    "sequence": "sequence_track",
    "structure": "structure_track",
    "secondary_structure": "secondary_structure_track",
    "sasa": "sasa_track",
}


@dataclass(frozen=True, slots=True)
class PromptAuthoringDiagnostic:
    """One user-correctable, authoring-owned located issue."""

    code: str
    message: str
    field_path: tuple[str | int, ...]
    residue_handle: str | None = None

    def projection(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "field_path": list(self.field_path),
            **(
                {}
                if self.residue_handle is None
                else {"residue_handle": self.residue_handle}
            ),
        }


@dataclass(frozen=True, slots=True)
class PromptAuthoringSnapshot:
    """One complete open projection for Prompt Studio."""

    document: Mapping[str, Any]
    residues: tuple[Mapping[str, Any], ...]
    tracks: Mapping[str, tuple[Mapping[str, Any], ...]]
    function_annotations: tuple[Mapping[str, Any], ...]
    source: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class PromptAuthoringPreview:
    """One non-executable complete authoring preview."""

    normalized_document: Mapping[str, Any]
    preview_digest: str
    residues: tuple[Mapping[str, Any], ...]
    tracks: Mapping[str, tuple[Mapping[str, Any], ...]]
    function_annotations: tuple[Mapping[str, Any], ...]
    changes: tuple[Mapping[str, Any], ...]
    random_selections: tuple[Mapping[str, Any], ...]
    source_merges: tuple[Mapping[str, Any], ...]
    diagnostics: tuple[PromptAuthoringDiagnostic, ...]
    summary: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class PromptCompositionProjection:
    """Frontend projection of one specialized composition."""

    composition_id: str
    capability_id: str
    managed_node_ids: tuple[str, ...]
    exposed_inputs: tuple[ManagedRoleEndpoint, ...]
    exposed_outputs: tuple[ManagedRoleEndpoint, ...]


@dataclass(frozen=True, slots=True)
class PromptApplyResult:
    draft: WorkflowDraft
    composition: PromptCompositionProjection | None


@dataclass(frozen=True, slots=True)
class _SourceValue:
    prompt: ProteinPrompt
    facts: Mapping[str, Any]
    csh_normalized: bool = False


@dataclass(frozen=True, slots=True)
class _EvaluatedPrompt:
    document: Mapping[str, Any]
    source: _SourceValue
    prompt: ProteinPrompt
    handle_to_residue_id: Mapping[str, str]
    residue_id_to_handle: Mapping[str, str]
    target_layout: ResidueLayout
    edits: tuple[Mapping[str, str], ...]
    track_overrides: Mapping[str, tuple[Mapping[str, Any], ...]]
    random_operations: tuple[Mapping[str, Any], ...]
    random_selections: tuple[Mapping[str, Any], ...]
    annotations: tuple[Mapping[str, str], ...]
    merges: tuple[Mapping[str, Any], ...]
    changes: tuple[Mapping[str, Any], ...]
    diagnostics: tuple[PromptAuthoringDiagnostic, ...]


def _parse_fasta(payload: bytes) -> tuple[tuple[str, str], ...]:
    text = payload.decode("utf-8")
    records: list[tuple[str, str]] = []
    header: str | None = None
    sequence_parts: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith(">"):
            if header is not None:
                records.append((header, "".join(sequence_parts).upper()))
            header = line[1:].strip()
            sequence_parts = []
        else:
            if header is None:
                header = ""
            sequence_parts.append(re.sub(r"\s+", "", line))
    if header is not None:
        records.append((header, "".join(sequence_parts).upper()))
    if not records or any(not sequence for _header, sequence in records):
        raise ValueError("FASTA source contains no complete sequence record")
    return tuple(records)


def _prompt_from_fasta(
    records: tuple[tuple[str, str], ...],
    chain_ids: Sequence[str],
) -> ProteinPrompt:
    if len(records) != len(chain_ids):
        raise ValueError("FASTA record count does not match declared chains")
    layout = build_layout(
        tuple(
            {"chain_id": chain_id, "length": len(sequence)}
            for chain_id, (_header, sequence) in zip(
                chain_ids,
                records,
                strict=True,
            )
        )
    )
    sequence = [
        residue
        for _header, record_sequence in records
        for residue in record_sequence
    ]
    return ProteinPrompt(
        target_layout=layout,
        sequence_track=ResidueTrack(sequence, None),
        structure_track=ResidueTrack([None] * layout.length, None),
        function_annotations=FunctionAnnotations(),
    )


def _blank_prompt(chains: Sequence[Mapping[str, Any]]) -> ProteinPrompt:
    layout = build_layout(cast(Any, chains))
    return assemble_protein_prompt(layout, {}, None)


def _track_values(prompt: ProteinPrompt, track: str) -> tuple[Any, ...] | None:
    value = getattr(prompt, _TRACK_ATTRIBUTES[track])
    return None if value is None else tuple(value.values)


def _copy_document(value: Mapping[str, Any]) -> dict[str, Any]:
    return cast(dict[str, Any], _thaw_json(value))


def _source_handles(prompt: ProteinPrompt) -> dict[str, str]:
    return {
        f"residue-{index + 1:08d}": residue_id
        for index, residue_id in enumerate(prompt.target_layout.residue_ids)
    }


def _source_document(
    source: Mapping[str, Any],
    prompt: ProteinPrompt,
) -> dict[str, Any]:
    handles = _source_handles(prompt)
    handle_by_id = {residue_id: handle for handle, residue_id in handles.items()}
    return {
        "source": _copy_document(source),
        "target_residues": [
            {
                "residue_handle": handle,
                "origin": "source",
                "chain_id": residue_chain(residue_id),
            }
            for handle, residue_id in handles.items()
        ],
        "track_intents": [],
        "function_annotations": [
            {
                "label": annotation.label,
                "start_residue_handle": handle_by_id[
                    annotation.start_residue_id
                ],
                "end_residue_handle": handle_by_id[
                    annotation.end_residue_id
                ],
            }
            for annotation in prompt.function_annotations.annotations
        ],
        "overlap_policy": "allow",
        "random_operations": [],
        "source_merges": [],
        "rigid_transforms": [],
    }


def _composition_projection(
    record: ManagedCompositionRecord,
) -> PromptCompositionProjection:
    return PromptCompositionProjection(
        record.composition_id,
        record.capability_id,
        record.managed_node_ids,
        record.exposed_inputs,
        record.exposed_outputs,
    )


class PromptAuthoringService:
    """The sole open, preview, and apply interface for Prompt Studio."""

    def __init__(
        self,
        projects: ProjectManager,
        workflow_authoring: WorkflowAuthoringService,
    ) -> None:
        self._projects = projects
        self._workflow_authoring = workflow_authoring

    def _record(
        self,
        project_id: str,
        composition_id: str,
    ) -> ManagedCompositionRecord:
        draft = self._workflow_authoring.load_draft(project_id)
        for record in draft.authoring_compositions:
            if record.composition_id == composition_id:
                return record
        raise WorkflowAuthoringError(
            "workflow_draft_not_found",
            "Prompt authoring composition was not found",
            details={
                "resource_kind": "authoring_composition",
                "resource_id": composition_id,
            },
        )

    def _read_project_input(
        self,
        project_id: str,
        project_input_ref: str,
    ) -> tuple[ProjectInputDescriptor, bytes]:
        try:
            return self._projects.read_input(project_id, project_input_ref)
        except FileNotFoundError as error:
            raise WorkflowAuthoringError(
                "project_input_not_found",
                "Project Input was not found",
                details={
                    "resource_kind": "project_input",
                    "resource_id": project_input_ref,
                },
            ) from error

    def _resolve_source(
        self,
        project_id: str,
        source: Mapping[str, Any],
    ) -> _SourceValue:
        kind = source["kind"]
        if kind == "blank":
            return _SourceValue(
                _blank_prompt(source["chains"]),
                {"kind": kind, "chains": _thaw_json(source["chains"])},
            )
        if kind == "fasta":
            descriptor, payload = self._read_project_input(
                project_id,
                source["project_input_ref"],
            )
            records = _parse_fasta(payload)
            return _SourceValue(
                _prompt_from_fasta(records, source["chain_ids"]),
                {
                    "kind": kind,
                    "project_input_ref": descriptor.project_input_ref,
                    "content_digest": descriptor.content_digest,
                    "chain_ids": list(source["chain_ids"]),
                },
            )
        if kind == "pdb":
            descriptor, payload = self._read_project_input(
                project_id,
                source["project_input_ref"],
            )
            structure = ProteinStructure(
                payload.decode("utf-8").replace("\r\n", "\n").replace(
                    "\r", "\n"
                ).rstrip("\n")
                + "\n"
            )
            selected = select_chains(structure, tuple(source["chain_ids"]))
            csh_normalized = contains_csh_component(selected)
            if csh_normalized:
                selected, normalizations = normalize_csh_parent_span(selected)
                axis = resolve_residue_axis(selected, normalizations)
            else:
                axis = resolve_residue_axis(selected)
            _layout, prompt = _prompt_from_structure(axis)
            return _SourceValue(
                prompt,
                {
                    "kind": kind,
                    "project_input_ref": descriptor.project_input_ref,
                    "content_digest": descriptor.content_digest,
                    "chain_ids": list(source["chain_ids"]),
                },
                csh_normalized,
            )
        record = self._record(project_id, source["composition_id"])
        evaluated = self._evaluate(project_id, record.normalized_document)
        return _SourceValue(
            evaluated.prompt,
            {
                "kind": "protein_prompt",
                "composition_id": record.composition_id,
                "confirmed_preview_identity": (
                    record.confirmed_preview_identity
                ),
            },
        )

    def open(
        self,
        project_id: str,
        request: Mapping[str, Any],
    ) -> PromptAuthoringSnapshot:
        if request["mode"] == "reopen":
            if "composition_id" not in request or "source" in request:
                raise WorkflowAuthoringError(
                    "malformed_request",
                    "Reopen requires one composition identity",
                    details={"field_path": ["composition_id"]},
                )
            record = self._record(project_id, request["composition_id"])
            document = _copy_document(record.normalized_document)
        else:
            if "source" not in request or "composition_id" in request:
                raise WorkflowAuthoringError(
                    "malformed_request",
                    "Create requires one Prompt source",
                    details={"field_path": ["source"]},
                )
            source = request["source"]
            source_value = self._resolve_source(project_id, source)
            document = _source_document(source, source_value.prompt)
        evaluated = self._evaluate(project_id, document)
        residues, tracks, annotations = self._prompt_projection(evaluated)
        return PromptAuthoringSnapshot(
            document=evaluated.document,
            residues=residues,
            tracks=tracks,
            function_annotations=annotations,
            source=evaluated.source.facts,
        )

    def _rigid_overrides(
        self,
        prompt: ProteinPrompt,
        handle_to_id: Mapping[str, str],
        transforms: Sequence[Mapping[str, Any]],
    ) -> tuple[Mapping[str, Any], ...]:
        overrides: list[Mapping[str, Any]] = []
        residue_index = {
            residue_id: index
            for index, residue_id in enumerate(prompt.target_layout.residue_ids)
        }
        for transform in transforms:
            matrix = transform["rotation_matrix"]
            origin = transform["origin"]
            translation = transform["translation"]
            for handle in transform["residue_handles"]:
                residue_id = handle_to_id[handle]
                coordinates = cast(
                    Mapping[str, Sequence[float]],
                    prompt.structure_track.values[residue_index[residue_id]],
                )
                replacement = {
                    "atom_coordinates": [
                        {
                            "atom_name": atom_name,
                            "coordinates": [
                                sum(
                                    matrix[row][column]
                                    * (coordinate[column] - origin[column])
                                    for column in range(3)
                                )
                                + origin[row]
                                + translation[row]
                                for row in range(3)
                            ],
                        }
                        for atom_name, coordinate in coordinates.items()
                    ]
                }
                overrides.append(
                    {
                        "action": "replace",
                        "residue_id": residue_id,
                        "value": replacement,
                    }
                )
        return tuple(overrides)

    def _evaluate(
        self,
        project_id: str,
        raw_document: Mapping[str, Any],
    ) -> _EvaluatedPrompt:
        document = _copy_document(raw_document)
        source = self._resolve_source(project_id, document["source"])
        source_handles = _source_handles(source.prompt)
        source_ids = set(source.prompt.target_layout.residue_ids)
        handle_to_id = dict(source_handles)
        target_ids: list[str] = []
        chain_order: list[str] = []
        for item in document["target_residues"]:
            handle = item["residue_handle"]
            chain_id = item["chain_id"]
            if chain_id not in chain_order:
                chain_order.append(chain_id)
            if item["origin"] == "source":
                residue_id = source_handles[handle]
            else:
                token = hashlib.sha256(
                    f"{chain_id}:{handle}".encode("utf-8")
                ).hexdigest()[:24]
                residue_id = f"{chain_id}:inserted.{token}"
                handle_to_id[handle] = residue_id
            target_ids.append(residue_id)
        target_layout = ResidueLayout(
            chain_id=",".join(chain_order),
            length=len(target_ids),
            residue_ids=target_ids,
        )
        target_set = set(target_ids)
        edits = tuple(
            [
                {
                    "operation": "insert",
                    "chain_id": residue_chain(residue_id),
                    "residue_id": residue_id,
                }
                for residue_id in target_ids
                if residue_id not in source_ids
            ]
            + [
                {
                    "operation": "delete",
                    "chain_id": residue_chain(residue_id),
                    "residue_id": residue_id,
                }
                for residue_id in source.prompt.target_layout.residue_ids
                if residue_id not in target_set
            ]
        )
        prompt = source.prompt
        changes: list[Mapping[str, Any]] = []
        diagnostics: list[PromptAuthoringDiagnostic] = []
        if target_layout != source.prompt.target_layout:
            prompt, _residue_map = edit_protein_prompt_layout(
                prompt,
                target_layout,
                cast(Any, edits),
            )
            changes.append(
                {
                    "kind": "layout",
                    "source_length": source.prompt.target_layout.length,
                    "target_length": target_layout.length,
                    "inserted_count": sum(
                        item["operation"] == "insert" for item in edits
                    ),
                    "deleted_count": sum(
                        item["operation"] == "delete" for item in edits
                    ),
                }
            )

        random_operations: list[Mapping[str, Any]] = []
        random_selections: list[Mapping[str, Any]] = []
        random_residue_ordinal = 0
        for operation_index, operation in enumerate(
            document["random_operations"]
        ):
            if operation["kind"] == "mask":
                unknown_handles = tuple(
                    handle
                    for handle in operation["eligible_residue_handles"]
                    if handle not in handle_to_id
                    or handle_to_id[handle]
                    not in prompt.target_layout.residue_ids
                )
                if unknown_handles:
                    diagnostics.extend(
                        PromptAuthoringDiagnostic(
                            "residue_handle_not_found",
                            "Random eligibility residue is not in the target snapshot",
                            (
                                "random_operations",
                                operation_index,
                                "eligible_residue_handles",
                            ),
                            handle,
                        )
                        for handle in unknown_handles
                    )
                    continue
                eligibility = tuple(
                    handle_to_id[handle]
                    for handle in operation["eligible_residue_handles"]
                )
                selected_track = getattr(
                    prompt,
                    _TRACK_ATTRIBUTES[operation["track"]],
                )
                if selected_track is None:
                    diagnostics.append(
                        PromptAuthoringDiagnostic(
                            "required_track_missing",
                            "Random Mask requires the selected Prompt track",
                            ("random_operations", operation_index, "track"),
                        )
                    )
                    continue
                eligible_ids = eligibility or tuple(
                    prompt.target_layout.residue_ids
                )
                residue_index = {
                    residue_id: index
                    for index, residue_id in enumerate(
                        prompt.target_layout.residue_ids
                    )
                }
                assigned_count = sum(
                    selected_track.values[residue_index[residue_id]]
                    is not None
                    for residue_id in eligible_ids
                )
                if operation["count"] > assigned_count:
                    diagnostics.append(
                        PromptAuthoringDiagnostic(
                            "random_count_exceeds_eligibility",
                            "Random count exceeds assigned eligible track positions",
                            ("random_operations", operation_index, "count"),
                        )
                    )
                    continue
                effective = normalize_random_mask_effective_randomness(
                    prompt,
                    effective_seed=operation["seed"],
                    count=operation["count"],
                    track=operation["track"],
                    eligible_residue_ids=eligibility,
                )
                before = _track_values(prompt, operation["track"])
                prompt = random_mask_prompt(
                    prompt,
                    effective_seed=effective["effective_seed"],
                    count=effective["count"],
                    track=effective["track"],
                    eligible_residue_ids=tuple(
                        effective["eligible_residue_ids"]
                    ),
                )
                after = _track_values(prompt, operation["track"])
                selected_ids = tuple(
                    residue_id
                    for index, residue_id in enumerate(
                        prompt.target_layout.residue_ids
                    )
                    if cast(Sequence[Any], before)[index] is not None
                    and cast(Sequence[Any], after)[index] is None
                )
                random_selections.append(
                    {
                        "operation_id": operation["operation_id"],
                        "kind": "mask",
                        "residue_handles": [
                            next(
                                handle
                                for handle, identity in handle_to_id.items()
                                if identity == residue_id
                            )
                            for residue_id in selected_ids
                        ],
                    }
                )
            else:
                target_chains = set(prompt.target_layout.chain_id.split(","))
                if set(operation["eligible_chain_ids"]) - target_chains:
                    diagnostics.append(
                        PromptAuthoringDiagnostic(
                            "eligible_chain_not_found",
                            "Random insertion eligibility contains an unknown chain",
                            (
                                "random_operations",
                                operation_index,
                                "eligible_chain_ids",
                            ),
                        )
                    )
                    continue
                effective = normalize_random_insert_effective_randomness(
                    prompt,
                    effective_seed=operation["seed"],
                    count=operation["count"],
                    eligible_chain_ids=tuple(operation["eligible_chain_ids"]),
                )
                before_ids = set(prompt.target_layout.residue_ids)
                prompt, _residue_map = random_insert_masked(
                    prompt,
                    effective_seed=effective["effective_seed"],
                    count=effective["count"],
                    eligible_chain_ids=tuple(effective["eligible_chain_ids"]),
                )
                inserted_ids = tuple(
                    residue_id
                    for residue_id in prompt.target_layout.residue_ids
                    if residue_id not in before_ids
                )
                for residue_id in inserted_ids:
                    random_residue_ordinal += 1
                    handle = f"random-residue-{random_residue_ordinal:08d}"
                    handle_to_id[handle] = residue_id
                random_selections.append(
                    {
                        "operation_id": operation["operation_id"],
                        "kind": "insert",
                        "inserted_positions": [
                            prompt.target_layout.residue_ids.index(residue_id)
                            for residue_id in inserted_ids
                        ],
                    }
                )
            random_operations.append(
                {**_copy_document(operation), "effective": effective}
            )

        target_set = set(prompt.target_layout.residue_ids)
        track_overrides: dict[str, list[Mapping[str, Any]]] = {
            track: [] for track in _TRACK_NAMES
        }
        touched_track_handles: set[tuple[str, str]] = set()
        for intent_index, intent in enumerate(document["track_intents"]):
            action = intent["action"]
            if action == "preserve":
                continue
            track = intent["track"]
            handle = intent["residue_handle"]
            track_handle = (track, handle)
            if track_handle in touched_track_handles:
                diagnostics.append(
                    PromptAuthoringDiagnostic(
                        "track_intent_overlap",
                        "Track intents overlap at one target residue",
                        ("track_intents", intent_index),
                        handle,
                    )
                )
                continue
            touched_track_handles.add(track_handle)
            if handle not in handle_to_id or handle_to_id[handle] not in target_set:
                diagnostics.append(
                    PromptAuthoringDiagnostic(
                        "residue_handle_not_found",
                        "Track intent residue is not in the target snapshot",
                        ("track_intents", intent_index, "residue_handle"),
                        handle,
                    )
                )
                continue
            residue_id = handle_to_id[handle]
            if action == "mask":
                override: Mapping[str, Any] = {
                    "action": "clear",
                    "residue_id": residue_id,
                }
            else:
                value = intent["value"]
                if track == "sequence" and (
                    type(value) is not str
                    or len(value) != 1
                    or value not in "ACDEFGHIKLMNPQRSTVWYBXZJUO"
                ):
                    diagnostics.append(
                        PromptAuthoringDiagnostic(
                            "invalid_track_replacement",
                            "Sequence replacement is not one amino-acid code",
                            ("track_intents", intent_index, "value"),
                            handle,
                        )
                    )
                    continue
                elif track == "secondary_structure" and value not in {
                    "H",
                    "B",
                    "E",
                    "G",
                    "I",
                    "T",
                    "S",
                    "-",
                }:
                    diagnostics.append(
                        PromptAuthoringDiagnostic(
                            "invalid_track_replacement",
                            "Secondary-structure replacement is not canonical SS8",
                            ("track_intents", intent_index, "value"),
                            handle,
                        )
                    )
                    continue
                override = {
                    "action": "replace",
                    "residue_id": residue_id,
                    "value": value,
                }
            track_overrides[track].append(override)
            changes.append(
                {
                    "kind": "track",
                    "track": track,
                    "residue_handle": intent["residue_handle"],
                    "action": action,
                }
            )

        rigid_transforms: list[Mapping[str, Any]] = []
        for transform_index, transform in enumerate(
            document["rigid_transforms"]
        ):
            matrix = transform["rotation_matrix"]
            orthonormal = all(
                math.isclose(
                    math.fsum(
                        matrix[index][left] * matrix[index][right]
                        for index in range(3)
                    ),
                    1.0 if left == right else 0.0,
                    rel_tol=0.0,
                    abs_tol=1e-8,
                )
                for left in range(3)
                for right in range(3)
            )
            determinant = (
                matrix[0][0]
                * (
                    matrix[1][1] * matrix[2][2]
                    - matrix[1][2] * matrix[2][1]
                )
                - matrix[0][1]
                * (
                    matrix[1][0] * matrix[2][2]
                    - matrix[1][2] * matrix[2][0]
                )
                + matrix[0][2]
                * (
                    matrix[1][0] * matrix[2][1]
                    - matrix[1][1] * matrix[2][0]
                )
            )
            if not orthonormal or not math.isclose(
                determinant,
                1.0,
                rel_tol=0.0,
                abs_tol=1e-8,
            ):
                diagnostics.append(
                    PromptAuthoringDiagnostic(
                        "rigid_rotation_invalid",
                        "Rigid transform rotation matrix is not a proper rotation",
                        (
                            "rigid_transforms",
                            transform_index,
                            "rotation_matrix",
                        ),
                    )
                )
                continue
            invalid = False
            for handle in transform["residue_handles"]:
                if (
                    handle not in handle_to_id
                    or handle_to_id[handle] not in target_set
                ):
                    diagnostics.append(
                        PromptAuthoringDiagnostic(
                            "residue_handle_not_found",
                            "Rigid transform residue is not in the target snapshot",
                            (
                                "rigid_transforms",
                                transform_index,
                                "residue_handles",
                            ),
                            handle,
                        )
                    )
                    invalid = True
                    continue
                residue_index = prompt.target_layout.residue_ids.index(
                    handle_to_id[handle]
                )
                if prompt.structure_track.values[residue_index] is None:
                    diagnostics.append(
                        PromptAuthoringDiagnostic(
                            "required_track_value_missing",
                            "Rigid transform requires current coordinates",
                            (
                                "rigid_transforms",
                                transform_index,
                                "residue_handles",
                            ),
                            handle,
                        )
                    )
                    invalid = True
            if not invalid:
                rigid_transforms.append(transform)
        rigid = self._rigid_overrides(
            prompt,
            handle_to_id,
            rigid_transforms,
        )
        track_overrides["structure"].extend(rigid)
        for track in _TRACK_NAMES:
            if track_overrides[track]:
                prompt = override_protein_prompt_track(
                    prompt,
                    track=track,
                    overrides=cast(Any, track_overrides[track]),
                )

        annotation_values: list[Mapping[str, str]] = []
        target_index = {
            residue_id: index
            for index, residue_id in enumerate(prompt.target_layout.residue_ids)
        }
        for annotation_index, annotation in enumerate(
            document["function_annotations"]
        ):
            valid_annotation = True
            for endpoint in (
                "start_residue_handle",
                "end_residue_handle",
            ):
                handle = annotation[endpoint]
                if (
                    handle not in handle_to_id
                    or handle_to_id[handle]
                    not in prompt.target_layout.residue_ids
                ):
                    diagnostics.append(
                        PromptAuthoringDiagnostic(
                            "annotation_endpoint_not_found",
                            "Function annotation endpoint is not in the target snapshot",
                            (
                                "function_annotations",
                                annotation_index,
                                endpoint,
                            ),
                            handle,
                        )
                    )
                    valid_annotation = False
            if not valid_annotation:
                continue
            start_residue_id = handle_to_id[
                annotation["start_residue_handle"]
            ]
            end_residue_id = handle_to_id[
                annotation["end_residue_handle"]
            ]
            if (
                residue_chain(start_residue_id)
                != residue_chain(end_residue_id)
                or target_index[start_residue_id]
                > target_index[end_residue_id]
            ):
                diagnostics.append(
                    PromptAuthoringDiagnostic(
                        "annotation_interval_invalid",
                        "Function annotation interval is not ordered within one chain",
                        ("function_annotations", annotation_index),
                    )
                )
                continue
            annotation_values.append(
                {
                    "label": annotation["label"],
                    "chain_id": residue_chain(start_residue_id),
                    "start_residue_id": start_residue_id,
                    "end_residue_id": end_residue_id,
                }
            )
        annotations = tuple(annotation_values)
        final_annotations = replace_function_annotations(
            cast(ResidueLayout, prompt.target_layout),
            annotations,
            overlap_policy="allow",
        )
        if document["overlap_policy"] == "reject":
            previous_end = 0
            for annotation_index, annotation in enumerate(
                final_annotations.annotations
            ):
                if annotation.start <= previous_end:
                    diagnostics.append(
                        PromptAuthoringDiagnostic(
                            "annotation_overlap",
                            "Function annotations overlap under the reject policy",
                            ("function_annotations", annotation_index),
                        )
                    )
                previous_end = max(previous_end, annotation.end)
        prompt = ProteinPrompt(
            target_layout=prompt.target_layout,
            sequence_track=prompt.sequence_track,
            structure_track=prompt.structure_track,
            secondary_structure_track=prompt.secondary_structure_track,
            sasa_track=prompt.sasa_track,
            function_annotations=final_annotations,
        )

        merges: list[Mapping[str, Any]] = []
        for merge_index, merge in enumerate(document["source_merges"]):
            merge_source = self._resolve_source(project_id, merge["source"])
            source_handle_map = _source_handles(merge_source.prompt)
            correspondence_items: list[Mapping[str, str]] = []
            correspondence_valid = True
            for row_index, item in enumerate(merge["correspondence"]):
                row_valid = True
                source_handle = item.get("source_residue_handle")
                target_handle = item.get("target_residue_handle")
                if (
                    source_handle is not None
                    and source_handle not in source_handle_map
                ):
                    diagnostics.append(
                        PromptAuthoringDiagnostic(
                            "residue_handle_not_found",
                            "Merge source residue is not in its source snapshot",
                            (
                                "source_merges",
                                merge_index,
                                "correspondence",
                                row_index,
                                "source_residue_handle",
                            ),
                            source_handle,
                        )
                    )
                    correspondence_valid = False
                    row_valid = False
                if (
                    target_handle is not None
                    and (
                        target_handle not in handle_to_id
                        or handle_to_id[target_handle]
                        not in prompt.target_layout.residue_ids
                    )
                ):
                    diagnostics.append(
                        PromptAuthoringDiagnostic(
                            "residue_handle_not_found",
                            "Merge target residue is not in the target snapshot",
                            (
                                "source_merges",
                                merge_index,
                                "correspondence",
                                row_index,
                                "target_residue_handle",
                            ),
                            target_handle,
                        )
                    )
                    correspondence_valid = False
                    row_valid = False
                if row_valid:
                    correspondence_items.append(
                        {
                            "disposition": item["disposition"],
                            **(
                                {}
                                if source_handle is None
                                else {
                                    "source_residue_id": source_handle_map[
                                        source_handle
                                    ]
                                }
                            ),
                            **(
                                {}
                                if target_handle is None
                                else {
                                    "target_residue_id": handle_to_id[
                                        target_handle
                                    ]
                                }
                            ),
                        }
                    )
            correspondence = tuple(correspondence_items)
            source_corresponded = tuple(
                item["source_residue_id"]
                for item in correspondence
                if "source_residue_id" in item
            )
            target_corresponded = tuple(
                item["target_residue_id"]
                for item in correspondence
                if "target_residue_id" in item
            )
            source_counts = Counter(source_corresponded)
            target_counts = Counter(target_corresponded)
            source_id_to_handle = {
                residue_id: handle
                for handle, residue_id in source_handle_map.items()
            }
            target_id_to_handle = {
                residue_id: handle for handle, residue_id in handle_to_id.items()
            }
            for residue_id in merge_source.prompt.target_layout.residue_ids:
                count = source_counts[residue_id]
                if count == 0:
                    diagnostics.append(
                        PromptAuthoringDiagnostic(
                            "correspondence_source_missing",
                            "Merge correspondence does not dispose this source residue",
                            ("source_merges", merge_index, "correspondence"),
                            source_id_to_handle[residue_id],
                        )
                    )
                    correspondence_valid = False
                elif count > 1:
                    diagnostics.append(
                        PromptAuthoringDiagnostic(
                            "correspondence_source_duplicate",
                            "Merge correspondence disposes this source residue more than once",
                            ("source_merges", merge_index, "correspondence"),
                            source_id_to_handle[residue_id],
                        )
                    )
                    correspondence_valid = False
            for residue_id in prompt.target_layout.residue_ids:
                count = target_counts[residue_id]
                if count == 0:
                    diagnostics.append(
                        PromptAuthoringDiagnostic(
                            "correspondence_target_missing",
                            "Merge correspondence does not dispose this target residue",
                            ("source_merges", merge_index, "correspondence"),
                            target_id_to_handle[residue_id],
                        )
                    )
                    correspondence_valid = False
                elif count > 1:
                    diagnostics.append(
                        PromptAuthoringDiagnostic(
                            "correspondence_target_duplicate",
                            "Merge correspondence disposes this target residue more than once",
                            ("source_merges", merge_index, "correspondence"),
                            target_id_to_handle[residue_id],
                        )
                    )
                    correspondence_valid = False
            for track in _TRACK_NAMES:
                if (
                    merge["track_decisions"][track] == "adopt"
                    and _track_values(merge_source.prompt, track) is None
                ):
                    diagnostics.append(
                        PromptAuthoringDiagnostic(
                            "merge_source_track_missing",
                            "Merge source does not contain the adopted track",
                            (
                                "source_merges",
                                merge_index,
                                "track_decisions",
                                track,
                            ),
                        )
                    )
                    correspondence_valid = False
            if merge["track_decisions"]["function_annotations"] == "adopt":
                source_to_target = {
                    item["source_residue_id"]: item["target_residue_id"]
                    for item in correspondence
                    if item["disposition"] == "match"
                }
                source_ids = tuple(
                    merge_source.prompt.target_layout.residue_ids
                )
                source_index = {
                    residue_id: index
                    for index, residue_id in enumerate(source_ids)
                }
                target_index = {
                    residue_id: index
                    for index, residue_id in enumerate(
                        prompt.target_layout.residue_ids
                    )
                }
                for annotation_index, annotation in enumerate(
                    merge_source.prompt.function_annotations.annotations
                ):
                    source_span = source_ids[
                        source_index[annotation.start_residue_id] :
                        source_index[annotation.end_residue_id] + 1
                    ]
                    mapped_span = tuple(
                        source_to_target.get(residue_id)
                        for residue_id in source_span
                    )
                    mapped_positions = tuple(
                        target_index[residue_id]
                        for residue_id in mapped_span
                        if residue_id is not None
                    )
                    annotation_lost = (
                        len(mapped_positions) != len(source_span)
                        or mapped_positions
                        != tuple(
                            range(
                                mapped_positions[0],
                                mapped_positions[0] + len(mapped_positions),
                            )
                        )
                        or len({
                            residue_chain(residue_id)
                            for residue_id in mapped_span
                            if residue_id is not None
                        })
                        != 1
                    )
                    if annotation_lost:
                        diagnostics.append(
                            PromptAuthoringDiagnostic(
                                "annotation_loss",
                                "Source merge would lose a function annotation interval",
                                (
                                    "source_merges",
                                    merge_index,
                                    "track_decisions",
                                    "function_annotations",
                                    annotation_index,
                                ),
                                source_id_to_handle[
                                    annotation.start_residue_id
                                ],
                            )
                        )
                        correspondence_valid = False
            if correspondence_valid and merge["confirmed"] and "conflict" not in merge[
                "track_decisions"
            ].values():
                prompt = merge_protein_prompt_source(
                    prompt,
                    merge_source.prompt,
                    correspondence,
                    merge["track_decisions"],
                )
            merges.append(
                {
                    "source": merge_source.facts,
                    "correspondence": correspondence,
                    "track_decisions": _copy_document(
                        merge["track_decisions"]
                    ),
                    "confirmed": merge["confirmed"],
                }
            )

        residue_id_to_handle = {
            residue_id: handle for handle, residue_id in handle_to_id.items()
        }
        return _EvaluatedPrompt(
            document=document,
            source=source,
            prompt=prompt,
            handle_to_residue_id=handle_to_id,
            residue_id_to_handle=residue_id_to_handle,
            target_layout=target_layout,
            edits=edits,
            track_overrides={
                track: tuple(overrides)
                for track, overrides in track_overrides.items()
            },
            random_operations=tuple(random_operations),
            random_selections=tuple(random_selections),
            annotations=annotations,
            merges=tuple(merges),
            changes=tuple(changes),
            diagnostics=tuple(diagnostics),
        )

    def _prompt_projection(
        self,
        evaluated: _EvaluatedPrompt,
    ) -> tuple[
        tuple[Mapping[str, Any], ...],
        Mapping[str, tuple[Mapping[str, Any], ...]],
        tuple[Mapping[str, Any], ...],
    ]:
        prompt = evaluated.prompt
        handles = evaluated.residue_id_to_handle
        source_prompt = evaluated.source.prompt
        source_ids = tuple(source_prompt.target_layout.residue_ids)
        source_index = {
            residue_id: index for index, residue_id in enumerate(source_ids)
        }
        target_ids = set(prompt.target_layout.residue_ids)
        preserved = {
            (intent["track"], intent["residue_handle"])
            for intent in evaluated.document["track_intents"]
            if intent["action"] == "preserve"
        }
        residues: list[Mapping[str, Any]] = []
        for index, residue_id in enumerate(prompt.target_layout.residue_ids):
            handle = handles[residue_id]
            residues.append(
                {
                    "residue_handle": handle,
                    "chain_id": residue_chain(residue_id),
                    "residue_label": residue_id.split(":", 1)[1],
                    "position": index + 1,
                }
            )
        for index, residue_id in enumerate(source_ids):
            if residue_id in target_ids:
                continue
            residues.append(
                {
                    "residue_handle": handles[residue_id],
                    "chain_id": residue_chain(residue_id),
                    "residue_label": residue_id.split(":", 1)[1],
                    "position": index + 1,
                }
            )
        tracks: dict[str, tuple[Mapping[str, Any], ...]] = {}
        for track in _TRACK_NAMES:
            values = _track_values(prompt, track)
            source_values = _track_values(source_prompt, track)

            def projected_value(value: Any) -> Any:
                if value is None:
                    return None
                if track != "structure":
                    return value
                return {
                    "atoms": [
                        {
                            "atom_handle": f"atom-{atom_index + 1:04d}",
                            "atom_label": atom_name,
                            "coordinates": list(coordinates),
                        }
                        for atom_index, (atom_name, coordinates) in enumerate(
                            cast(Mapping[str, Any], value).items()
                        )
                    ]
                }

            projected: list[Mapping[str, Any]] = []
            for index, residue_id in enumerate(prompt.target_layout.residue_ids):
                handle = cast(str, residues[index]["residue_handle"])
                value = None if values is None else values[index]
                if residue_id not in source_index:
                    state = "inserted"
                else:
                    source_value = (
                        None
                        if source_values is None
                        else source_values[source_index[residue_id]]
                    )
                    if value == source_value:
                        state = (
                            "current"
                            if (track, handle) in preserved
                            else "source"
                        )
                    elif value is None:
                        state = "cleared"
                    else:
                        state = "changed"
                projected.append({
                    "residue_handle": residues[index]["residue_handle"],
                    "value": projected_value(value),
                    "state": state,
                })
            for index, residue_id in enumerate(source_ids):
                if residue_id in target_ids:
                    continue
                source_value = (
                    None if source_values is None else source_values[index]
                )
                projected.append({
                    "residue_handle": handles[residue_id],
                    "value": projected_value(source_value),
                    "state": "pending-delete",
                })
            tracks[track] = tuple(projected)
        source_annotations = {
            (
                annotation.label,
                annotation.start_residue_id,
                annotation.end_residue_id,
            ): annotation
            for annotation in source_prompt.function_annotations.annotations
        }
        final_annotation_keys = {
            (
                annotation.label,
                annotation.start_residue_id,
                annotation.end_residue_id,
            )
            for annotation in prompt.function_annotations.annotations
        }
        source_labels = {
            annotation.label
            for annotation in source_prompt.function_annotations.annotations
        }
        annotations: list[Mapping[str, Any]] = []
        for annotation in prompt.function_annotations.annotations:
            key = (
                annotation.label,
                annotation.start_residue_id,
                annotation.end_residue_id,
            )
            annotations.append(
                {
                    "label": annotation.label,
                    "start_residue_handle": handles[
                        annotation.start_residue_id
                    ],
                    "end_residue_handle": handles[annotation.end_residue_id],
                    "state": (
                        "source"
                        if key in source_annotations
                        else (
                            "changed"
                            if annotation.label in source_labels
                            else "inserted"
                        )
                    ),
                }
            )
        for key, annotation in source_annotations.items():
            if key in final_annotation_keys:
                continue
            annotations.append(
                {
                    "label": annotation.label,
                    "start_residue_handle": handles[
                        annotation.start_residue_id
                    ],
                    "end_residue_handle": handles[annotation.end_residue_id],
                    "state": "pending-delete",
                }
            )
        return tuple(residues), tracks, tuple(annotations)

    def preview(
        self,
        project_id: str,
        document: Mapping[str, Any],
        composition_id: str | None = None,
    ) -> PromptAuthoringPreview:
        evaluated = self._evaluate(project_id, document)
        residues, tracks, annotations = self._prompt_projection(evaluated)
        composition_facts = (
            None
            if composition_id is None
            else {
                "composition_id": composition_id,
                "confirmed_preview_identity": self._record(
                    project_id,
                    composition_id,
                ).confirmed_preview_identity,
            }
        )
        preview_digest = "sha256:" + hashlib.sha256(
            canonical_json_bytes(
                {
                    "normalized_document": evaluated.document,
                    "source_facts": evaluated.source.facts,
                    "composition_facts": composition_facts,
                }
            )
        ).hexdigest()
        summary = {
            "chains": [
                {
                    "chain_id": chain_id,
                    "length": sum(
                        residue_chain(residue_id) == chain_id
                        for residue_id in evaluated.prompt.target_layout.residue_ids
                    ),
                }
                for chain_id in evaluated.prompt.target_layout.chain_id.split(",")
            ],
            "tracks": {
                track: {
                    "specified": sum(
                        value is not None
                        for value in (_track_values(evaluated.prompt, track) or ())
                    ),
                    "unspecified": (
                        evaluated.prompt.target_layout.length
                        - sum(
                            value is not None
                            for value in (
                                _track_values(evaluated.prompt, track) or ()
                            )
                        )
                    ),
                }
                for track in _TRACK_NAMES
            },
            "function_annotation_count": len(
                evaluated.prompt.function_annotations.annotations
            ),
        }
        merge_diagnostics = tuple(
            diagnostic
            for index, merge in enumerate(evaluated.document["source_merges"])
            for diagnostic in (
                *(
                    ()
                    if merge["confirmed"]
                    else (
                        PromptAuthoringDiagnostic(
                            "correspondence_unconfirmed",
                            "Source correspondence has not been confirmed",
                            ("source_merges", index, "confirmed"),
                        ),
                    )
                ),
                *(
                    PromptAuthoringDiagnostic(
                        "source_conflict_unresolved",
                        "Source track conflict has not been decided",
                        (
                            "source_merges",
                            index,
                            "track_decisions",
                            track,
                        ),
                    )
                    for track, decision in merge["track_decisions"].items()
                    if decision == "conflict"
                ),
            )
        )
        diagnostics = (*evaluated.diagnostics, *merge_diagnostics)
        return PromptAuthoringPreview(
            normalized_document=evaluated.document,
            preview_digest=preview_digest,
            residues=residues,
            tracks=tracks,
            function_annotations=annotations,
            changes=evaluated.changes,
            random_selections=evaluated.random_selections,
            source_merges=tuple(
                {
                    "source": evaluated.merges[index]["source"],
                    "correspondence": _thaw_json(
                        merge["correspondence"]
                    ),
                    "track_decisions": _thaw_json(
                        merge["track_decisions"]
                    ),
                    "confirmed": merge["confirmed"],
                }
                for index, merge in enumerate(
                    evaluated.document["source_merges"]
                )
            ),
            diagnostics=diagnostics,
            summary=summary,
        )

    def _managed_node_id(
        self,
        composition_id: str,
        logical_role: str,
    ) -> str:
        return f"{composition_id}.{logical_role}"

    def _node(
        self,
        composition_id: str,
        logical_role: str,
        operation: str,
        node_parameters: Mapping[str, Any],
    ) -> WorkflowNodeInstance:
        return WorkflowNodeInstance(
            node_id=self._managed_node_id(composition_id, logical_role),
            node_type_id=operation,
            binding_id=f"{operation}.direct",
            node_parameters=node_parameters,
            binding_parameters={},
        )

    def _materialize_base_source(
        self,
        project_id: str,
        composition_id: str,
        evaluated: _EvaluatedPrompt,
    ) -> tuple[
        list[WorkflowNodeInstance],
        list[WorkflowEdge],
        tuple[str, str],
        ManagedRoleEndpoint,
        list[ManagedRoleEndpoint],
        list[WorkflowEdge],
    ]:
        source = evaluated.document["source"]
        kind = source["kind"]
        nodes: list[WorkflowNodeInstance] = []
        edges: list[WorkflowEdge] = []
        exposed_inputs: list[ManagedRoleEndpoint] = []
        external_edges: list[WorkflowEdge] = []
        if kind == "pdb":
            imported = self._node(
                composition_id,
                "source.import_structure",
                "protein_io.import_structure",
                {"project_input_ref": source["project_input_ref"]},
            )
            selected = self._node(
                composition_id,
                "source.select_chains",
                "structure_transform.select_chains",
                {"chain_ids": source["chain_ids"]},
            )
            resolved = self._node(
                composition_id,
                "source.resolve_axis",
                "structure_transform.resolve_residue_axis",
                {},
            )
            prompt_node = self._node(
                composition_id,
                "source.prompt",
                "prompt_authoring.prompt_from_structure",
                {},
            )
            nodes.extend((imported, selected))
            edges.append(
                WorkflowEdge(
                    imported.node_id,
                    "structure",
                    selected.node_id,
                    "structure",
                )
            )
            resolved_source = selected
            if evaluated.source.csh_normalized:
                normalized = self._node(
                    composition_id,
                    "source.normalize_csh",
                    "structure_transform.normalize_csh_parent_span",
                    {},
                )
                nodes.append(normalized)
                edges.extend(
                    (
                        WorkflowEdge(
                            selected.node_id,
                            "structure",
                            normalized.node_id,
                            "structure",
                        ),
                        WorkflowEdge(
                            normalized.node_id,
                            "modified_residue_normalizations",
                            resolved.node_id,
                            "modified_residue_normalizations",
                        ),
                    )
                )
                resolved_source = normalized
            nodes.extend((resolved, prompt_node))
            edges.extend(
                (
                    WorkflowEdge(
                        resolved_source.node_id,
                        "structure",
                        resolved.node_id,
                        "structure",
                    ),
                    WorkflowEdge(
                        resolved.node_id,
                        "residue_axis",
                        prompt_node.node_id,
                        "residue_axis",
                    ),
                )
            )
            return (
                nodes,
                edges,
                (prompt_node.node_id, "protein_prompt"),
                ManagedRoleEndpoint(
                    "residue_layout",
                    prompt_node.node_id,
                    "layout",
                ),
                exposed_inputs,
                external_edges,
            )
        if kind == "protein_prompt":
            identity = self._node(
                composition_id,
                "source.prompt",
                "prompt_authoring.override_protein_prompt_track",
                {"track": "sequence", "overrides": []},
            )
            layout = self._node(
                composition_id,
                "source.layout",
                "prompt_authoring.build_residue_layout",
                {
                    "chains": [
                        {
                            "chain_id": chain_id,
                            "length": sum(
                                residue_chain(residue_id) == chain_id
                                for residue_id in evaluated.source.prompt.target_layout.residue_ids
                            ),
                        }
                        for chain_id in evaluated.source.prompt.target_layout.chain_id.split(",")
                    ]
                },
            )
            nodes.extend((identity, layout))
            endpoint = ManagedRoleEndpoint(
                "prompt_source",
                identity.node_id,
                "protein_prompt",
            )
            exposed_inputs.append(endpoint)
            source_record = self._record(
                project_id,
                source["composition_id"],
            )
            source_output = source_record.exposed_outputs[0]
            external_edges.append(
                WorkflowEdge(
                    source_output.node_id,
                    source_output.port_name,
                    identity.node_id,
                    "protein_prompt",
                )
            )
            return (
                nodes,
                edges,
                (identity.node_id, "protein_prompt"),
                ManagedRoleEndpoint(
                    "residue_layout",
                    layout.node_id,
                    "layout",
                ),
                exposed_inputs,
                external_edges,
            )
        chains = [
            {
                "chain_id": chain_id,
                "length": sum(
                    residue_chain(residue_id) == chain_id
                    for residue_id in evaluated.source.prompt.target_layout.residue_ids
                ),
            }
            for chain_id in evaluated.source.prompt.target_layout.chain_id.split(",")
        ]
        layout = self._node(
            composition_id,
            "source.layout",
            "prompt_authoring.build_residue_layout",
            {"chains": chains},
        )
        assemble = self._node(
            composition_id,
            "source.prompt",
            "prompt_authoring.assemble_protein_prompt",
            {},
        )
        nodes.extend((layout, assemble))
        edges.append(
            WorkflowEdge(layout.node_id, "layout", assemble.node_id, "layout")
        )
        current = (assemble.node_id, "protein_prompt")
        if kind == "fasta":
            imported = self._node(
                composition_id,
                "source.import_sequence",
                "protein_io.import_sequence",
                {"project_input_ref": source["project_input_ref"]},
            )
            sequence = self._node(
                composition_id,
                "source.sequence",
                "prompt_authoring.update_prompt_sequence",
                {},
            )
            nodes.extend((imported, sequence))
            edges.extend(
                (
                    WorkflowEdge(
                        current[0],
                        current[1],
                        sequence.node_id,
                        "protein_prompt",
                    ),
                    WorkflowEdge(
                        imported.node_id,
                        "sequence",
                        sequence.node_id,
                        "sequence",
                    ),
                )
            )
            current = (sequence.node_id, "protein_prompt")
        return (
            nodes,
            edges,
            current,
            ManagedRoleEndpoint(
                "residue_layout",
                layout.node_id,
                "layout",
            ),
            exposed_inputs,
            external_edges,
        )

    def _materialize_merge_source(
        self,
        project_id: str,
        composition_id: str,
        merge_index: int,
        source: Mapping[str, Any],
        source_value: _SourceValue,
    ) -> tuple[
        list[WorkflowNodeInstance],
        list[WorkflowEdge],
        tuple[str, str],
        list[ManagedRoleEndpoint],
        list[WorkflowEdge],
    ]:
        prefix = f"merge.{merge_index + 1:04d}.source"
        nodes: list[WorkflowNodeInstance] = []
        edges: list[WorkflowEdge] = []
        exposed_inputs: list[ManagedRoleEndpoint] = []
        external_edges: list[WorkflowEdge] = []
        if source["kind"] == "pdb":
            imported = self._node(
                composition_id,
                f"{prefix}.import_structure",
                "protein_io.import_structure",
                {"project_input_ref": source["project_input_ref"]},
            )
            selected = self._node(
                composition_id,
                f"{prefix}.select_chains",
                "structure_transform.select_chains",
                {"chain_ids": source["chain_ids"]},
            )
            resolved = self._node(
                composition_id,
                f"{prefix}.resolve_axis",
                "structure_transform.resolve_residue_axis",
                {},
            )
            prompt_node = self._node(
                composition_id,
                f"{prefix}.prompt",
                "prompt_authoring.prompt_from_structure",
                {},
            )
            nodes.extend((imported, selected))
            edges.append(
                WorkflowEdge(
                    imported.node_id,
                    "structure",
                    selected.node_id,
                    "structure",
                )
            )
            resolved_source = selected
            if source_value.csh_normalized:
                normalized = self._node(
                    composition_id,
                    f"{prefix}.normalize_csh",
                    "structure_transform.normalize_csh_parent_span",
                    {},
                )
                nodes.append(normalized)
                edges.extend(
                    (
                        WorkflowEdge(
                            selected.node_id,
                            "structure",
                            normalized.node_id,
                            "structure",
                        ),
                        WorkflowEdge(
                            normalized.node_id,
                            "modified_residue_normalizations",
                            resolved.node_id,
                            "modified_residue_normalizations",
                        ),
                    )
                )
                resolved_source = normalized
            nodes.extend((resolved, prompt_node))
            edges.extend(
                (
                    WorkflowEdge(
                        resolved_source.node_id,
                        "structure",
                        resolved.node_id,
                        "structure",
                    ),
                    WorkflowEdge(
                        resolved.node_id,
                        "residue_axis",
                        prompt_node.node_id,
                        "residue_axis",
                    ),
                )
            )
            return (
                nodes,
                edges,
                (prompt_node.node_id, "protein_prompt"),
                exposed_inputs,
                external_edges,
            )
        if source["kind"] == "protein_prompt":
            identity = self._node(
                composition_id,
                f"{prefix}.prompt",
                "prompt_authoring.override_protein_prompt_track",
                {"track": "sequence", "overrides": []},
            )
            nodes.append(identity)
            exposed_inputs.append(
                ManagedRoleEndpoint(
                    f"source_merge_{merge_index + 1}",
                    identity.node_id,
                    "protein_prompt",
                )
            )
            source_record = self._record(
                project_id,
                source["composition_id"],
            )
            source_output = source_record.exposed_outputs[0]
            external_edges.append(
                WorkflowEdge(
                    source_output.node_id,
                    source_output.port_name,
                    identity.node_id,
                    "protein_prompt",
                )
            )
            return (
                nodes,
                edges,
                (identity.node_id, "protein_prompt"),
                exposed_inputs,
                external_edges,
            )
        chains = [
            {
                "chain_id": chain_id,
                "length": sum(
                    residue_chain(residue_id) == chain_id
                    for residue_id in source_value.prompt.target_layout.residue_ids
                ),
            }
            for chain_id in source_value.prompt.target_layout.chain_id.split(",")
        ]
        layout = self._node(
            composition_id,
            f"{prefix}.layout",
            "prompt_authoring.build_residue_layout",
            {"chains": chains},
        )
        assemble = self._node(
            composition_id,
            f"{prefix}.prompt",
            "prompt_authoring.assemble_protein_prompt",
            {},
        )
        nodes.extend((layout, assemble))
        edges.append(
            WorkflowEdge(layout.node_id, "layout", assemble.node_id, "layout")
        )
        current = (assemble.node_id, "protein_prompt")
        if source["kind"] == "fasta":
            imported = self._node(
                composition_id,
                f"{prefix}.import_sequence",
                "protein_io.import_sequence",
                {"project_input_ref": source["project_input_ref"]},
            )
            sequence = self._node(
                composition_id,
                f"{prefix}.sequence",
                "prompt_authoring.update_prompt_sequence",
                {},
            )
            nodes.extend((imported, sequence))
            edges.extend(
                (
                    WorkflowEdge(
                        current[0],
                        current[1],
                        sequence.node_id,
                        "protein_prompt",
                    ),
                    WorkflowEdge(
                        imported.node_id,
                        "sequence",
                        sequence.node_id,
                        "sequence",
                    ),
                )
            )
            current = (sequence.node_id, "protein_prompt")
        return nodes, edges, current, exposed_inputs, external_edges

    def _materialize(
        self,
        project_id: str,
        composition_id: str,
        evaluated: _EvaluatedPrompt,
        preview_digest: str,
    ) -> tuple[
        tuple[WorkflowNodeInstance, ...],
        tuple[WorkflowEdge, ...],
        ManagedCompositionRecord,
        tuple[WorkflowEdge, ...],
    ]:
        (
            nodes,
            edges,
            current,
            layout_output,
            exposed_inputs,
            external_edges,
        ) = (
            self._materialize_base_source(project_id, composition_id, evaluated)
        )
        role_index = 0

        def append_prompt_node(
            logical_name: str,
            operation: str,
            parameters: Mapping[str, Any],
        ) -> None:
            nonlocal current, role_index
            role_index += 1
            node = self._node(
                composition_id,
                f"{role_index:04d}.{logical_name}",
                operation,
                parameters,
            )
            nodes.append(node)
            edges.append(
                WorkflowEdge(
                    current[0],
                    current[1],
                    node.node_id,
                    "protein_prompt",
                )
            )
            current = (node.node_id, "protein_prompt")

        if evaluated.edits:
            source_ids = set(evaluated.source.prompt.target_layout.residue_ids)
            target_ids = tuple(evaluated.target_layout.residue_ids)
            insertion_declarations: list[dict[str, Any]] = []
            position = 0
            while position < len(target_ids):
                if target_ids[position] in source_ids:
                    position += 1
                    continue
                start = position
                while position < len(target_ids) and target_ids[position] not in source_ids:
                    position += 1
                declaration: dict[str, Any] = {
                    "inserted_residue_ids": list(target_ids[start:position])
                }
                if start > 0:
                    declaration["after_residue_id"] = target_ids[start - 1]
                if position < len(target_ids):
                    declaration["before_residue_id"] = target_ids[position]
                insertion_declarations.append(declaration)
            append_prompt_node(
                "layout_edit",
                "prompt_authoring.edit_protein_prompt_layout",
                {
                    "insertions": insertion_declarations,
                    "deleted_residue_ids": [
                        item["residue_id"]
                        for item in evaluated.edits
                        if item["operation"] == "delete"
                    ],
                },
            )
            layout_output = ManagedRoleEndpoint(
                "residue_layout", current[0], "layout"
            )
        for random_operation in evaluated.random_operations:
            effective = random_operation["effective"]
            if random_operation["kind"] == "mask":
                append_prompt_node(
                    f"random_mask_{random_operation['operation_id']}",
                    "prompt_authoring.random_mask",
                    effective,
                )
            else:
                append_prompt_node(
                    f"random_insert_{random_operation['operation_id']}",
                    "prompt_authoring.random_insert_masked",
                    effective,
                )
                layout_output = ManagedRoleEndpoint(
                    "residue_layout", current[0], "layout"
                )
        for track in _TRACK_NAMES:
            overrides = evaluated.track_overrides[track]
            if overrides:
                append_prompt_node(
                    f"override_{track}",
                    "prompt_authoring.override_protein_prompt_track",
                    {"track": track, "overrides": list(overrides)},
                )
        append_prompt_node(
            "annotations",
            "prompt_authoring.replace_protein_prompt_annotations",
            {
                "annotations": list(evaluated.annotations),
                "overlap_policy": evaluated.document["overlap_policy"],
            },
        )
        for merge_index, merge in enumerate(evaluated.merges):
            source = evaluated.document["source_merges"][merge_index]["source"]
            source_value = self._resolve_source(project_id, source)
            (
                merge_nodes,
                merge_edges,
                merge_current,
                merge_inputs,
                merge_external_edges,
            ) = self._materialize_merge_source(
                project_id,
                composition_id,
                merge_index,
                source,
                source_value,
            )
            nodes.extend(merge_nodes)
            edges.extend(merge_edges)
            exposed_inputs.extend(merge_inputs)
            external_edges.extend(merge_external_edges)
            role_index += 1
            merge_node = self._node(
                composition_id,
                f"{role_index:04d}.source_merge",
                "prompt_authoring.merge_protein_prompt_source",
                {
                    "correspondence": list(merge["correspondence"]),
                    "track_decisions": _copy_document(
                        merge["track_decisions"]
                    ),
                },
            )
            nodes.append(merge_node)
            edges.extend(
                (
                    WorkflowEdge(
                        current[0],
                        current[1],
                        merge_node.node_id,
                        "target_prompt",
                    ),
                    WorkflowEdge(
                        merge_current[0],
                        merge_current[1],
                        merge_node.node_id,
                        "source_prompt",
                    ),
                )
            )
            current = (merge_node.node_id, "protein_prompt")
        output = ManagedRoleEndpoint("protein_prompt", current[0], current[1])
        record = ManagedCompositionRecord(
            composition_id=composition_id,
            capability_id=_CAPABILITY_ID,
            normalized_document=evaluated.document,
            managed_node_ids=tuple(node.node_id for node in nodes),
            internal_edges=tuple(edges),
            exposed_inputs=tuple(exposed_inputs),
            exposed_outputs=(output, layout_output),
            confirmed_preview_identity=preview_digest,
        )
        return tuple(nodes), tuple(edges), record, tuple(external_edges)

    def apply(
        self,
        project_id: str,
        *,
        intent: str,
        normalized_document: Mapping[str, Any],
        preview_digest: str,
        composition_id: str | None = None,
    ) -> PromptApplyResult:
        if intent == "create":
            if composition_id is not None:
                raise WorkflowAuthoringError(
                    "malformed_request",
                    "Create does not accept a composition identity",
                    details={"field_path": ["composition_id"]},
                )
        elif composition_id is None:
            raise WorkflowAuthoringError(
                "malformed_request",
                f"{intent.capitalize()} requires a composition identity",
                details={"field_path": ["composition_id"]},
            )
        preview = self.preview(
            project_id,
            normalized_document,
            composition_id=composition_id,
        )
        if preview.diagnostics:
            raise WorkflowAuthoringError(
                "malformed_request",
                "Prompt authoring document has unresolved diagnostics",
                details={
                    "field_path": list(preview.diagnostics[0].field_path)
                },
            )
        if preview.preview_digest != preview_digest:
            raise WorkflowAuthoringError(
                "malformed_request",
                "Confirmed Prompt preview does not match the document",
                details={"field_path": ["preview_digest"]},
            )
        draft = self._workflow_authoring.load_draft(project_id)
        records = list(draft.authoring_compositions)
        existing = (
            None
            if composition_id is None
            else self._record(project_id, composition_id)
        )
        if intent == "delete":
            if existing is None:
                raise WorkflowAuthoringError(
                    "workflow_draft_not_found",
                    "Prompt authoring composition was not found",
                    details={
                        "resource_kind": "authoring_composition",
                        "resource_id": str(composition_id),
                    },
                )
            removed_ids = set(existing.managed_node_ids)
            workflow = WorkflowDocument(
                schema_version=draft.workflow.schema_version,
                workflow_id=draft.workflow.workflow_id,
                nodes=tuple(
                    node
                    for node in draft.workflow.nodes
                    if node.node_id not in removed_ids
                ),
                edges=tuple(
                    edge
                    for edge in draft.workflow.edges
                    if edge.source_node_id not in removed_ids
                    and edge.target_node_id not in removed_ids
                ),
                observation_selectors=draft.workflow.observation_selectors,
                selection_objectives=draft.workflow.selection_objectives,
            )
            records = [
                record
                for record in records
                if record.composition_id != existing.composition_id
            ]
            published = self._workflow_authoring.publish_managed_draft(
                project_id,
                workflow=workflow,
                authoring_compositions=tuple(records),
            )
            return PromptApplyResult(published, None)

        evaluated = self._evaluate(project_id, normalized_document)
        if intent in {"create", "copy"}:
            identity_document = _copy_document(evaluated.document)
            if "project_input_ref" in identity_document["source"]:
                identity_document["source"]["project_input_ref"] = (
                    evaluated.source.facts["content_digest"]
                )
            token = hashlib.sha256(
                canonical_json_bytes(identity_document)
            ).hexdigest()[:24]
            base_composition_id = f"prompt-composition-{token}"
            matching_ordinals = tuple(
                1
                if record.composition_id == base_composition_id
                else int(
                    record.composition_id.removeprefix(
                        f"{base_composition_id}-"
                    )
                )
                for record in records
                if record.composition_id == base_composition_id
                or record.composition_id.startswith(
                    f"{base_composition_id}-"
                )
            )
            target_composition_id = (
                base_composition_id
                if not matching_ordinals
                else f"{base_composition_id}-{max(matching_ordinals) + 1}"
            )
        else:
            if existing is None:
                raise WorkflowAuthoringError(
                    "workflow_draft_not_found",
                    "Prompt authoring composition was not found",
                    details={
                        "resource_kind": "authoring_composition",
                        "resource_id": str(composition_id),
                    },
                )
            target_composition_id = existing.composition_id
        nodes, internal_edges, record, source_external_edges = self._materialize(
            project_id,
            target_composition_id,
            evaluated,
            preview_digest,
        )
        replaced = existing if intent == "replace" else None
        removed_ids = set(
            () if replaced is None else replaced.managed_node_ids
        )
        retained_nodes = tuple(
            node
            for node in draft.workflow.nodes
            if node.node_id not in removed_ids
        )
        retained_edges: list[WorkflowEdge] = []
        external_edges: list[WorkflowEdge] = list(source_external_edges)
        old_inputs = (
            {} if replaced is None else {item.role: item for item in replaced.exposed_inputs}
        )
        old_outputs = (
            {} if replaced is None else {item.role: item for item in replaced.exposed_outputs}
        )
        new_inputs = {item.role: item for item in record.exposed_inputs}
        new_outputs = {item.role: item for item in record.exposed_outputs}
        for edge in draft.workflow.edges:
            source_removed = edge.source_node_id in removed_ids
            target_removed = edge.target_node_id in removed_ids
            if not source_removed and not target_removed:
                retained_edges.append(edge)
                continue
            if source_removed and not target_removed:
                role = next(
                    role
                    for role, endpoint in old_outputs.items()
                    if endpoint.node_id == edge.source_node_id
                    and endpoint.port_name == edge.source_port
                )
                endpoint = new_outputs[role]
                external_edges.append(
                    WorkflowEdge(
                        endpoint.node_id,
                        endpoint.port_name,
                        edge.target_node_id,
                        edge.target_port,
                    )
                )
            elif target_removed and not source_removed:
                role = next(
                    role
                    for role, endpoint in old_inputs.items()
                    if endpoint.node_id == edge.target_node_id
                    and endpoint.port_name == edge.target_port
                )
                endpoint = new_inputs[role]
                external_edges.append(
                    WorkflowEdge(
                        edge.source_node_id,
                        edge.source_port,
                        endpoint.node_id,
                        endpoint.port_name,
                    )
                )
        workflow = WorkflowDocument(
            schema_version=draft.workflow.schema_version,
            workflow_id=draft.workflow.workflow_id,
            nodes=(*retained_nodes, *nodes),
            edges=(*retained_edges, *internal_edges, *external_edges),
            observation_selectors=draft.workflow.observation_selectors,
            selection_objectives=draft.workflow.selection_objectives,
        )
        records = [
            item
            for item in records
            if item.composition_id != target_composition_id
        ]
        records.append(record)
        published = self._workflow_authoring.publish_managed_draft(
            project_id,
            workflow=workflow,
            authoring_compositions=tuple(records),
        )
        return PromptApplyResult(published, _composition_projection(record))
