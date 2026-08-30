"""Current specialized ProteinPrompt authoring and whole-Prompt contracts."""

from __future__ import annotations

from pathlib import Path

import pytest

from core.catalog.authoring import build_authoring_capability_projection
from core.catalog.builder import build_frozen_catalog
from core.project.manager import ProjectManager
from core.workflow.authoring import (
    WorkflowAuthoringError,
    WorkflowAuthoringService,
)
from core.workflow.document import WorkflowDocument
from datatypes.prompt import (
    FunctionAnnotation,
    FunctionAnnotations,
    ProteinPrompt,
)
from datatypes.residue import ResidueLayout, ResidueTrack
from modules.prompt_authoring.annotations import replace_function_annotations
from modules.prompt_authoring.authoring import PromptAuthoringService
from modules.prompt_authoring.deterministic import (
    edit_protein_prompt_layout,
    merge_protein_prompt_source,
)
from protein_workbench_public.bootstrap import module_registrations


_ONE_RESIDUE_PDB = (
    b"ATOM      1  N   ALA A   1       0.000   0.000   0.000"
    b"  1.00 20.00           N  \n"
    b"ATOM      2  CA  ALA A   1       1.000   0.000   0.000"
    b"  1.00 20.00           C  \n"
    b"ATOM      3  C   ALA A   1       2.000   0.000   0.000"
    b"  1.00 20.00           C  \n"
    b"ATOM      4  O   ALA A   1       3.000   0.000   0.000"
    b"  1.00 20.00           O  \nTER\nEND\n"
)


def _services(tmp_path: Path):
    registrations = module_registrations()
    catalog = build_frozen_catalog(registrations)
    projection = build_authoring_capability_projection(
        registrations,
        catalog,
    )
    projects = ProjectManager(tmp_path / "projects")
    project = projects.create("Prompt authoring")
    workflows = WorkflowAuthoringService(projects, catalog, projection)
    workflows.save_draft(
        project.id,
        workflow=WorkflowDocument("2.1.0", project.id, (), ()),
    )
    return (
        catalog,
        projection,
        projects,
        project,
        workflows,
        PromptAuthoringService(projects, workflows),
    )


def _blank_document(service: PromptAuthoringService, project_id: str):
    return service.open(
        project_id,
        {
            "mode": "create",
            "source": {
                "kind": "blank",
                "chains": [
                    {"chain_id": "A", "length": 3},
                    {"chain_id": "B", "length": 2},
                ],
            },
        },
    ).document


def test_prompt_package_atomically_publishes_current_managed_contracts() -> None:
    registrations = module_registrations()
    catalog = build_frozen_catalog(registrations)
    expected = {
        "prompt_authoring.assemble_protein_prompt",
        "prompt_authoring.build_residue_layout",
        "prompt_authoring.edit_protein_prompt_layout",
        "prompt_authoring.merge_protein_prompt_source",
        "prompt_authoring.override_protein_prompt_track",
        "prompt_authoring.prompt_from_structure",
        "prompt_authoring.random_insert_masked",
        "prompt_authoring.random_mask",
        "prompt_authoring.replace_protein_prompt_annotations",
        "prompt_authoring.update_prompt_sequence",
    }
    present = {
        contract.contract_id
        for contract in catalog.contracts
        if contract.contract_kind == "node_type"
        and contract.contract_id.startswith("prompt_authoring.")
    }
    assert present == expected
    removed = {
        "prompt_authoring.add_function_annotation",
        "prompt_authoring.edit_residue_layout",
        "prompt_authoring.insert_masked_residues",
        "prompt_authoring.map_residue_track",
        "prompt_authoring.override_residue_track",
    }
    assert not present & removed


