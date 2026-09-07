"""Prompt Studio authoring over one ordinary ``prompt_authoring.author`` Node.

The service resolves only the provider-free source paths needed by Prompt
Studio. Scientific evaluation remains owned by :mod:`recipe`; this module
only resolves visible Workflow values and projects the evaluated result.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
import hashlib
from typing import Any, NoReturn, cast

from core.catalog.canonical import canonical_json_bytes
from core.catalog.model import FrozenCatalog
from core.catalog.declarations import NodeTypeDefinition
from core.parameters.contract import admit_values, ParameterValueAdmissionError
from core.project.manager import ProjectInputDescriptor, ProjectManager
from core.workflow.authoring import (
    WorkflowAuthoringError,
    WorkflowAuthoringService,
    WorkflowDraft,
)
from core.workflow.document import (
    WorkflowEdge,
    WorkflowNodeInstance,
    _thaw_json,
)
from datatypes.prompt import FunctionAnnotation, FunctionAnnotationTrack, ProteinPrompt
from datatypes.residue import (
    ModifiedResidueNormalizationCollection,
    ResidueTrack,
    residue_identity_chain,
)
from datatypes.sequence import ProteinSequence, validate_protein_sequence
from datatypes.structure import (
    NamedAtomCoordinates,
    ProteinStructure,
    ResolvedStructureResidueAxis,
)
from modules.protein_io.fasta import parse_fasta_sequence
from modules.residue_data.implementation import materialize_sequence
from modules.structure_transform.csh_normalization import normalize_csh_parent_span
from modules.structure_transform.projections import extract_sequence, select_chains
from modules.structure_transform.residue_axis import resolve_residue_axis

from .prompt_types import PROTEIN_PROMPT_PORT_TYPE
from .prompts import assemble_protein_prompt, decompose_protein_prompt
from .recipe import _evaluate_prompt_recipe


_AUTHOR_NODE_TYPE = "prompt_authoring.author"
_TRACK_FIELDS: dict[str, str] = {
    "sequence": "sequence",
    "coordinates": "coordinates",
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
    tracks: Mapping[str, Mapping[str, Any]]
    function_annotations: tuple[Mapping[str, Any], ...]
    source: Mapping[str, Any]
    baseline_diagnostics: tuple[PromptAuthoringDiagnostic, ...]
    random_selections: tuple[Mapping[str, Any], ...]


@dataclass(frozen=True, slots=True)
class PromptAuthoringPreview:
    """One non-executable complete authoring preview."""

    normalized_document: Mapping[str, Any]
    preview_digest: str
    residues: tuple[Mapping[str, Any], ...]
    tracks: Mapping[str, Mapping[str, Any]]
    function_annotations: tuple[Mapping[str, Any], ...]
    changes: tuple[Mapping[str, Any], ...]
    random_selections: tuple[Mapping[str, Any], ...]
    source_merges: tuple[Mapping[str, Any], ...]
    diagnostics: tuple[PromptAuthoringDiagnostic, ...]
    baseline_diagnostics: tuple[PromptAuthoringDiagnostic, ...]
    summary: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class PromptApplyResult:
    """The Draft carrying the applied authoring Node Instance."""

    draft: WorkflowDraft


@dataclass(frozen=True, slots=True)
class _StructureValue:
    value: ProteinStructure
    descriptor: ProjectInputDescriptor


@dataclass(frozen=True, slots=True)
class _AxisValue:
    value: ResolvedStructureResidueAxis
    descriptor: ProjectInputDescriptor


@dataclass(frozen=True, slots=True)
class _ResolvedSources:
    """Resolved input values and exact source facts for one author Node."""

    sequence_source: ProteinSequence | None
    structure_source: ResolvedStructureResidueAxis | None
    prompt_source: ProteinPrompt | None
    merge_sources: tuple[ProteinPrompt, ...]
    source_facts: Mapping[str, Any]
    merge_source_facts: tuple[Mapping[str, Any], ...]


def _copy_document(value: Mapping[str, Any]) -> dict[str, Any]:
    return dict(_thaw_json(value))


def _normalize_document(value: Mapping[str, Any]) -> dict[str, Any]:
    """Return the one persisted Prompt authoring dialect."""
    document = _copy_document(value)
    edits = document.get("track_edits")
    if edits is not None:
        for edit in edits:
            if (
                edit.get("track") == "secondary_structure"
                and edit.get("action") == "replace"
                and edit.get("value") == "-"
            ):
                edit["value"] = "C"
    return document


def _residue_handle(residue_id: str) -> str:
    digest = hashlib.sha256(residue_id.encode("utf-8")).hexdigest()
    return f"residue-{digest}"


def _prompt_facts(prompt: ProteinPrompt) -> dict[str, Any]:
    return {
        "kind": "protein_prompt",
        "content_digest": PROTEIN_PROMPT_PORT_TYPE.content_digest(prompt),
        "chain_ids": list(prompt.layout.chain_ids),
    }


def _empty_tracks() -> dict[str, Mapping[str, Any]]:
    return {
        track: {"present": False, "values": ()}
        for track in _TRACK_FIELDS
    }


def _empty_summary() -> dict[str, Any]:
    return {
        "chains": [],
        "tracks": {
            track: {"specified": 0, "unspecified": 0}
            for track in _TRACK_FIELDS
        },
        "function_annotation_count": 0,
    }


class PromptAuthoringService:
    """The sole open, preview, and apply interface for Prompt Studio."""

    def __init__(
        self,
        projects: ProjectManager,
        workflow_authoring: WorkflowAuthoringService,
        catalog: FrozenCatalog,
    ) -> None:
        self._catalog = catalog
        self._projects = projects
        self._workflow_authoring = workflow_authoring

    def _require_author_node(
        self,
        project_id: str,
        node_id: str,
    ) -> tuple[WorkflowNodeInstance, WorkflowDraft]:
        draft = self._workflow_authoring.load_draft(project_id)
        for node in draft.workflow.nodes:
            if node.node_id != node_id:
                continue
            if node.node_type_id != _AUTHOR_NODE_TYPE:
                raise WorkflowAuthoringError(
                    "malformed_request",
                    "Prompt Studio can only edit a prompt_authoring.author "
                    "Node Instance",
                    details={"field_path": ["node_id"]},
                )
            return self._admit_node(node), draft
        raise WorkflowAuthoringError(
            "workflow_draft_not_found",
            "Workflow Node Instance was not found",
            details={
                "resource_kind": "workflow_node_instance",
                "resource_id": node_id,
            },
        )

    def _admit_node(self, node: WorkflowNodeInstance) -> WorkflowNodeInstance:
        definition = cast(NodeTypeDefinition, self._catalog.require_contract("node_type", node.node_type_id).definition)
        try:
            parameters = admit_values(definition.parameter_contract, node.node_parameters)
        except ParameterValueAdmissionError as error:
            raise WorkflowAuthoringError(
                "malformed_request", error.reason,
                details={"field_path": ["nodes", node.node_id, "node_parameters", *error.path]},
            ) from error
        return replace(node, node_parameters=parameters)

    def _node_by_id(
        self,
        draft: WorkflowDraft,
        node_id: str,
    ) -> WorkflowNodeInstance:
        for node in draft.workflow.nodes:
            if node.node_id == node_id:
                return self._admit_node(node)
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

    @staticmethod
    def _incoming_edges(
        draft: WorkflowDraft,
        node_id: str,
        target_port: str,
    ) -> tuple[WorkflowEdge, ...]:
        return tuple(
            edge
            for edge in draft.workflow.edges
            if edge.target_node_id == node_id and edge.target_port == target_port
        )

    def _one_incoming_edge(
        self,
        draft: WorkflowDraft,
        node_id: str,
        target_port: str,
        *,
        required: bool,
    ) -> WorkflowEdge | None:
        edges = self._incoming_edges(draft, node_id, target_port)
        if len(edges) == 1:
            return edges[0]
        if not edges and not required:
            return None
        self._unsupported_source(target_port)

    @staticmethod
    def _unsupported_source(port: str) -> NoReturn:
        raise WorkflowAuthoringError(
            "malformed_request",
            f"Prompt source port {port!r} is not connected to one supported "
            "upstream output",
            details={"field_path": ["node_id", port]},
        )

    @staticmethod
    def _assert_not_visited(
        node: WorkflowNodeInstance,
        visited: frozenset[str],
    ) -> frozenset[str]:
        if node.node_id in visited:
            raise WorkflowAuthoringError(
                "malformed_request",
                "Prompt sources reference a cycle",
                details={"field_path": ["node_id"]},
            )
        return visited | {node.node_id}

    # -- exact provider-free source evaluation ----------------------------- #
    def _sequence_from_import(
        self,
        project_id: str,
        node: WorkflowNodeInstance,
    ) -> tuple[ProteinSequence, ProjectInputDescriptor]:
        descriptor, payload = self._read_project_input(
            project_id,
            node.node_parameters["project_input_ref"],
        )
        return validate_protein_sequence(ProteinSequence(parse_fasta_sequence(payload))), descriptor

    def _structure_from_import(
        self,
        project_id: str,
        node: WorkflowNodeInstance,
    ) -> _StructureValue:
        descriptor, payload = self._read_project_input(
            project_id,
            node.node_parameters["project_input_ref"],
        )
        text = payload.decode("utf-8")
        canonical = text.replace("\r\n", "\n").replace("\r", "\n")
        return _StructureValue(
            ProteinStructure(canonical.rstrip("\n") + "\n"),
            descriptor,
        )

    def _structure_value_from_edge(
        self,
        project_id: str,
        draft: WorkflowDraft,
        edge: WorkflowEdge,
        visited: frozenset[str],
    ) -> _StructureValue:
        node = self._node_by_id(draft, edge.source_node_id)
        next_visited = self._assert_not_visited(node, visited)
        if node.node_type_id == "protein_io.import_structure":
            if edge.source_port != "structure":
                self._unsupported_source(edge.target_port)
            return self._structure_from_import(project_id, node)
        if node.node_type_id == "structure_transform.select_chains":
            if edge.source_port != "structure":
                self._unsupported_source(edge.target_port)
            upstream = self._one_incoming_edge(
                draft, node.node_id, "structure", required=True
            )
            assert upstream is not None
            source = self._structure_value_from_edge(
                project_id, draft, upstream, next_visited
            )
            return _StructureValue(
                select_chains(source.value, tuple(node.node_parameters["chain_ids"])),
                source.descriptor,
            )
        if node.node_type_id == "structure_transform.normalize_csh_parent_span":
            if edge.source_port != "structure":
                self._unsupported_source(edge.target_port)
            upstream = self._one_incoming_edge(
                draft, node.node_id, "structure", required=True
            )
            assert upstream is not None
            source = self._structure_value_from_edge(
                project_id, draft, upstream, next_visited
            )
            normalized, _normalizations = normalize_csh_parent_span(source.value)
            return _StructureValue(normalized, source.descriptor)
        self._unsupported_source(edge.target_port)

    def _normalizations_from_edge(
        self,
        project_id: str,
        draft: WorkflowDraft,
        edge: WorkflowEdge,
        visited: frozenset[str],
    ) -> ModifiedResidueNormalizationCollection:
        node = self._node_by_id(draft, edge.source_node_id)
        next_visited = self._assert_not_visited(node, visited)
        if (
            node.node_type_id
            != "structure_transform.normalize_csh_parent_span"
            or edge.source_port != "modified_residue_normalizations"
        ):
            self._unsupported_source(edge.target_port)
        upstream = self._one_incoming_edge(
            draft, node.node_id, "structure", required=True
        )
        assert upstream is not None
        source = self._structure_value_from_edge(
            project_id, draft, upstream, next_visited
        )
        _structure, normalizations = normalize_csh_parent_span(source.value)
        return normalizations

    def _axis_value_from_edge(
        self,
        project_id: str,
        draft: WorkflowDraft,
        edge: WorkflowEdge,
        visited: frozenset[str],
    ) -> _AxisValue:
        node = self._node_by_id(draft, edge.source_node_id)
        next_visited = self._assert_not_visited(node, visited)
        if (
            node.node_type_id != "structure_transform.resolve_residue_axis"
            or edge.source_port != "residue_axis"
        ):
            self._unsupported_source(edge.target_port)
        structure_edge = self._one_incoming_edge(
            draft, node.node_id, "structure", required=True
        )
        assert structure_edge is not None
        structure = self._structure_value_from_edge(
            project_id, draft, structure_edge, next_visited
        )
        normalizations_edge = self._one_incoming_edge(
            draft,
            node.node_id,
            "modified_residue_normalizations",
            required=False,
        )
        normalizations = (
            None
            if normalizations_edge is None
            else self._normalizations_from_edge(
                project_id, draft, normalizations_edge, next_visited
            )
        )
        return _AxisValue(
            resolve_residue_axis(structure.value, normalizations),
            structure.descriptor,
        )

    def _prompt_value_from_edge(
        self,
        project_id: str,
        draft: WorkflowDraft,
        edge: WorkflowEdge,
        visited: frozenset[str],
    ) -> ProteinPrompt:
        node = self._node_by_id(draft, edge.source_node_id)
        next_visited = self._assert_not_visited(node, visited)
        if edge.source_port != "protein_prompt":
            self._unsupported_source(edge.target_port)
        if node.node_type_id == _AUTHOR_NODE_TYPE:
            document = _normalize_document(node.node_parameters["document"])
            sources = self._resolve_sources(
                project_id, draft, node, document, next_visited
            )
            prompt, _trace = _evaluate_prompt_recipe(
                sequence_source=sources.sequence_source,
                structure_source=sources.structure_source,
                prompt_source=sources.prompt_source,
                merge_sources=sources.merge_sources,
                document=document,
            )
            return prompt
        if node.node_type_id == "prompt_authoring.assemble":
            return self._assemble_prompt(
                project_id, draft, node, next_visited
            )
        self._unsupported_source(edge.target_port)

    def _decomposed_value_from_edge(
        self,
        project_id: str,
        draft: WorkflowDraft,
        edge: WorkflowEdge,
        expected_port: str,
        visited: frozenset[str],
    ) -> ResidueTrack[Any] | FunctionAnnotationTrack | None:
        node = self._node_by_id(draft, edge.source_node_id)
        next_visited = self._assert_not_visited(node, visited)
        if (
            node.node_type_id != "prompt_authoring.decompose"
            or edge.source_port != expected_port
        ):
            self._unsupported_source(edge.target_port)
        prompt_edge = self._one_incoming_edge(
            draft, node.node_id, "protein_prompt", required=True
        )
        assert prompt_edge is not None
        prompt = self._prompt_value_from_edge(
            project_id, draft, prompt_edge, next_visited
        )
        outputs = decompose_protein_prompt(prompt)
        if expected_port in ("secondary_structure", "sasa"):
            return outputs.get(expected_port)
        return outputs[expected_port]

    def _assemble_prompt(
        self,
        project_id: str,
        draft: WorkflowDraft,
        node: WorkflowNodeInstance,
        visited: frozenset[str],
    ) -> ProteinPrompt:
        sequence_edge = self._one_incoming_edge(
            draft, node.node_id, "sequence", required=True
        )
        coordinates_edge = self._one_incoming_edge(
            draft, node.node_id, "coordinates", required=True
        )
        annotations_edge = self._one_incoming_edge(
            draft, node.node_id, "function_annotations", required=True
        )
        assert sequence_edge is not None
        assert coordinates_edge is not None
        assert annotations_edge is not None
        sequence = self._decomposed_value_from_edge(
            project_id, draft, sequence_edge, "sequence", visited
        )
        coordinates = self._decomposed_value_from_edge(
            project_id, draft, coordinates_edge, "coordinates", visited
        )
        annotations = self._decomposed_value_from_edge(
            project_id,
            draft,
            annotations_edge,
            "function_annotations",
            visited,
        )
        assert type(sequence) is ResidueTrack
        assert type(coordinates) is ResidueTrack
        assert type(annotations) is FunctionAnnotationTrack
        tracks: dict[str, ResidueTrack[Any] | None] = {
            "sequence": sequence,
            "coordinates": coordinates,
        }
        for port in ("secondary_structure", "sasa"):
            edge = self._one_incoming_edge(
                draft, node.node_id, port, required=False
            )
            if edge is not None:
                value = self._decomposed_value_from_edge(
                    project_id, draft, edge, port, visited
                )
                assert value is None or type(value) is ResidueTrack
                tracks[port] = value
        return assemble_protein_prompt(
            sequence,
            coordinates,
            annotations,
            secondary_structure_track=tracks.get("secondary_structure"),
            sasa_track=tracks.get("sasa"),
        )

    def _sequence_value_from_edge(
        self,
        project_id: str,
        draft: WorkflowDraft,
        edge: WorkflowEdge,
        document: Mapping[str, Any],
        visited: frozenset[str],
    ) -> tuple[ProteinSequence, Mapping[str, Any]]:
        node = self._node_by_id(draft, edge.source_node_id)
        next_visited = self._assert_not_visited(node, visited)
        if node.node_type_id == "protein_io.import_sequence":
            if edge.source_port != "sequence":
                self._unsupported_source(edge.target_port)
            sequence, descriptor = self._sequence_from_import(project_id, node)
            return sequence, {
                "kind": "fasta",
                "project_input_ref": descriptor.project_input_ref,
                "content_digest": descriptor.content_digest,
                "chain_ids": [
                    chain["chain_id"] for chain in document.get("chains", ())
                ],
            }
        if node.node_type_id == "residue_data.materialize_sequence":
            if edge.source_port != "sequence":
                self._unsupported_source(edge.target_port)
            sequence_edge = self._one_incoming_edge(
                draft, node.node_id, "sequence", required=True
            )
            assert sequence_edge is not None
            track = self._decomposed_value_from_edge(
                project_id, draft, sequence_edge, "sequence", next_visited
            )
            assert type(track) is ResidueTrack
            sequence = materialize_sequence(track)
            prompt_edge = self._one_incoming_edge(
                draft,
                sequence_edge.source_node_id,
                "protein_prompt",
                required=True,
            )
            assert prompt_edge is not None
            prompt = self._prompt_value_from_edge(
                project_id, draft, prompt_edge, next_visited
            )
            return sequence, _prompt_facts(prompt)
        if node.node_type_id == "structure_transform.extract_sequence":
            if edge.source_port != "sequence":
                self._unsupported_source(edge.target_port)
            axis_edge = self._one_incoming_edge(
                draft, node.node_id, "residue_axis", required=True
            )
            assert axis_edge is not None
            axis = self._axis_value_from_edge(
                project_id, draft, axis_edge, next_visited
            )
            return extract_sequence(axis.value), {
                "kind": "pdb",
                "project_input_ref": axis.descriptor.project_input_ref,
                "content_digest": axis.descriptor.content_digest,
                "chain_ids": list(axis.value.layout.chain_ids),
            }
        self._unsupported_source(edge.target_port)

    def _resolve_sources(
        self,
        project_id: str,
        draft: WorkflowDraft,
        node: WorkflowNodeInstance,
        document: Mapping[str, Any],
        visited: frozenset[str],
    ) -> _ResolvedSources:
        try:
            return self._resolve_source_values(project_id, draft, node, document, visited)
        except ValueError as error:
            raise WorkflowAuthoringError(
                "malformed_request", str(error),
                details={"field_path": ["nodes", node.node_id, "inputs"]},
            ) from error

    def _resolve_source_values(
        self,
        project_id: str,
        draft: WorkflowDraft,
        node: WorkflowNodeInstance,
        document: Mapping[str, Any],
        visited: frozenset[str],
    ) -> _ResolvedSources:
        sequence_edges = self._incoming_edges(
            draft, node.node_id, "sequence_source"
        )
        structure_edges = self._incoming_edges(
            draft, node.node_id, "structure_source"
        )
        prompt_edges = self._incoming_edges(
            draft, node.node_id, "prompt_source"
        )
        for port, edges in (
            ("sequence_source", sequence_edges),
            ("structure_source", structure_edges),
            ("prompt_source", prompt_edges),
        ):
            if len(edges) > 1:
                self._unsupported_source(port)
        if sum(bool(edges) for edges in (sequence_edges, structure_edges, prompt_edges)) > 1:
            raise WorkflowAuthoringError(
                "malformed_request",
                "Prompt authoring accepts at most one primary source",
                details={"field_path": ["node_id"]},
            )

        sequence_source: ProteinSequence | None = None
        structure_source: ResolvedStructureResidueAxis | None = None
        prompt_source: ProteinPrompt | None = None
        source_facts: Mapping[str, Any]
        if sequence_edges:
            sequence_source, source_facts = self._sequence_value_from_edge(
                project_id,
                draft,
                sequence_edges[0],
                document,
                visited,
            )
        elif structure_edges:
            axis = self._axis_value_from_edge(
                project_id, draft, structure_edges[0], visited
            )
            structure_source = axis.value
            source_facts = {
                "kind": "pdb",
                "project_input_ref": axis.descriptor.project_input_ref,
                "content_digest": axis.descriptor.content_digest,
                "chain_ids": list(axis.value.layout.chain_ids),
            }
        elif prompt_edges:
            prompt_source = self._prompt_value_from_edge(
                project_id, draft, prompt_edges[0], visited
            )
            source_facts = _prompt_facts(prompt_source)
        else:
            source_facts = {
                "kind": "blank",
                "chains": _copy_document(document).get("chains", []),
            }

        merge_sources: list[ProteinPrompt] = []
        merge_source_facts: list[Mapping[str, Any]] = []
        for edge in self._incoming_edges(draft, node.node_id, "merge_sources"):
            source = self._prompt_value_from_edge(
                project_id, draft, edge, visited
            )
            merge_sources.append(source)
            merge_source_facts.append(_prompt_facts(source))

        return _ResolvedSources(
            sequence_source,
            structure_source,
            prompt_source,
            tuple(merge_sources),
            source_facts,
            tuple(merge_source_facts),
        )

    # -- protocol projection ------------------------------------------------ #
    @staticmethod
    def _project_coordinates(
        value: NamedAtomCoordinates | None,
    ) -> Any:
        if value is None:
            return None
        return {
            "atoms": [
                {
                    "atom_handle": f"atom-{index + 1:04d}",
                    "atom_name": atom_name,
                    "coordinates": list(coordinate),
                }
                for index, (atom_name, coordinate) in enumerate(value.atoms)
            ]
        }

    @staticmethod
    def _display_axis(
        baseline: ProteinPrompt | None,
        final: ProteinPrompt,
    ) -> tuple[str, ...]:
        if baseline is None:
            return tuple(final.layout.residue_ids)
        before = tuple(baseline.layout.residue_ids)
        after = tuple(final.layout.residue_ids)
        surviving = set(after)
        # Attach each tombstone to its next surviving baseline neighbour.
        next_by_chain: dict[str, str] = {}
        before_anchor: dict[str, list[str]] = {}
        chain_tail: dict[str, list[str]] = {}
        for residue_id in reversed(before):
            chain = residue_identity_chain(residue_id)
            if residue_id in surviving:
                next_by_chain[chain] = residue_id
            elif chain in next_by_chain:
                before_anchor.setdefault(next_by_chain[chain], []).append(residue_id)
            else:
                chain_tail.setdefault(chain, []).append(residue_id)
        last_by_chain = {residue_identity_chain(residue_id): residue_id for residue_id in after}
        result: list[str] = []
        for residue_id in after:
            result.extend(reversed(before_anchor.get(residue_id, ())))
            result.append(residue_id)
            chain = residue_identity_chain(residue_id)
            if last_by_chain[chain] == residue_id:
                result.extend(reversed(chain_tail.get(chain, ())))
        result.extend(residue_id for residue_id in before if residue_identity_chain(residue_id) not in last_by_chain)
        return tuple(result)

    @staticmethod
    def _annotation_key(annotation: FunctionAnnotation) -> tuple[str, str, str]:
        return (
            annotation.label,
            annotation.start_residue_id,
            annotation.end_residue_id,
        )

    def _project_prompt(
        self,
        prompt: ProteinPrompt,
        baseline: ProteinPrompt | None,
    ) -> tuple[
        tuple[Mapping[str, Any], ...],
        Mapping[str, Mapping[str, Any]],
        tuple[Mapping[str, Any], ...],
        tuple[Mapping[str, Any], ...],
        Mapping[str, Any],
    ]:
        display_ids = self._display_axis(baseline, prompt)
        final_index = {
            residue_id: index
            for index, residue_id in enumerate(prompt.layout.residue_ids)
        }
        baseline_index = (
            {}
            if baseline is None
            else {
                residue_id: index
                for index, residue_id in enumerate(baseline.layout.residue_ids)
            }
        )
        display_index = {
            residue_id: index for index, residue_id in enumerate(display_ids)
        }
        handles = {
            residue_id: _residue_handle(residue_id) for residue_id in display_ids
        }
        residues: list[Mapping[str, Any]] = []
        for index, residue_id in enumerate(display_ids):
            if residue_id not in final_index:
                state = "pending-delete"
            elif residue_id not in baseline_index and baseline is not None:
                state = "inserted"
            else:
                state = "current"
            residues.append(
                {
                    "residue_handle": handles[residue_id],
                    "residue_id": residue_id,
                    "chain_id": residue_identity_chain(residue_id),
                    "residue_label": residue_id.split(":", 1)[1],
                    "position": index + 1,
                    "state": state,
                }
            )

        tracks: dict[str, Mapping[str, Any]] = {}
        for track, field in _TRACK_FIELDS.items():
            final_values = getattr(prompt, field)
            baseline_values = None if baseline is None else getattr(baseline, field)
            projected: list[Mapping[str, Any]] = []
            for residue_id in display_ids:
                final_position = final_index.get(residue_id)
                baseline_position = baseline_index.get(residue_id)
                if final_position is None:
                    value = (
                        None
                        if baseline_values is None
                        else baseline_values[baseline_position]
                    )
                    state = "pending-delete"
                elif baseline is not None and baseline_position is None:
                    value = (
                        None if final_values is None else final_values[final_position]
                    )
                    state = "inserted"
                elif baseline is not None and baseline_values is not None and final_values is None:
                    value = baseline_values[baseline_position]
                    state = "pending-delete"
                else:
                    value = (
                        None if final_values is None else final_values[final_position]
                    )
                    baseline_value = (
                        None
                        if baseline_values is None
                        else baseline_values[baseline_position]
                    )
                    if baseline is None or value == baseline_value:
                        state = "current"
                    elif value is None:
                        state = "cleared"
                    else:
                        state = "changed"
                if track == "coordinates":
                    value = self._project_coordinates(value)
                projected.append(
                    {
                        "residue_handle": handles[residue_id],
                        "value": value,
                        "state": state,
                    }
                )
            tracks[track] = {
                "present": final_values is not None,
                "values": tuple(projected),
            }

        baseline_annotations = (
            () if baseline is None else tuple(baseline.function_annotations)
        )
        final_annotations = tuple(prompt.function_annotations)
        baseline_keys = {self._annotation_key(item) for item in baseline_annotations}
        final_keys = {self._annotation_key(item) for item in final_annotations}
        annotation_union = list(baseline_annotations)
        annotation_union.extend(
            item
            for item in final_annotations
            if self._annotation_key(item) not in baseline_keys
        )
        annotation_union.sort(
            key=lambda item: (
                display_index[item.start_residue_id],
                display_index[item.end_residue_id],
                item.label,
            )
        )
        annotations: list[Mapping[str, Any]] = []
        for annotation in annotation_union:
            key = self._annotation_key(annotation)
            state = (
                "current"
                if key in baseline_keys and key in final_keys
                else "inserted"
                if key in final_keys
                else "pending-delete"
            )
            annotations.append(
                {
                    "label": annotation.label,
                    "start_residue_handle": handles[
                        annotation.start_residue_id
                    ],
                    "end_residue_handle": handles[
                        annotation.end_residue_id
                    ],
                    "state": state,
                }
            )

        changes: list[Mapping[str, Any]] = []
        if baseline is not None:
            common = set(baseline_index) & set(final_index)
            if ([r for r in baseline_index if r in common]
                    != [r for r in final_index if r in common]):
                changes.append({
                    "kind": "residue_order", "action": "replace",
                    "before_residue_handles": [handles[r] for r in baseline_index],
                    "after_residue_handles": [handles[r] for r in final_index],
                })
            for residue_id in display_ids:
                if residue_id not in baseline_index:
                    changes.append(
                        {
                            "kind": "residue",
                            "action": "insert",
                            "residue_handle": handles[residue_id],
                        }
                    )
                elif residue_id not in final_index:
                    changes.append(
                        {
                            "kind": "residue",
                            "action": "delete",
                            "residue_handle": handles[residue_id],
                        }
                    )
            common_ids = tuple(
                residue_id
                for residue_id in display_ids
                if residue_id in baseline_index and residue_id in final_index
            )
            for track, field in _TRACK_FIELDS.items():
                before_values = getattr(baseline, field)
                after_values = getattr(prompt, field)
                if (before_values is None) != (after_values is None):
                    changes.append(
                        {
                            "kind": "track_presence",
                            "track": track,
                            "action": (
                                "insert" if after_values is not None else "delete"
                            ),
                        }
                    )
                    continue
                if before_values is None or after_values is None:
                    continue
                for residue_id in common_ids:
                    before_value = before_values[baseline_index[residue_id]]
                    after_value = after_values[final_index[residue_id]]
                    if before_value == after_value:
                        continue
                    changes.append(
                        {
                            "kind": "track_value",
                            "track": track,
                            "residue_handle": handles[residue_id],
                            "action": (
                                "clear" if after_value is None else "replace"
                            ),
                        }
                    )
            for annotation in baseline_annotations:
                if self._annotation_key(annotation) not in final_keys:
                    changes.append(
                        {
                            "kind": "function_annotation",
                            "action": "delete",
                            "annotation": {
                                "label": annotation.label,
                                "start_residue_handle": handles[
                                    annotation.start_residue_id
                                ],
                                "end_residue_handle": handles[
                                    annotation.end_residue_id
                                ],
                            },
                        }
                    )
            for annotation in final_annotations:
                if self._annotation_key(annotation) not in baseline_keys:
                    changes.append(
                        {
                            "kind": "function_annotation",
                            "action": "insert",
                            "annotation": {
                                "label": annotation.label,
                                "start_residue_handle": handles[
                                    annotation.start_residue_id
                                ],
                                "end_residue_handle": handles[
                                    annotation.end_residue_id
                                ],
                            },
                        }
                    )

        chain_lengths = {
            chain_id: sum(
                residue_identity_chain(residue_id) == chain_id
                for residue_id in prompt.layout.residue_ids
            )
            for chain_id in prompt.layout.chain_ids
        }
        summary_tracks: dict[str, Mapping[str, int]] = {}
        for track, field in _TRACK_FIELDS.items():
            values = getattr(prompt, field)
            specified = 0 if values is None else sum(item is not None for item in values)
            summary_tracks[track] = {
                "specified": specified,
                "unspecified": prompt.layout.length - specified,
            }
        summary = {
            "chains": [
                {"chain_id": chain_id, "length": chain_lengths[chain_id]}
                for chain_id in prompt.layout.chain_ids
            ],
            "tracks": summary_tracks,
            "function_annotation_count": len(prompt.function_annotations),
        }
        return (
            tuple(residues),
            tracks,
            tuple(annotations),
            tuple(changes),
            summary,
        )

    @staticmethod
    def _preview_digest(
        node_id: str,
        document: Mapping[str, Any],
        sources: _ResolvedSources,
    ) -> str:
        return "sha256:" + hashlib.sha256(
            canonical_json_bytes(
                {
                    "node_id": node_id,
                    "normalized_document": document,
                    "source_facts": sources.source_facts,
                    "merge_source_facts": sources.merge_source_facts,
                }
            )
        ).hexdigest()

    @staticmethod
    def _project_random_trace(
        trace: Sequence[Mapping[str, Any]],
    ) -> tuple[Mapping[str, Any], ...]:
        return tuple(
            {
                "operation_index": item["operation_index"],
                "kind": item["kind"],
                "realized_residue_handles": [
                    _residue_handle(residue_id)
                    for residue_id in item["residue_ids"]
                ],
            }
            for item in trace
        )

    @staticmethod
    def _project_source_merges(
        sources: _ResolvedSources,
        document: Mapping[str, Any],
    ) -> tuple[Mapping[str, Any], ...]:
        result: list[Mapping[str, Any]] = []
        for merge in document.get("source_merges", ()):
            source_index = merge["source_index"]
            result.append(
                {
                    "source": _copy_document(
                        sources.merge_source_facts[source_index]
                    ),
                    "correspondence": _thaw_json(merge["correspondence"]),
                    "track_decisions": _thaw_json(merge["track_decisions"]),
                    "confirmed": True,
                }
            )
        return tuple(result)

    @staticmethod
    def _can_evaluate(
        sources: _ResolvedSources,
        document: Mapping[str, Any],
    ) -> bool:
        return bool(
            sources.sequence_source is not None
            or sources.structure_source is not None
            or sources.prompt_source is not None
            or document.get("chains")
        )

    def _evaluate_if_possible(
        self,
        sources: _ResolvedSources,
        document: Mapping[str, Any],
    ) -> tuple[ProteinPrompt | None, tuple[Mapping[str, Any], ...]]:
        if not self._can_evaluate(sources, document):
            return None, ()
        return _evaluate_prompt_recipe(
            sequence_source=sources.sequence_source,
            structure_source=sources.structure_source,
            prompt_source=sources.prompt_source,
            merge_sources=sources.merge_sources,
            document=document,
        )

    def _saved_result(
        self, sources: _ResolvedSources, document: Mapping[str, Any],
    ) -> tuple[ProteinPrompt | None, tuple[Mapping[str, Any], ...], tuple[PromptAuthoringDiagnostic, ...]]:
        try:
            prompt, trace = self._evaluate_if_possible(sources, document)
        except ValueError as error:
            return None, (), (PromptAuthoringDiagnostic("recipe_error", str(error), ("document",)),)
        return prompt, trace, ()

    def open(
        self,
        project_id: str,
        request: Mapping[str, Any],
    ) -> PromptAuthoringSnapshot:
        node, draft = self._require_author_node(project_id, request["node_id"])
        document = _normalize_document(node.node_parameters["document"])
        sources = self._resolve_sources(
            project_id, draft, node, document, frozenset({node.node_id})
        )
        prompt, trace, baseline_diagnostics = self._saved_result(sources, document)
        if prompt is None:
            return PromptAuthoringSnapshot(
                document=document,
                residues=(),
                tracks=_empty_tracks(),
                function_annotations=(),
                source=sources.source_facts,
                baseline_diagnostics=baseline_diagnostics,
                random_selections=(),
            )
        residues, tracks, annotations, _changes, _summary = self._project_prompt(
            prompt, prompt
        )
        return PromptAuthoringSnapshot(
            document=document,
            residues=residues,
            tracks=tracks,
            function_annotations=annotations,
            source=sources.source_facts,
            baseline_diagnostics=baseline_diagnostics,
            random_selections=self._project_random_trace(trace),
        )

    def _preview_loaded(
        self,
        project_id: str,
        node: WorkflowNodeInstance,
        draft: WorkflowDraft,
        document: Mapping[str, Any],
    ) -> PromptAuthoringPreview:
        stored_document = _normalize_document(node.node_parameters["document"])
        stored_sources = self._resolve_sources(
            project_id,
            draft,
            node,
            stored_document,
            frozenset({node.node_id}),
        )
        baseline, _baseline_trace, baseline_diagnostics = self._saved_result(
            stored_sources, stored_document
        )
        sources = self._resolve_sources(
            project_id,
            draft,
            node,
            document,
            frozenset({node.node_id}),
        )
        digest = self._preview_digest(node.node_id, document, sources)
        try:
            final, trace = _evaluate_prompt_recipe(
                sequence_source=sources.sequence_source,
                structure_source=sources.structure_source,
                prompt_source=sources.prompt_source,
                merge_sources=sources.merge_sources,
                document=document,
            )
        except ValueError as error:
            if baseline is None:
                residues: tuple[Mapping[str, Any], ...] = ()
                tracks: Mapping[str, Mapping[str, Any]] = _empty_tracks()
                annotations: tuple[Mapping[str, Any], ...] = ()
                summary: Mapping[str, Any] = _empty_summary()
            else:
                residues, tracks, annotations, _changes, summary = (
                    self._project_prompt(baseline, baseline)
                )
            return PromptAuthoringPreview(
                normalized_document=document,
                preview_digest=digest,
                residues=residues,
                tracks=tracks,
                function_annotations=annotations,
                changes=(),
                random_selections=(),
                source_merges=(),
                diagnostics=(
                    PromptAuthoringDiagnostic(
                        "recipe_error", str(error), ("document",)
                    ),
                ),
                summary=summary,
                baseline_diagnostics=baseline_diagnostics,
            )

        residues, tracks, annotations, changes, summary = self._project_prompt(
            final, baseline
        )
        return PromptAuthoringPreview(
            normalized_document=document,
            preview_digest=digest,
            residues=residues,
            tracks=tracks,
            function_annotations=annotations,
            changes=changes,
            random_selections=self._project_random_trace(trace),
            source_merges=self._project_source_merges(sources, document),
            diagnostics=(),
            baseline_diagnostics=baseline_diagnostics,
            summary=summary,
        )

    def preview(
        self,
        project_id: str,
        request: Mapping[str, Any],
    ) -> PromptAuthoringPreview:
        node, draft = self._require_author_node(project_id, request["node_id"])
        document = _normalize_document(request["document"])
        return self._preview_loaded(project_id, node, draft, document)

    def apply(
        self,
        project_id: str,
        request: Mapping[str, Any],
    ) -> PromptApplyResult:
        node, draft = self._require_author_node(project_id, request["node_id"])
        document = _normalize_document(request["document"])
        preview = self._preview_loaded(project_id, node, draft, document)
        if preview.diagnostics:
            raise WorkflowAuthoringError(
                "malformed_request",
                preview.diagnostics[0].message,
                details={
                    "field_path": list(preview.diagnostics[0].field_path)
                },
            )
        if request["preview_digest"] != preview.preview_digest:
            raise WorkflowAuthoringError(
                "malformed_request",
                "Preview digest does not match the current document and sources",
                details={"field_path": ["preview_digest"]},
            )
        parameters = dict(_thaw_json(node.node_parameters))
        parameters["document"] = _copy_document(preview.normalized_document)
        updated = self._workflow_authoring.update_node_parameters(
            project_id,
            node_id=node.node_id,
            node_parameters=parameters,
        )
        return PromptApplyResult(draft=updated)
