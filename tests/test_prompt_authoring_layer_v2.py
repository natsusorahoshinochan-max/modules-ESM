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
from core.workflow.document import (
    WorkflowDocument,
    WorkflowEdge,
    WorkflowNodeInstance,
)
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
    second_copy_preview = service.preview(
        project.id,
        preview.normalized_document,
        composition_id=copied.composition.composition_id,
    )
    second_copy = service.apply(
        project.id,
        intent="copy",
        normalized_document=second_copy_preview.normalized_document,
        preview_digest=second_copy_preview.preview_digest,
        composition_id=copied.composition.composition_id,
    )

    assert second_copy.composition.composition_id not in {
        composition.composition_id,
        copied.composition.composition_id,
    }
    assert len({
        record.composition_id
        for record in second_copy.draft.authoring_compositions
    }) == 2


def test_recreating_deleted_composition_allocates_a_new_identity(
    tmp_path: Path,
) -> None:
    _catalog, _projection, _projects, project, _workflows, service = _services(
        tmp_path
    )
    document = _blank_document(service, project.id)
    preview = service.preview(project.id, document)
    created = service.apply(
        project.id,
        intent="create",
        normalized_document=preview.normalized_document,
        preview_digest=preview.preview_digest,
    )
    deleted_preview = service.preview(
        project.id,
        preview.normalized_document,
        composition_id=created.composition.composition_id,
    )
    service.apply(
        project.id,
        intent="delete",
        normalized_document=deleted_preview.normalized_document,
        preview_digest=deleted_preview.preview_digest,
        composition_id=created.composition.composition_id,
    )
    recreated_preview = service.preview(project.id, document)
    recreated = service.apply(
        project.id,
        intent="create",
        normalized_document=recreated_preview.normalized_document,
        preview_digest=recreated_preview.preview_digest,
    )

    assert recreated.composition.composition_id != (
        created.composition.composition_id
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


def test_fasta_source_materializes_project_input_provenance(tmp_path: Path) -> None:
    _catalog, _projection, projects, project, _workflows, service = _services(
        tmp_path
    )
    fasta = projects.publish_input(
        project.id,
        "materialized-fasta",
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
    preview = service.preview(project.id, opened.document)
    applied = service.apply(
        project.id,
        intent="create",
        normalized_document=preview.normalized_document,
        preview_digest=preview.preview_digest,
    )
    managed = {
        node.node_id: node
        for node in applied.draft.workflow.nodes
        if node.node_id in applied.composition.managed_node_ids
    }
    imported = next(
        node
        for node in managed.values()
        if node.node_type_id == "protein_io.import_sequence"
    )
    updated = next(
        node
        for node in managed.values()
        if node.node_type_id == "prompt_authoring.update_prompt_sequence"
    )

    assert imported.node_parameters == {
        "project_input_ref": fasta.project_input_ref
    }
    assert {
        (edge.source_node_id, edge.source_port, edge.target_port)
        for edge in applied.draft.workflow.edges
        if edge.target_node_id == updated.node_id
    } == {
        (imported.node_id, "sequence", "sequence"),
        (
            next(
                node.node_id
                for node in managed.values()
                if node.node_type_id
                == "prompt_authoring.assemble_protein_prompt"
            ),
            "protein_prompt",
            "protein_prompt",
        ),
    }


def test_pdb_merge_source_materializes_required_csh_normalization(
    tmp_path: Path,
) -> None:
    _catalog, _projection, projects, project, _workflows, service = _services(
        tmp_path
    )
    source = projects.publish_input(
        project.id,
        "merge-csh-source",
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
    document = dict(opened.document)
    document["source_merges"] = [
        {
            "source": {
                "kind": "pdb",
                "project_input_ref": source.project_input_ref,
                "chain_ids": ["A"],
            },
            "correspondence": [
                {
                    "disposition": "match",
                    "source_residue_handle": residue["residue_handle"],
                    "target_residue_handle": residue["residue_handle"],
                }
                for residue in opened.residues
            ],
            "track_decisions": {
                "sequence": "preserve",
                "structure": "preserve",
                "secondary_structure": "preserve",
                "sasa": "preserve",
                "function_annotations": "preserve",
            },
            "confirmed": True,
        }
    ]
    preview = service.preview(project.id, document)
    applied = service.apply(
        project.id,
        intent="create",
        normalized_document=preview.normalized_document,
        preview_digest=preview.preview_digest,
    )

    assert any(
        node.node_type_id
        == "structure_transform.normalize_csh_parent_span"
        and ".merge.0001.source.normalize_csh" in node.node_id
        for node in applied.draft.workflow.nodes
    )


def test_preview_projects_all_six_track_change_states(tmp_path: Path) -> None:
    _catalog, _projection, projects, project, _workflows, service = _services(
        tmp_path
    )
    fasta = projects.publish_input(
        project.id,
        "state-source",
        b">source\nACDEG\n",
        filename="states.fasta",
    )
    opened = service.open(
        project.id,
        {
            "mode": "create",
            "source": {
                "kind": "fasta",
                "project_input_ref": fasta.project_input_ref,
                "chain_ids": ["A"],
            },
        },
    )
    handles = [item["residue_handle"] for item in opened.residues]
    document = dict(opened.document)
    document["target_residues"] = [
        *document["target_residues"][:4],
        {
            "residue_handle": "insert-one",
            "origin": "insert",
            "chain_id": "A",
        },
    ]
    document["track_intents"] = [
        {
            "track": "sequence",
            "residue_handle": handles[1],
            "action": "preserve",
        },
        {
            "track": "sequence",
            "residue_handle": handles[2],
            "action": "specify",
            "value": "F",
        },
        {
            "track": "sequence",
            "residue_handle": handles[3],
            "action": "mask",
        },
        {
            "track": "sequence",
            "residue_handle": "insert-one",
            "action": "specify",
            "value": "H",
        },
    ]

    preview = service.preview(project.id, document)

    projected = {
        item["residue_handle"]: (item["value"], item["state"])
        for item in preview.tracks["sequence"]
    }
    assert projected == {
        handles[0]: ("A", "source"),
        handles[1]: ("C", "current"),
        handles[2]: ("F", "changed"),
        handles[3]: (None, "cleared"),
        "insert-one": ("H", "inserted"),
        handles[4]: ("G", "pending-delete"),
    }
    assert handles[4] in {
        item["residue_handle"] for item in preview.residues
    }


def test_preview_marks_a_new_same_label_annotation_as_inserted(
    tmp_path: Path,
) -> None:
    _catalog, _projection, _projects, project, _workflows, service = _services(
        tmp_path
    )
    opened = service.open(
        project.id,
        {
            "mode": "create",
            "source": {
                "kind": "blank",
                "chains": [{"chain_id": "A", "length": 6}],
            },
        },
    )
    handles = [item["residue_handle"] for item in opened.residues]
    source_document = dict(opened.document)
    source_document["function_annotations"] = [
        {
            "label": "domain",
            "start_residue_handle": handles[0],
            "end_residue_handle": handles[1],
        },
        {
            "label": "domain",
            "start_residue_handle": handles[2],
            "end_residue_handle": handles[3],
        },
    ]
    source_preview = service.preview(project.id, source_document)
    source = service.apply(
        project.id,
        intent="create",
        normalized_document=source_preview.normalized_document,
        preview_digest=source_preview.preview_digest,
    )
    sourced = service.open(
        project.id,
        {
            "mode": "create",
            "source": {
                "kind": "protein_prompt",
                "composition_id": source.composition.composition_id,
            },
        },
    )
    document = dict(sourced.document)
    document["function_annotations"] = [
        *document["function_annotations"],
        {
            "label": "domain",
            "start_residue_handle": sourced.residues[4]["residue_handle"],
            "end_residue_handle": sourced.residues[5]["residue_handle"],
        },
    ]

    preview = service.preview(project.id, document)

    assert [item["state"] for item in preview.function_annotations] == [
        "source",
        "source",
        "inserted",
    ]


def test_inserted_residue_identity_is_not_caller_authored(tmp_path: Path) -> None:
    _catalog, _projection, _projects, project, _workflows, service = _services(
        tmp_path
    )
    opened = service.open(
        project.id,
        {
            "mode": "create",
            "source": {
                "kind": "blank",
                "chains": [{"chain_id": "A", "length": 3}],
            },
        },
    )
    assert "authoring_session_id" not in opened.document
    document = dict(opened.document)
    document["target_residues"] = [
        document["target_residues"][0],
        {
            "residue_handle": "caller-insert-label",
            "origin": "insert",
            "chain_id": "A",
        },
        document["target_residues"][1],
    ]
    preview = service.preview(project.id, document)
    applied = service.apply(
        project.id,
        intent="create",
        normalized_document=preview.normalized_document,
        preview_digest=preview.preview_digest,
    )
    layout_edit = next(
        node
        for node in applied.draft.workflow.nodes
        if node.node_type_id == "prompt_authoring.edit_protein_prompt_layout"
    )
    inserted_id = layout_edit.node_parameters["insertions"][0][
        "inserted_residue_ids"
    ][0]

    assert inserted_id != "A:caller-insert-label"
    assert {
        endpoint.role for endpoint in applied.composition.exposed_outputs
    } == {"protein_prompt", "residue_layout"}
    reopened = service.open(
        project.id,
        {
            "mode": "reopen",
            "composition_id": applied.composition.composition_id,
        },
    )
    replacement_document = dict(reopened.document)
    caller_position = next(
        index
        for index, residue in enumerate(
            replacement_document["target_residues"]
        )
        if residue["residue_handle"] == "caller-insert-label"
    )
    replacement_document["target_residues"].insert(
        caller_position,
        {
            "residue_handle": "insert-before-caller",
            "origin": "insert",
            "chain_id": "A",
        },
    )
    replacement_preview = service.preview(
        project.id,
        replacement_document,
        composition_id=applied.composition.composition_id,
    )
    replaced = service.apply(
        project.id,
        intent="replace",
        normalized_document=replacement_preview.normalized_document,
        preview_digest=replacement_preview.preview_digest,
        composition_id=applied.composition.composition_id,
    )
    replaced_layout_edit = next(
        node
        for node in replaced.draft.workflow.nodes
        if node.node_type_id == "prompt_authoring.edit_protein_prompt_layout"
    )
    assert replaced_layout_edit.node_parameters["insertions"][0][
        "inserted_residue_ids"
    ][1] == inserted_id


def test_layout_consumer_reconnects_to_edited_target_layout(
    tmp_path: Path,
) -> None:
    _catalog, _projection, _projects, project, workflows, service = _services(
        tmp_path
    )
    document = dict(_blank_document(service, project.id))
    preview = service.preview(project.id, document)
    created = service.apply(
        project.id,
        intent="create",
        normalized_document=preview.normalized_document,
        preview_digest=preview.preview_digest,
    )
    composition = created.composition
    assert composition is not None
    layout_endpoint = next(
        endpoint
        for endpoint in composition.exposed_outputs
        if endpoint.role == "residue_layout"
    )
    consumer = WorkflowNodeInstance(
        node_id="layout-consumer",
        node_type_id="proteinmpnn.constraints",
        binding_id="proteinmpnn.constraints.local",
        node_parameters={
            "designable_residue_ids": [],
            "fixed_residue_ids": [],
            "designed_chains": [],
            "fixed_chains": [],
            "omit_amino_acids": [],
            "tied_residue_groups": [],
            "bias_by_residue": [],
        },
        binding_parameters={},
    )
    workflows.save_draft(
        project.id,
        workflow=WorkflowDocument(
            schema_version=created.draft.workflow.schema_version,
            workflow_id=project.id,
            nodes=(*created.draft.workflow.nodes, consumer),
            edges=(
                *created.draft.workflow.edges,
                WorkflowEdge(
                    layout_endpoint.node_id,
                    layout_endpoint.port_name,
                    consumer.node_id,
                    "layout",
                ),
            ),
        ),
    )
    document["target_residues"].insert(
        1,
        {
            "residue_handle": "inserted-for-layout-consumer",
            "origin": "insert",
            "chain_id": "A",
        },
    )
    replacement_preview = service.preview(
        project.id,
        document,
        composition_id=composition.composition_id,
    )
    replaced = service.apply(
        project.id,
        intent="replace",
        normalized_document=replacement_preview.normalized_document,
        preview_digest=replacement_preview.preview_digest,
        composition_id=composition.composition_id,
    )
    replaced_layout_endpoint = next(
        endpoint
        for endpoint in replaced.composition.exposed_outputs
        if endpoint.role == "residue_layout"
    )

    assert replaced_layout_endpoint.node_id.endswith(".0001.layout_edit")
    assert replaced_layout_endpoint.port_name == "layout"
    assert WorkflowEdge(
        replaced_layout_endpoint.node_id,
        "layout",
        consumer.node_id,
        "layout",
    ) in replaced.draft.workflow.edges


def test_source_merge_diagnostics_and_explicit_materialization(
    tmp_path: Path,
) -> None:
    _catalog, _projection, _projects, project, _workflows, service = _services(
        tmp_path
    )
    document = dict(_blank_document(service, project.id))
    target_handles = [
        item["residue_handle"] for item in document["target_residues"]
    ]
    merge = {
        "source": {
            "kind": "blank",
            "chains": [{"chain_id": "A", "length": 3}],
        },
        "correspondence": [
            *[
                {
                    "disposition": "match",
                    "source_residue_handle": f"residue-{index + 1:08d}",
                    "target_residue_handle": handle,
                }
                for index, handle in enumerate(target_handles[:3])
            ],
            *[
                {
                    "disposition": "target_gap",
                    "target_residue_handle": handle,
                }
                for handle in target_handles[3:]
            ],
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


def test_source_merge_reports_duplicate_and_incomplete_correspondence(
    tmp_path: Path,
) -> None:
    _catalog, _projection, _projects, project, _workflows, service = _services(
        tmp_path
    )
    document = dict(_blank_document(service, project.id))
    handles = [item["residue_handle"] for item in document["target_residues"]]
    document["source_merges"] = [
        {
            "source": {
                "kind": "blank",
                "chains": [{"chain_id": "A", "length": 3}],
            },
            "correspondence": [
                {
                    "disposition": "match",
                    "source_residue_handle": handles[0],
                    "target_residue_handle": handles[0],
                },
                {
                    "disposition": "match",
                    "source_residue_handle": handles[0],
                    "target_residue_handle": handles[1],
                },
                {
                    "disposition": "match",
                    "source_residue_handle": handles[1],
                    "target_residue_handle": handles[0],
                },
            ],
            "track_decisions": {
                "sequence": "preserve",
                "structure": "preserve",
                "secondary_structure": "preserve",
                "sasa": "preserve",
                "function_annotations": "preserve",
            },
            "confirmed": True,
        }
    ]

    preview = service.preview(project.id, document)

    assert {item.code for item in preview.diagnostics} == {
        "correspondence_source_duplicate",
        "correspondence_target_duplicate",
        "correspondence_source_missing",
        "correspondence_target_missing",
    }


def test_source_merge_reports_annotation_loss_before_materialization(
    tmp_path: Path,
) -> None:
    _catalog, _projection, _projects, project, _workflows, service = _services(
        tmp_path
    )
    source_opened = service.open(
        project.id,
        {
            "mode": "create",
            "source": {
                "kind": "blank",
                "chains": [{"chain_id": "A", "length": 3}],
            },
        },
    )
    source_document = dict(source_opened.document)
    source_document["function_annotations"] = [
        {
            "label": "domain",
            "start_residue_handle": source_opened.residues[0]["residue_handle"],
            "end_residue_handle": source_opened.residues[2]["residue_handle"],
        }
    ]
    source_preview = service.preview(project.id, source_document)
    assert source_preview.function_annotations[0]["state"] == "inserted"
    source_applied = service.apply(
        project.id,
        intent="create",
        normalized_document=source_preview.normalized_document,
        preview_digest=source_preview.preview_digest,
    )
    reopened = service.open(
        project.id,
        {
            "mode": "create",
            "source": {
                "kind": "protein_prompt",
                "composition_id": source_applied.composition.composition_id,
            },
        },
    )
    deleted_annotation_document = dict(reopened.document)
    deleted_annotation_document["function_annotations"] = []
    deleted_annotation_preview = service.preview(
        project.id,
        deleted_annotation_document,
    )
    assert deleted_annotation_preview.function_annotations[0]["state"] == (
        "pending-delete"
    )
    target_opened = service.open(
        project.id,
        {
            "mode": "create",
            "source": {
                "kind": "blank",
                "chains": [{"chain_id": "A", "length": 3}],
            },
        },
    )
    target_document = dict(target_opened.document)
    target_document["source_merges"] = [
        {
            "source": {
                "kind": "protein_prompt",
                "composition_id": source_applied.composition.composition_id,
            },
            "correspondence": [
                {
                    "disposition": "match",
                    "source_residue_handle": source_opened.residues[0]["residue_handle"],
                    "target_residue_handle": target_opened.residues[0]["residue_handle"],
                },
                {
                    "disposition": "source_gap",
                    "source_residue_handle": source_opened.residues[1]["residue_handle"],
                },
                {
                    "disposition": "match",
                    "source_residue_handle": source_opened.residues[2]["residue_handle"],
                    "target_residue_handle": target_opened.residues[2]["residue_handle"],
                },
                {
                    "disposition": "target_gap",
                    "target_residue_handle": target_opened.residues[1]["residue_handle"],
                },
            ],
            "track_decisions": {
                "sequence": "preserve",
                "structure": "preserve",
                "secondary_structure": "preserve",
                "sasa": "preserve",
                "function_annotations": "adopt",
            },
            "confirmed": True,
        }
    ]

    preview = service.preview(project.id, target_document)

    assert [item.code for item in preview.diagnostics] == [
        "annotation_loss"
    ]


def test_source_merge_reports_missing_adopted_track(
    tmp_path: Path,
) -> None:
    _catalog, _projection, _projects, project, _workflows, service = _services(
        tmp_path
    )
    source_opened = service.open(
        project.id,
        {
            "mode": "create",
            "source": {
                "kind": "blank",
                "chains": [{"chain_id": "A", "length": 1}],
            },
        },
    )
    source_preview = service.preview(project.id, source_opened.document)
    source_applied = service.apply(
        project.id,
        intent="create",
        normalized_document=source_preview.normalized_document,
        preview_digest=source_preview.preview_digest,
    )
    target_opened = service.open(
        project.id,
        {
            "mode": "create",
            "source": {
                "kind": "blank",
                "chains": [{"chain_id": "A", "length": 1}],
            },
        },
    )
    target_document = dict(target_opened.document)
    target_document["track_intents"] = [
        {
            "track": "secondary_structure",
            "residue_handle": target_opened.residues[0]["residue_handle"],
            "action": "specify",
            "value": "H",
        }
    ]
    target_document["source_merges"] = [
        {
            "source": {
                "kind": "protein_prompt",
                "composition_id": source_applied.composition.composition_id,
            },
            "correspondence": [
                {
                    "disposition": "match",
                    "source_residue_handle": source_opened.residues[0][
                        "residue_handle"
                    ],
                    "target_residue_handle": target_opened.residues[0][
                        "residue_handle"
                    ],
                }
            ],
            "track_decisions": {
                "sequence": "preserve",
                "structure": "preserve",
                "secondary_structure": "adopt",
                "sasa": "preserve",
                "function_annotations": "preserve",
            },
            "confirmed": True,
        }
    ]

    preview = service.preview(project.id, target_document)

    assert [item.code for item in preview.diagnostics] == [
        "merge_source_track_missing"
    ]


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


def test_rigid_transform_rejects_a_non_rotation_matrix(tmp_path: Path) -> None:
    _catalog, _projection, projects, project, _workflows, service = _services(
        tmp_path
    )
    pdb = projects.publish_input(
        project.id,
        "non-rigid-source",
        _ONE_RESIDUE_PDB,
        filename="non-rigid.pdb",
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
                [2.0, 0.0, 0.0],
                [0.0, 1.0, 0.0],
                [0.0, 0.0, 1.0],
            ],
            "origin": [0.0, 0.0, 0.0],
            "translation": [0.0, 0.0, 0.0],
        }
    ]

    preview = service.preview(project.id, document)

    assert [item.code for item in preview.diagnostics] == [
        "rigid_rotation_invalid"
    ]


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