def test_authoring_projection_has_one_prompt_entry_and_no_managed_palette_nodes() -> None:
    registrations = module_registrations()
    catalog = build_frozen_catalog(registrations)
    projection = build_authoring_capability_projection(registrations, catalog)
    capability = projection.require_capability("protein_prompt.authoring")
    assert capability.editor_kind == "prompt_studio"
    assert {
        endpoint.role: endpoint.port_type.contract_id
        for endpoint in capability.exposed_outputs
    } == {
        "protein_prompt": "protein.prompt",
        "residue_layout": "residue.layout",
    }
    managed = {
        role.node_type.contract_id
        for role in projection.node_roles
        if role.role == "managed_member"
    }
    assert {
        reference.contract_id
        for reference in capability.managed_node_types
    } == managed
    assert all(
        role.role != "ordinary_node"
        for role in projection.node_roles
        if role.node_type.contract_id in managed
    )


def test_whole_prompt_layout_edit_realigns_every_track_and_annotations() -> None:
    source_layout = ResidueLayout("A", 3, ("A:1", "A:2", "A:3"))
    prompt = ProteinPrompt(
        target_layout=source_layout,
        sequence_track=ResidueTrack(("A", "C", "D"), None),
        structure_track=ResidueTrack(({"CA": (1.0, 0.0, 0.0)}, None, None), None),
        secondary_structure_track=ResidueTrack(("H", "E", "-"), None),
        sasa_track=ResidueTrack((1.0, 2.0, 3.0), None),
        function_annotations=FunctionAnnotations(
            (
                FunctionAnnotation(
                    "domain",
                    1,
                    3,
                    "A",
                    "A:1",
                    "A:3",
                ),
            )
        ),
    )
    target_layout = ResidueLayout(
        "A",
        3,
        ("A:1", "A:inserted", "A:3"),
    )
    changed, residue_map = edit_protein_prompt_layout(
        prompt,
        target_layout,
        (
            {"operation": "delete", "chain_id": "A", "residue_id": "A:2"},
            {"operation": "insert", "chain_id": "A", "residue_id": "A:inserted"},
        ),
    )
    assert changed.sequence_track.values == ("A", None, "D")
    assert changed.structure_track.values == (
        {"CA": (1.0, 0.0, 0.0)},
        None,
        None,
    )
    assert changed.secondary_structure_track.values == ("H", None, "-")
    assert changed.sasa_track.values == (1.0, None, 3.0)
    assert changed.function_annotations.annotations[0].end == 3
    assert residue_map.target_layout == target_layout


def test_complete_annotation_replacement_and_confirmed_merge() -> None:
    layout = ResidueLayout("A", 2, ("A:1", "A:2"))
    target = ProteinPrompt(
        layout,
        ResidueTrack(("A", "C"), None),
        ResidueTrack((None, None), None),
    )
    source = ProteinPrompt(
        layout,
        ResidueTrack(("D", "E"), None),
        ResidueTrack((None, None), None),
    )
    annotations = replace_function_annotations(
        layout,
        (
            {
                "label": "active_site",
                "chain_id": "A",
                "start_residue_id": "A:1",
                "end_residue_id": "A:2",
            },
        ),
        overlap_policy="reject",
    )
    assert annotations.annotations[0].start == 1
    merged = merge_protein_prompt_source(
        target,
        source,
        (
            {"disposition": "match", "source_residue_id": "A:1", "target_residue_id": "A:1"},
            {"disposition": "match", "source_residue_id": "A:2", "target_residue_id": "A:2"},
        ),
        {
            "sequence": "adopt",
            "structure": "preserve",
            "secondary_structure": "preserve",
            "sasa": "preserve",
            "function_annotations": "preserve",
        },
    )
    assert merged.sequence_track.values == ("D", "E")


