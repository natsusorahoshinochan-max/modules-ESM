"""Prompt Studio authoring over one ordinary ``prompt_authoring.author`` Node.

Per the 2026-09-02 clean refactor spec (§9.1, §9.2, §12.3, §16) Prompt
Studio edits one ordinary deep Node Instance in a Workflow Draft. The Node's
``document`` node parameter carries the full authoring intent; its external
edges connect real typed Ports (``sequence_source`` / ``structure_source`` /
``prompt_source`` / ``merge_sources``). Preview and execution share exactly
one scientific implementation: :func:`recipe.apply_prompt_recipe`.

No managed composition, no generated subgraph, no external edge rewiring.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import hashlib
import re

from core.catalog.canonical import canonical_json_bytes
from core.project.manager import ProjectInputDescriptor, ProjectManager
from core.workflow.authoring import (
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
from datatypes.prompt import FunctionAnnotation, ProteinPrompt
from datatypes.residue import residue_identity_chain
from datatypes.sequence import ProteinSequence
from datatypes.structure import (
    NamedAtomCoordinates,
    ProteinStructure,
    ResolvedStructureResidueAxis,
)
from modules.structure_transform.csh_normalization import (
    contains_csh_component,
    normalize_csh_parent_span,
)
from modules.structure_transform.projections import select_chains
from modules.structure_transform.residue_axis import resolve_residue_axis

from .recipe import apply_prompt_recipe


_AUTHOR_NODE_TYPE = "prompt_authoring.author"
_TRACK_FIELDS: dict[str, str] = {
    "sequence": "sequence",
    "structure": "coordinates",
    "secondary_structure": "secondary_structure",
    "sasa": "sasa",
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
class PromptApplyResult:
    """The Draft carrying the applied authoring Node Instance."""

    draft: WorkflowDraft


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


def _copy_document(value: Mapping[str, Any]) -> dict[str, Any]:
    return dict(_thaw_json(value))


def _residue_handle(index: int) -> str:
    return f"residue-{index + 1:08d}"


class PromptAuthoringService:
    """The sole open, preview, and apply interface for Prompt Studio."""

    def __init__(
        self,
        projects: ProjectManager,
        workflow_authoring: WorkflowAuthoringService,
    ) -> None:
        self._projects = projects
        self._workflow_authoring = workflow_authoring

    # -- draft / node plumbing ------------------------------------------------ #
    def _require_author_node(
        self,
        project_id: str,
        node_id: str,
    ) -> tuple[WorkflowNodeInstance, WorkflowDraft]:
        draft = self._workflow_authoring.load_draft(project_id)
        for node in draft.workflow.nodes:
            if node.node_id == node_id:
                if node.node_type_id != _AUTHOR_NODE_TYPE:
                    raise WorkflowAuthoringError(
                        "malformed_request",
                        "Prompt Studio can only edit a prompt_authoring.author "
                        "Node Instance",
                        details={"field_path": ["node_id"]},
                    )
                return node, draft
        raise WorkflowAuthoringError(
            "workflow_draft_not_found",
            "Workflow Node Instance was not found",
            details={
                "resource_kind": "workflow_node_instance",
                "resource_id": node_id,
            },
        )

    def _node_by_id(
        self,
        draft: WorkflowDraft,
        node_id: str,
    ) -> WorkflowNodeInstance:
        for node in draft.workflow.nodes:
            if node.node_id == node_id:
                return node
        raise WorkflowAuthoringError(
            "workflow_draft_not_found",
            "Upstream Workflow Node Instance was not found",
            details={
                "resource_kind": "workflow_node_instance",
                "resource_id": node_id,
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

    # -- source resolution (from node edges, not composition) ---------------- #
    def _sequence_from_node(
        self,
        project_id: str,
        node: WorkflowNodeInstance,
        chain_ids: Sequence[str],
    ) -> ProteinSequence:
        _descriptor, payload = self._read_project_input(
            project_id,
            node.node_parameters["project_input_ref"],
        )
        records = _parse_fasta(payload)
        if len(records) != len(chain_ids):
            raise WorkflowAuthoringError(
                "malformed_request",
                "FASTA record count does not match the declared chains",
                details={"field_path": ["document", "chains"]},
            )
        sequence = "".join(sequence for _header, sequence in records)
        residue_ids: list[str] = []
        for (_, seq), chain_id in zip(records, chain_ids, strict=True):
            residue_ids.extend(
                f"{chain_id}:{position + 1}" for position in range(len(seq))
            )
        return ProteinSequence(sequence=sequence, residue_ids=tuple(residue_ids))

    def _structure_from_node(
        self,
        project_id: str,
        node: WorkflowNodeInstance,
        chain_ids: Sequence[str],
    ) -> ResolvedStructureResidueAxis:
        _descriptor, payload = self._read_project_input(
            project_id,
            node.node_parameters["project_input_ref"],
        )
        structure = ProteinStructure(
            payload.decode("utf-8")
            .replace("\r\n", "\n")
            .replace("\r", "\n")
            .rstrip("\n")
            + "\n"
        )
        selected = select_chains(structure, tuple(chain_ids))
        if contains_csh_component(selected):
            selected, normalizations = normalize_csh_parent_span(selected)
            return resolve_residue_axis(selected, normalizations)
        return resolve_residue_axis(selected)

    def _single_incoming_source(
        self,
        draft: WorkflowDraft,
        node_id: str,
        target_port: str,
    ) -> str:
        source_ids = [
            edge.source_node_id
            for edge in draft.workflow.edges
            if edge.target_node_id == node_id
            and edge.target_port == target_port
        ]
        if len(source_ids) != 1:
            raise WorkflowAuthoringError(
                "malformed_request",
                "Prompt source port 'structure_source' is not connected to a "
                "supported upstream Node",
                details={"field_path": ["node_id", "structure_source"]},
            )
        return source_ids[0]

    def _structure_source_from_upstream(
        self,
        project_id: str,
        draft: WorkflowDraft,
        node: WorkflowNodeInstance,
        chain_ids: Sequence[str],
        *,
        depth: int = 0,
    ) -> ResolvedStructureResidueAxis:
        """Replay the project input behind one structure-source subgraph."""
        if depth > 4:
            raise WorkflowAuthoringError(
                "malformed_request",
                "Prompt source port 'structure_source' is not connected to a "
                "supported upstream Node",
                details={"field_path": ["node_id", "structure_source"]},
            )
        if node.node_type_id == "protein_io.import_structure":
            return self._structure_from_node(project_id, node, chain_ids)
        if node.node_type_id == "structure_transform.select_chains":
            declared = tuple(
                node.node_parameters.get("chain_ids") or () or chain_ids
            )
            upstream = self._node_by_id(
                draft,
                self._single_incoming_source(draft, node.node_id, "structure"),
            )
            return self._structure_source_from_upstream(
                project_id, draft, upstream, declared, depth=depth + 1
            )
        if node.node_type_id == "structure_transform.resolve_residue_axis":
            upstream = self._node_by_id(
                draft,
                self._single_incoming_source(draft, node.node_id, "structure"),
            )
            return self._structure_source_from_upstream(
                project_id, draft, upstream, chain_ids, depth=depth + 1
            )
        if node.node_type_id == "structure_transform.normalize_csh_parent_span":
            upstream = self._node_by_id(
                draft,
                self._single_incoming_source(draft, node.node_id, "structure"),
            )
            return self._structure_source_from_upstream(
                project_id, draft, upstream, chain_ids, depth=depth + 1
            )
        raise WorkflowAuthoringError(
            "malformed_request",
            "Prompt source port 'structure_source' is not connected to a "
            "supported upstream Node",
            details={"field_path": ["node_id", "structure_source"]},
        )

    def _prompt_from_author_node(
        self,
        project_id: str,
        draft: WorkflowDraft,
        node: WorkflowNodeInstance,
        visited: set[str],
    ) -> ProteinPrompt:
        if node.node_id in visited:
            raise WorkflowAuthoringError(
                "malformed_request",
                "Prompt sources reference a cycle of author Nodes",
                details={"field_path": ["node_id"]},
            )
        visited.add(node.node_id)
        document = _copy_document(node.node_parameters["document"])
        sources = self._resolve_sources(
            project_id, draft, node, document, visited
        )
        return apply_prompt_recipe(
            sequence_source=sources.sequence_source,
            structure_source=sources.structure_source,
            prompt_source=sources.prompt_source,
            merge_sources=sources.merge_sources,
            document=document,
        )

    def _resolve_sources(
        self,
        project_id: str,
        draft: WorkflowDraft,
        node: WorkflowNodeInstance,
        document: Mapping[str, Any],
        visited: set[str],
    ) -> "_ResolvedSources":
        incoming: dict[str, list[str]] = {}
        for edge in draft.workflow.edges:
            if edge.target_node_id == node.node_id:
                incoming.setdefault(edge.target_port, []).append(
                    edge.source_node_id
                )
        chain_ids = tuple(
            chain["chain_id"] for chain in document.get("chains", ())
        )

        def fail(port: str) -> None:
            raise WorkflowAuthoringError(
                "malformed_request",
                f"Prompt source port {port!r} is not connected to a "
                "supported upstream Node",
                details={"field_path": ["node_id", port]},
            )

        sequence_source: ProteinSequence | None = None
        structure_source: ResolvedStructureResidueAxis | None = None
        prompt_source: ProteinPrompt | None = None
        merge_sources: list[ProteinPrompt] = []

        for source_id in incoming.get("sequence_source", ()):
            upstream = self._node_by_id(draft, source_id)
            if upstream.node_type_id == "protein_io.import_sequence":
                sequence_source = self._sequence_from_node(
                    project_id, upstream, chain_ids
                )
            else:
                fail("sequence_source")
        for source_id in incoming.get("structure_source", ()):
            upstream = self._node_by_id(draft, source_id)
            structure_source = self._structure_source_from_upstream(
                project_id, draft, upstream, chain_ids
            )
        for source_id in incoming.get("prompt_source", ()):
            upstream = self._node_by_id(draft, source_id)
            if upstream.node_type_id == _AUTHOR_NODE_TYPE:
                prompt_source = self._prompt_from_author_node(
                    project_id, draft, upstream, set(visited)
                )
            else:
                fail("prompt_source")
        for source_id in incoming.get("merge_sources", ()):
            upstream = self._node_by_id(draft, source_id)
            if upstream.node_type_id == _AUTHOR_NODE_TYPE:
                merge_sources.append(
                    self._prompt_from_author_node(
                        project_id, draft, upstream, set(visited)
                    )
                )
            else:
                fail("merge_sources")

        if sequence_source is not None and structure_source is not None:
            raise WorkflowAuthoringError(
                "malformed_request",
                "Prompt authoring accepts at most one of sequence_source "
                "and structure_source",
                details={"field_path": ["node_id"]},
            )

        return _ResolvedSources(
            sequence_source=sequence_source,
            structure_source=structure_source,
            prompt_source=prompt_source,
            merge_sources=tuple(merge_sources),
        )

    @staticmethod
    def _source_facts(
        sources: "_ResolvedSources",
        document: Mapping[str, Any],
    ) -> dict[str, Any]:
        if sources.prompt_source is not None:
            return {"kind": "protein_prompt"}
        if sources.structure_source is not None:
            return {"kind": "pdb"}
        if sources.sequence_source is not None:
            return {"kind": "fasta"}
        return {"kind": "blank", "chains": _copy_document(document).get("chains", ())}

    @staticmethod
    def _baseline_prompt(
        sources: "_ResolvedSources",
        document: Mapping[str, Any],
    ) -> ProteinPrompt | None:
        if (
            sources.sequence_source is not None
            or sources.structure_source is not None
            or sources.prompt_source is not None
            or sources.merge_sources
        ):
            return apply_prompt_recipe(
                sequence_source=sources.sequence_source,
                structure_source=sources.structure_source,
                prompt_source=sources.prompt_source,
                merge_sources=sources.merge_sources,
                document={},
            )
        chains = document.get("chains")
        if chains:
            return apply_prompt_recipe(
                sequence_source=None,
                structure_source=None,
                prompt_source=None,
                merge_sources=(),
                document={"chains": list(chains)},
            )
        return None

    # -- projection ----------------------------------------------------------- #
    @staticmethod
    def _project_structure_value(value: NamedAtomCoordinates | None) -> Any:
        if value is None:
            return None
        return {
            "atoms": [
                {
                    "atom_handle": f"atom-{index + 1:04d}",
                    "atom_label": atom_name,
                    "coordinates": list(coordinate),
                }
                for index, (atom_name, coordinate) in enumerate(value.atoms)
            ]
        }

    def _project_prompt(
        self,
        prompt: ProteinPrompt,
        baseline: ProteinPrompt | None,
        sources: "_ResolvedSources",
        document: Mapping[str, Any],
    ) -> tuple[
        tuple[Mapping[str, Any], ...],
        Mapping[str, tuple[Mapping[str, Any], ...]],
        tuple[Mapping[str, Any], ...],
        tuple[Mapping[str, Any], ...],
        Mapping[str, Any],
    ]:
        handle_by_id: dict[str, str] = {}
        residues: list[Mapping[str, Any]] = []
        for index, residue_id in enumerate(prompt.layout.residue_ids):
            handle = _residue_handle(index)
            handle_by_id[residue_id] = handle
            residues.append(
                {
                    "residue_handle": handle,
                    "chain_id": residue_identity_chain(residue_id),
                    "residue_label": residue_id.split(":", 1)[1],
                    "position": index + 1,
                }
            )

        baseline_index: dict[str, int] = {}
        if baseline is not None:
            baseline_index = {
                residue_id: index
                for index, residue_id in enumerate(
                    baseline.layout.residue_ids
                )
            }

        tracks: dict[str, list[Mapping[str, Any]]] = {}
        for track, field in _TRACK_FIELDS.items():
            final_values = getattr(prompt, field)
            baseline_values = (
                getattr(baseline, field) if baseline is not None else None
            )
            projected: list[Mapping[str, Any]] = []
            for index, residue_id in enumerate(prompt.layout.residue_ids):
                final_value = (
                    None if final_values is None else final_values[index]
                )
                if track == "structure":
                    value = self._project_structure_value(final_value)
                else:
                    value = final_value
                if baseline is None:
                    state = "source"
                elif residue_id not in baseline_index:
                    state = "inserted"
                else:
                    base_value = (
                        None
                        if baseline_values is None
                        else baseline_values[baseline_index[residue_id]]
                    )
                    if base_value == final_value:
                        state = "current"
                    elif final_value is None:
                        state = "cleared"
                    else:
                        state = "changed"
                projected.append(
                    {
                        "residue_handle": handle_by_id[residue_id],
                        "value": value,
                        "state": state,
                    }
                )
            tracks[track] = projected

        function_annotations: list[Mapping[str, Any]] = []
        for annotation in prompt.function_annotations:
            function_annotations.append(
                {
                    "label": annotation.label,
                    "start_residue_handle": handle_by_id[
                        annotation.start_residue_id
                    ],
                    "end_residue_handle": handle_by_id[
                        annotation.end_residue_id
                    ],
                    "state": "source",
                }
            )

        changes: list[Mapping[str, Any]] = []
        if baseline is not None:
            base_ids = set(baseline.layout.residue_ids)
            final_ids = set(prompt.layout.residue_ids)
            changes.append(
                {
                    "kind": "layout",
                    "source_length": baseline.layout.length,
                    "target_length": prompt.layout.length,
                    "inserted_count": len(final_ids - base_ids),
                    "deleted_count": len(base_ids - final_ids),
                }
            )

        chain_order = prompt.layout.chain_ids
        chain_lengths = {
            chain_id: sum(
                residue_identity_chain(rid) == chain_id
                for rid in prompt.layout.residue_ids
            )
            for chain_id in chain_order
        }
        track_summary: dict[str, Mapping[str, int]] = {}
        for track, field in _TRACK_FIELDS.items():
            values = getattr(prompt, field)
            specified = (
                0 if values is None else sum(v is not None for v in values)
            )
            track_summary[track] = {
                "specified": specified,
                "unspecified": prompt.layout.length - specified,
            }
        summary = {
            "chains": [
                {"chain_id": chain_id, "length": chain_lengths[chain_id]}
                for chain_id in chain_order
            ],
            "tracks": track_summary,
            "function_annotation_count": len(prompt.function_annotations),
        }

        _ = sources
        _ = document
        return (
            tuple(residues),
            tracks,
            tuple(function_annotations),
            tuple(changes),
            summary,
        )

    def _project_source_merges(
        self,
        sources: "_ResolvedSources",
        document: Mapping[str, Any],
    ) -> tuple[Mapping[str, Any], ...]:
        merges = document.get("source_merges") or ()
        result: list[Mapping[str, Any]] = []
        for merge in merges:
            result.append(
                {
                    "source": {"kind": "protein_prompt"},
                    "correspondence": _copy_document(
                        merge.get("correspondence", ())
                    ),
                    "track_decisions": _copy_document(
                        merge.get("track_decisions", {})
                    ),
                    "confirmed": bool(merge.get("confirmed", False)),
                }
            )
        return tuple(result)

    # -- public operations ---------------------------------------------------- #
    def open(
        self,
        project_id: str,
        request: Mapping[str, Any],
    ) -> PromptAuthoringSnapshot:
        node, draft = self._require_author_node(
            project_id, request["node_id"]
        )
        document = _copy_document(node.node_parameters["document"])
        sources = self._resolve_sources(
            project_id, draft, node, document, set()
        )
        baseline = self._baseline_prompt(sources, document)
        if baseline is None:
            return PromptAuthoringSnapshot(
                document=document,
                residues=(),
                tracks={track: () for track in _TRACK_FIELDS},
                function_annotations=(),
                source=self._source_facts(sources, document),
            )
        residues, tracks, annotations, _changes, _summary = self._project_prompt(
            baseline, baseline, sources, document
        )
        return PromptAuthoringSnapshot(
            document=document,
            residues=residues,
            tracks=tracks,
            function_annotations=annotations,
            source=self._source_facts(sources, document),
        )

    def preview(
        self,
        project_id: str,
        request: Mapping[str, Any],
    ) -> PromptAuthoringPreview:
        node, draft = self._require_author_node(
            project_id, request["node_id"]
        )
        stored = _copy_document(node.node_parameters["document"])
        document = _copy_document(request.get("document") or stored)
        sources = self._resolve_sources(
            project_id, draft, node, document, set()
        )
        try:
            baseline = self._baseline_prompt(sources, document)
            final = apply_prompt_recipe(
                sequence_source=sources.sequence_source,
                structure_source=sources.structure_source,
                prompt_source=sources.prompt_source,
                merge_sources=sources.merge_sources,
                document=document,
            )
        except ValueError as error:
            return PromptAuthoringPreview(
                normalized_document=document,
                preview_digest="sha256:" + hashlib.sha256(
                    canonical_json_bytes(
                        {"normalized_document": document}
                    )
                ).hexdigest(),
                residues=(),
                tracks={track: () for track in _TRACK_FIELDS},
                function_annotations=(),
                changes=(),
                random_selections=(),
                source_merges=(),
                diagnostics=(
                    PromptAuthoringDiagnostic(
                        "recipe_error", str(error), ("document",)
                    ),
                ),
                summary={},
            )

        (
            residues,
            tracks,
            annotations,
            changes,
            summary,
        ) = self._project_prompt(final, baseline, sources, document)
        source_merges = self._project_source_merges(sources, document)
        preview_digest = "sha256:" + hashlib.sha256(
            canonical_json_bytes(
                {
                    "normalized_document": document,
                    "source_facts": self._source_facts(sources, document),
                }
            )
        ).hexdigest()
        return PromptAuthoringPreview(
            normalized_document=document,
            preview_digest=preview_digest,
            residues=residues,
            tracks=tracks,
            function_annotations=annotations,
            changes=changes,
            random_selections=(),
            source_merges=source_merges,
            diagnostics=(),
            summary=summary,
        )

    def apply(
        self,
        project_id: str,
        request: Mapping[str, Any],
    ) -> PromptApplyResult:
        node, _draft = self._require_author_node(
            project_id, request["node_id"]
        )
        document = _copy_document(request["document"])
        parameters = dict(_thaw_json(node.node_parameters))
        parameters["document"] = document
        draft = self._workflow_authoring.update_node_parameters(
            project_id,
            node_id=node.node_id,
            node_parameters=parameters,
        )
        return PromptApplyResult(draft=draft)


@dataclass(frozen=True, slots=True)
class _ResolvedSources:
    """Resolved input values for one author Node Instance."""

    sequence_source: ProteinSequence | None
    structure_source: ResolvedStructureResidueAxis | None
    prompt_source: ProteinPrompt | None
    merge_sources: tuple[ProteinPrompt, ...]