def test_open_preview_apply_reopen_copy_delete_and_managed_ownership(
    tmp_path: Path,
) -> None:
    _catalog, _projection, projects, project, workflows, service = _services(
        tmp_path
    )
    fasta = projects.publish_input(
        project.id,
        "managed-source",
        b">managed\nACD\n",
        filename="managed.fasta",
    )
    document = dict(
        service.open(
            project.id,
            {
                "mode": "create",
                "source": {
                    "kind": "fasta",
                    "project_input_ref": fasta.project_input_ref,
                    "chain_ids": ["A"],
                },
            },
        ).document
    )
    first_handle = document["target_residues"][0]["residue_handle"]
    document["random_operations"] = [
        {
            "operation_id": "mask-one",
            "kind": "mask",
            "track": "sequence",
            "count": 1,
            "eligible_residue_handles": [first_handle],
            "seed": 17,
        }
    ]
    preview = service.preview(project.id, document)
    assert preview.random_selections[0]["residue_handles"] == [first_handle]
    created = service.apply(
        project.id,
        intent="create",
        normalized_document=preview.normalized_document,
        preview_digest=preview.preview_digest,
    )
    composition = created.composition
    assert composition is not None
    assert {
        endpoint.role: endpoint.port_name
        for endpoint in composition.exposed_outputs
    } == {
        "protein_prompt": "protein_prompt",
        "residue_layout": "layout",
    }
    assert any(
        node.node_type_id == "prompt_authoring.random_mask"
        for node in created.draft.workflow.nodes
    )
    reopened = service.open(
        project.id,
        {"mode": "reopen", "composition_id": composition.composition_id},
    )
    assert reopened.document == preview.normalized_document
    sourced = service.open(
        project.id,
        {
            "mode": "create",
            "source": {
                "kind": "protein_prompt",
                "composition_id": composition.composition_id,
            },
        },
    )
    assert len(sourced.residues) == len(reopened.residues)
    copy_preview = service.preview(
        project.id,
        preview.normalized_document,
        composition_id=composition.composition_id,
    )
    copied = service.apply(
        project.id,
        intent="copy",
        normalized_document=copy_preview.normalized_document,
        preview_digest=copy_preview.preview_digest,
        composition_id=composition.composition_id,
    )
    assert copied.composition is not None
    assert copied.composition.composition_id != composition.composition_id
    managed_node = next(
        node
        for node in copied.draft.workflow.nodes
        if node.node_id in copied.composition.managed_node_ids
    )
    changed = WorkflowDocument(
        copied.draft.workflow.schema_version,
        copied.draft.workflow.workflow_id,
        tuple(
            type(node)(
                node.node_id,
                node.node_type_id,
                node.binding_id,
                {"chains": [{"chain_id": "A", "length": 99}]},
                node.binding_parameters,
            )
            if node.node_id == managed_node.node_id
            else node
            for node in copied.draft.workflow.nodes
        ),
        copied.draft.workflow.edges,
    )
    with pytest.raises(WorkflowAuthoringError, match="managed Node"):
        workflows.save_draft(project.id, workflow=changed)
    delete_preview = service.preview(
        project.id,
        preview.normalized_document,
        composition_id=composition.composition_id,
    )
    deleted = service.apply(
        project.id,
        intent="delete",
        normalized_document=delete_preview.normalized_document,
        preview_digest=delete_preview.preview_digest,
        composition_id=composition.composition_id,
    )
    assert all(
        record.composition_id != composition.composition_id
        for record in deleted.draft.authoring_compositions
    )


def test_fasta_and_pdb_sources_open_without_public_layout_or_graph_facts(
    tmp_path: Path,
) -> None:
    _catalog, _projection, projects, project, _workflows, service = _services(
        tmp_path
    )
    fasta = projects.publish_input(
        project.id,
        "fasta-source",
        b">first\nACD\n>second\nEF\n",
        filename="source.fasta",
    )
    opened = service.open(
        project.id,
        {
            "mode": "create",
            "source": {
                "kind": "fasta",
                "project_input_ref": fasta.project_input_ref,
                "chain_ids": ["A", "B"],
            },
        },
    )
    assert [item["chain_id"] for item in opened.residues] == ["A", "A", "A", "B", "B"]
    public_text = repr(opened.document)
    assert "ResidueLayout" not in public_text
    assert "residue_ids" not in public_text
    assert "node_type_id" not in public_text


def test_pdb_source_materializes_required_csh_normalization(
    tmp_path: Path,
) -> None:
    _catalog, _projection, projects, project, _workflows, service = _services(
        tmp_path
    )
    source = projects.publish_input(
        project.id,
        "csh-source",
        (
            Path(__file__).parent.parent
            / "examples"
            / "v2"
            / "structures"
            / "2EMO.pdb"
        ).read_bytes(),
        filename="2EMO.pdb",
    )

    opened = service.open(
        project.id,
        {
            "mode": "create",
            "source": {
                "kind": "pdb",
                "project_input_ref": source.project_input_ref,
                "chain_ids": ["A"],
            },
        },
    )
    preview = service.preview(project.id, opened.document)
    applied = service.apply(
        project.id,
        intent="create",
        normalized_document=preview.normalized_document,
        preview_digest=preview.preview_digest,
    )

    assert any(
        node.node_type_id
        == "structure_transform.normalize_csh_parent_span"
        for node in applied.draft.workflow.nodes
        if node.node_id in applied.composition.managed_node_ids
    )

    pdb = projects.publish_input(
        project.id,
        "pdb-source",
        _ONE_RESIDUE_PDB,
        filename="source.pdb",
    )
    structure_opened = service.open(
        project.id,
        {
            "mode": "create",
            "source": {
                "kind": "pdb",
                "project_input_ref": pdb.project_input_ref,
                "chain_ids": ["A"],
            },
        },
    )
    assert len(structure_opened.residues) == 1
    assert structure_opened.tracks["structure"][0]["value"] is not None


def test_source_merge_diagnostics_and_explicit_materialization(
    tmp_path: Path,
) -> None:
    _catalog, _projection, _projects, project, _workflows, service = _services(
        tmp_path
    )
    document = dict(_blank_document(service, project.id))
    target_handles = [
        item["residue_handle"] for item in document["target_residues"][:3]
    ]
    merge = {
        "source": {
            "kind": "blank",
            "chains": [{"chain_id": "A", "length": 3}],
        },
        "correspondence": [
            {
                "disposition": "match",
                "source_residue_handle": f"residue-{index + 1:08d}",
                "target_residue_handle": handle,
            }
            for index, handle in enumerate(target_handles)
        ],
        "track_decisions": {
            "sequence": "preserve",
            "structure": "preserve",
            "secondary_structure": "preserve",
            "sasa": "preserve",
            "function_annotations": "preserve",
        },
        "confirmed": False,
    }
    document["source_merges"] = [merge]
    pending = service.preview(project.id, document)
    assert [item.code for item in pending.diagnostics] == [
        "correspondence_unconfirmed"
    ]
    with pytest.raises(WorkflowAuthoringError, match="unresolved diagnostics"):
        service.apply(
            project.id,
            intent="create",
            normalized_document=pending.normalized_document,
            preview_digest=pending.preview_digest,
        )

    merge["confirmed"] = True
    preview = service.preview(project.id, document)
    applied = service.apply(
        project.id,
        intent="create",
        normalized_document=preview.normalized_document,
        preview_digest=preview.preview_digest,
    )
    merge_node = next(
        node
        for node in applied.draft.workflow.nodes
        if node.node_type_id == "prompt_authoring.merge_protein_prompt_source"
    )
    merge_inputs = {
        edge.target_port
        for edge in applied.draft.workflow.edges
        if edge.target_node_id == merge_node.node_id
    }
    assert merge_inputs == {"target_prompt", "source_prompt"}


def test_random_diagnostic_and_rigid_transform_materialization(
    tmp_path: Path,
) -> None:
    _catalog, _projection, projects, project, _workflows, service = _services(
        tmp_path
    )
    blank = dict(_blank_document(service, project.id))
    blank["random_operations"] = [
        {
            "operation_id": "mask-unassigned",
            "kind": "mask",
            "track": "sequence",
            "count": 1,
            "eligible_residue_handles": [],
            "seed": 7,
        }
    ]
    random_preview = service.preview(project.id, blank)
    assert [item.code for item in random_preview.diagnostics] == [
        "random_count_exceeds_eligibility"
    ]

    pdb = projects.publish_input(
        project.id,
        "rigid-source",
        _ONE_RESIDUE_PDB,
        filename="rigid.pdb",
    )
    opened = service.open(
        project.id,
        {
            "mode": "create",
            "source": {
                "kind": "pdb",
                "project_input_ref": pdb.project_input_ref,
                "chain_ids": ["A"],
            },
        },
    )
    document = dict(opened.document)
    document["rigid_transforms"] = [
        {
            "residue_handles": [opened.residues[0]["residue_handle"]],
            "rotation_matrix": [
                [1.0, 0.0, 0.0],
                [0.0, 1.0, 0.0],
                [0.0, 0.0, 1.0],
            ],
            "origin": [0.0, 0.0, 0.0],
            "translation": [1.0, 2.0, 3.0],
        }
    ]
    preview = service.preview(project.id, document)
    applied = service.apply(
        project.id,
        intent="create",
        normalized_document=preview.normalized_document,
        preview_digest=preview.preview_digest,
    )
    override = next(
        node
        for node in applied.draft.workflow.nodes
        if node.node_type_id
        == "prompt_authoring.override_protein_prompt_track"
    )
    assert override.node_parameters["track"] == "structure"
    assert override.node_parameters["overrides"][0]["value"] == {
        "atom_coordinates": (
            {"atom_name": "N", "coordinates": (1.0, 2.0, 3.0)},
            {"atom_name": "CA", "coordinates": (2.0, 2.0, 3.0)},
            {"atom_name": "C", "coordinates": (3.0, 2.0, 3.0)},
            {"atom_name": "O", "coordinates": (4.0, 2.0, 3.0)},
        )
    }


def test_random_insertion_preview_handles_can_author_inserted_tracks(
    tmp_path: Path,
) -> None:
    _catalog, _projection, _projects, project, _workflows, service = _services(
        tmp_path
    )
    document = dict(_blank_document(service, project.id))
    document["random_operations"] = [
        {
            "operation_id": "insert-one",
            "kind": "insert",
            "count": 1,
            "eligible_chain_ids": ["A"],
            "seed": 29,
        }
    ]
    insertion_preview = service.preview(project.id, document)
    inserted_handle = next(
        residue["residue_handle"]
        for residue in insertion_preview.residues
        if residue["residue_handle"].startswith("random-residue-")
    )
    document["track_intents"] = [
        {
            "track": "secondary_structure",
            "residue_handle": inserted_handle,
            "action": "specify",
            "value": "E",
        }
    ]

    preview = service.preview(project.id, document)

    assert preview.diagnostics == ()
    projected = next(
        item
        for item in preview.tracks["secondary_structure"]
        if item["residue_handle"] == inserted_handle
    )
    assert projected["value"] == "E"
    applied = service.apply(
        project.id,
        intent="create",
        normalized_document=preview.normalized_document,
        preview_digest=preview.preview_digest,
    )
    managed_nodes = [
        node
        for node in applied.draft.workflow.nodes
        if node.node_id in applied.composition.managed_node_ids
    ]
    operation_order = [
        node.node_type_id
        for node in managed_nodes
        if node.node_type_id
        in {
            "prompt_authoring.random_insert_masked",
            "prompt_authoring.override_protein_prompt_track",
        }
    ]
    assert operation_order == [
        "prompt_authoring.random_insert_masked",
        "prompt_authoring.override_protein_prompt_track",
    ]
