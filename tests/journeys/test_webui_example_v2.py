"""Public acceptance for the current immutable WebUI 3GB1 example."""

from __future__ import annotations

import hashlib
from tests.support.prompt_authoring import workflow_with_prompt_document

from dataclasses import replace
from pathlib import Path

from fastapi.testclient import TestClient
import pytest

from core.catalog.builder import build_frozen_catalog
from core.project.manager import (
    CANONICAL_3GB1_PROJECT_ID,
    WEBUI_3GB1_PROJECT_ID,
    ProjectManager,
)
from core.workflow.authoring import WorkflowAuthoringError, WorkflowAuthoringService
from protein_workbench_public import bootstrap
from protein_workbench_public.bootstrap import create_application
from tests.support.protocol import validate_response


@pytest.mark.parametrize(
    ("changed_method_id", "affects_example"),
    [
        ("collection_ops.merge_scores.method", True),
        ("collection_ops.intersect_candidates.method", False),
    ],
)
def test_startup_admits_only_the_examples_selected_scientific_definitions(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    changed_method_id: str,
    affects_example: bool,
) -> None:
    monkeypatch.setenv("PROTEIN_WORKBENCH_DATA_ROOT", str(tmp_path))
    registrations = bootstrap.module_registrations()
    create_application(v2_environment_configuration={})
    catalog = build_frozen_catalog(registrations)
    original = WorkflowAuthoringService(
        ProjectManager(tmp_path / "projects"), catalog,
    )
    seed = original.load_active_commit(CANONICAL_3GB1_PROJECT_ID)
    example = original.load_active_commit(WEBUI_3GB1_PROJECT_ID)
    draft = original.load_draft(WEBUI_3GB1_PROJECT_ID)
    personal = original.copy_project(WEBUI_3GB1_PROJECT_ID, name="Current Method identity")
    current = original.commit(personal.id, workflow=original.load_draft(personal.id).workflow)
    assert changed_method_id not in {
        definition["contract_id"] for definition in seed.scientific_definitions
    }
    assert (
        changed_method_id in {
            definition["contract_id"] for definition in example.scientific_definitions
        }
    ) is affects_example

    package = next(
        item for item in registrations if item.package_id == "collection_ops"
    )
    changed_package = replace(
        package,
        methods=tuple(
            replace(
                method,
                algorithm_identity={
                    **method.algorithm_identity,
                    "name": "test-changed-scientific-algorithm",
                },
            )
            if method.method_id == changed_method_id else method
            for method in package.methods
        ),
    )
    changed_registrations = tuple(
        changed_package if item.package_id == package.package_id else item
        for item in registrations
    )
    # Supply real declarations at the production package-registration seam;
    # Catalog compilation, installation, admission, and persistence stay real.
    with monkeypatch.context() as changed:
        for registration in changed_registrations:
            changed.setattr(f"{registration.package_module}.package.MODULE_PACKAGE", registration)
        changed_app = create_application(v2_environment_configuration={})
        if affects_example:
            with pytest.raises(WorkflowAuthoringError) as raised:
                changed_app.state.workflow_authoring.require_verified_commit(
                    personal.id, workflow_commit_id=current.workflow_commit_id,
                )
            assert raised.value.code == "workflow_commit_identity_mismatch"
            assert raised.value.details == {
                "workflow_commit_id": current.workflow_commit_id,
            }

    create_application(v2_environment_configuration={})
    restored = WorkflowAuthoringService(
        ProjectManager(tmp_path / "projects"), catalog,
    )
    assert restored.load_active_commit(CANONICAL_3GB1_PROJECT_ID) == seed
    assert restored.load_active_commit(WEBUI_3GB1_PROJECT_ID) == example
    assert restored.load_draft(WEBUI_3GB1_PROJECT_ID) == draft


def test_webui_example_public_journey_and_prompt_contract(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.setenv("PROTEIN_WORKBENCH_DATA_ROOT", str(tmp_path))

    with TestClient(create_application(v2_environment_configuration={})) as http:
        projects_response = http.get("/api/v2/projects")
        assert projects_response.status_code == 200
        example = next(
            project
            for project in projects_response.json()["projects"]
            if project["id"] == WEBUI_3GB1_PROJECT_ID
        )
        assert example["project_kind"] == "default_example"
        assert example["seed"] is True
        assert example["latest_run_id"].startswith("run-")
        run_response = http.get(
            f"/api/v2/projects/{WEBUI_3GB1_PROJECT_ID}/runs/{example['latest_run_id']}"
        )
        assert run_response.status_code == 200
        bundled_run = run_response.json()
        validate_response("run_projection", 200, bundled_run)
        assert bundled_run["status"] == "succeeded"
        assert bundled_run["scope"]["mode"] == "full"
        assert {
            "candidate.collection", "score.collection",
            "structure_comparison.alignment_evidence",
        } <= {output["port_type"]["contract_id"] for output in bundled_run["outputs"]}

        draft_response = http.get(
            f"/api/v2/projects/{WEBUI_3GB1_PROJECT_ID}/workflow/draft"
        )
        assert draft_response.status_code == 200
        draft = draft_response.json()
        workflow = draft["workflow"]
        nodes = {node["node_id"]: node for node in workflow["nodes"]}
        assert nodes["generate-paired"]["binding_id"] == (
            "esm3.generate_paired.biohub_medium"
        )
        assert nodes["generate-paired"]["node_parameters"] == {"num_samples": 7}
        assert "effective_seed" not in nodes["generate-paired"]["binding_parameters"]
        from protein_workbench_public.example_results import shipped_example_workflow
        from protein_workbench_public.workflow_codec import decode_workflow_document
        assert decode_workflow_document(workflow) == shipped_example_workflow()
        assert nodes["fold-stage-one"]["binding_id"] == (
            "folding.fold.esmfold2_remote"
        )
        assert nodes["design-children"]["binding_id"] == (
            "proteinmpnn.design.local"
        )

        copy_response = http.post(
            f"/api/v2/projects/{WEBUI_3GB1_PROJECT_ID}:copy",
            json={"name": "WebUI acceptance copy"},
        )
        assert copy_response.status_code == 201
        copied = copy_response.json()
        assert copied["project_kind"] == "personal"
        assert copied["copied_from_project_id"] == WEBUI_3GB1_PROJECT_ID
        assert copied["latest_run_id"] is None
        assert copied["reference_results_project_id"] is None
        copied_draft_response = http.get(f"/api/v2/projects/{copied['id']}/workflow/draft")
        assert copied_draft_response.status_code == 200
        copied_draft = copied_draft_response.json()

        author_node_id = next(
            node["node_id"]
            for node in workflow["nodes"]
            if node["node_type_id"] == "prompt_authoring.author"
        )
        opened_response = http.post(
            f"/api/v2/projects/{copied['id']}/prompt-authoring:open",
            json={"node_id": author_node_id},
        )
        assert opened_response.status_code == 200
        opened = opened_response.json()
        validate_response("open_prompt_authoring", 200, opened)
        residues = opened["residues"]
        assert len(residues) == 57
        assert not any(item["residue_id"] == "A:39" for item in residues)
        assert all(
            item["residue_handle"]
            == "residue-"
            + hashlib.sha256(item["residue_id"].encode("utf-8")).hexdigest()
            for item in residues
        )
        assert len({item["residue_handle"] for item in residues}) == 57

        labels = {
            item["residue_handle"]: item["residue_label"]
            for item in residues
        }
        sequence = {
            labels[item["residue_handle"]]: item
            for item in opened["tracks"]["sequence"]["values"]
        }
        coordinates = {
            labels[item["residue_handle"]]: item
            for item in opened["tracks"]["coordinates"]["values"]
        }
        assert opened["tracks"]["sequence"]["present"] is True
        assert opened["tracks"]["coordinates"]["present"] is True
        assert opened["tracks"]["secondary_structure"]["present"] is False
        assert opened["tracks"]["sasa"]["present"] is False
        assert sequence["36"]["value"] is not None
        assert coordinates["36"]["value"] is not None
        assert opened["source"] == {
            "kind": "pdb",
            "project_input_ref": "3GB1.pdb",
            "content_digest": opened["source"]["content_digest"],
            "chain_ids": ["A"],
            "merge_sources": [],
        }
        assert opened["function_annotations"] == []

        preview_response = http.post(
            f"/api/v2/projects/{copied['id']}/prompt-authoring:preview",
            json={"node_id": author_node_id, "document": opened["document"]},
        )
        assert preview_response.status_code == 200
        preview = preview_response.json()
        validate_response("preview_prompt_authoring", 200, preview)
        assert preview["summary"]["chains"] == [
            {"chain_id": "A", "length": 57}
        ]
        assert preview["diagnostics"] == []
        assert preview["changes"] == []

        deleted_document = {
            **opened["document"],
            "target_residues": [
                item
                for item in opened["document"]["target_residues"]
                if item["residue_id"] != "A:30"
            ],
        }
        deleted_response = http.post(
            f"/api/v2/projects/{copied['id']}/prompt-authoring:preview",
            json={
                "node_id": author_node_id,
                "document": deleted_document,
            },
        )
        assert deleted_response.status_code == 200
        deleted = deleted_response.json()
        validate_response("preview_prompt_authoring", 200, deleted)
        tombstone = next(
            item for item in deleted["residues"]
            if item["residue_id"] == "A:30"
        )
        assert tombstone["state"] == "pending-delete"
        assert {
            "kind": "residue",
            "action": "delete",
            "residue_handle": tombstone["residue_handle"],
        } in deleted["changes"]

        malformed = http.post(
            f"/api/v2/projects/{copied['id']}/prompt-authoring:preview",
            json={
                "node_id": author_node_id,
                "document": {"rigid_transforms": [{}]},
            },
        )
        assert malformed.status_code == 400
        validate_response(
            "preview_prompt_authoring",
            malformed.status_code,
            malformed.json(),
        )
        assert malformed.json()["error"]["details"]["field_path"][:3] == [
            "document",
            "rigid_transforms",
            0,
        ]

        rejected = http.put(
            f"/api/v2/projects/{copied['id']}/workspace",
            json={
                "workflow": workflow_with_prompt_document(
                    copied_draft["workflow"], author_node_id, preview["normalized_document"],
                ),
                "expected_draft_revision": 0,
            },
        )
        assert rejected.status_code == 400
        validate_response(
            "save_project_workspace",
            rejected.status_code,
            rejected.json(),
        )
        assert rejected.json()["error"]["details"]["field_path"] == [
            "expected_draft_revision"
        ]

        apply_response = http.put(
            f"/api/v2/projects/{copied['id']}/workspace",
            json={
                "workflow": workflow_with_prompt_document(
                    copied_draft["workflow"], author_node_id, preview["normalized_document"],
                ),
                "expected_draft_revision": copied_draft["draft_revision"],
            },
        )
        assert apply_response.status_code == 200
        validate_response(
            "save_project_workspace",
            apply_response.status_code,
            apply_response.json(),
        )
        assert apply_response.json()["draft"]["draft_revision"] > (
            copied_draft["draft_revision"]
        )

        unchanged_example = http.get(
            f"/api/v2/projects/{WEBUI_3GB1_PROJECT_ID}/workflow/draft"
        ).json()
        assert unchanged_example["draft_revision"] == draft["draft_revision"]


def test_teaching_inputs_remain_request_local_until_complete_explicit_save(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    import base64

    monkeypatch.setenv("PROTEIN_WORKBENCH_DATA_ROOT", str(tmp_path))
    app = create_application(v2_environment_configuration={})
    with TestClient(app, raise_server_exceptions=False) as http:
        scope = f"/api/v2/projects/{WEBUI_3GB1_PROJECT_ID}"
        before_projects = http.get("/api/v2/projects").json()
        before_workspace = http.get(f"{scope}/workspace").json()
        before_inputs = http.get(f"{scope}/inputs").json()
        inputs = [
            {"project_input_ref": "new-sequence", "filename": "new.fasta",
             "content_base64": base64.b64encode(b">new\nACD\n").decode()},
            {"project_input_ref": "unused-sequence", "filename": "unused.fasta",
             "content_base64": base64.b64encode(b">unused\nGGG\n").decode()},
        ]
        inspected = http.post(f"{scope}/inputs/new-sequence:inspect", json={
            "format": "fasta", "input": inputs[0],
        })
        assert inspected.status_code == 200, inspected.text
        validate_response("inspect_project_input", 200, inspected.json())
        workflow = {
            "schema_version": "2.1.0", "workflow_id": WEBUI_3GB1_PROJECT_ID,
            "nodes": [
                {"node_id": "input", "node_type_id": "protein_io.import_sequence",
                 "binding_id": "protein_io.import_sequence.direct",
                 "node_parameters": {"project_input_ref": "new-sequence"}, "binding_parameters": {}},
                {"node_id": "edit", "node_type_id": "prompt_authoring.author",
                 "binding_id": "prompt_authoring.author.direct",
                 "node_parameters": {"document": {"chains": [{"chain_id": "A", "length": 3}]}}, "binding_parameters": {}},
            ],
            "edges": [{"source_node_id": "input", "source_port": "sequence",
                       "target_node_id": "edit", "target_port": "sequence_source"}],
            "observation_selectors": [], "selection_objectives": [],
        }
        for operation, extra in (("open", {}), ("preview", {"document": {"chains": [{"chain_id": "A", "length": 3}]}})):
            response = http.post(f"{scope}/prompt-authoring:{operation}", json={
                "node_id": "edit", "workflow": workflow,
                "prospective_inputs": inputs, **extra,
            })
            assert response.status_code == 200, response.text
            validate_response(f"{operation}_prompt_authoring", 200, response.json())
            assert len(response.json()["residues"]) == 3
        absent = http.post(f"{scope}/prompt-authoring:open", json={
            "node_id": "edit", "workflow": workflow,
        })
        assert absent.status_code == 404, absent.text
        assert http.get("/api/v2/projects").json() == before_projects
        assert http.get(f"{scope}/workspace").json() == before_workspace
        assert http.get(f"{scope}/inputs").json() == before_inputs
        ui_state = {"canvas": {"positions": {"edit": {"x": 12, "y": 34}}}}
        save_request = {"name": "My saved work", "workflow": workflow,
                        "ui_state": ui_state, "inputs": inputs}
        original_publish = app.state.workflow_authoring._publish_workspace
        def fail_publish(*args: object, **kwargs: object) -> None:
            raise OSError("injected workspace publication failure")
        with monkeypatch.context() as failure:
            failure.setattr(app.state.workflow_authoring, "_publish_workspace", fail_publish)
            failed = http.post(f"{scope}:copy", json=save_request)
            assert failed.status_code == 500
        assert app.state.workflow_authoring._publish_workspace == original_publish
        assert http.get("/api/v2/projects").json() == before_projects
        saved = http.post(f"{scope}:copy", json=save_request)
        assert saved.status_code == 201, saved.text
        project = saved.json()
        assert project["reference_results_project_id"] is None
        assert project["latest_run_id"] is None
        saved_scope = f"/api/v2/projects/{project['id']}"
        workspace = http.get(f"{saved_scope}/workspace").json()
        assert workspace["draft"]["workflow"] == {**workflow, "workflow_id": project["id"]}
        assert workspace["ui_state"] == ui_state
        adopted = http.get(f"{saved_scope}/inputs").json()["inputs"]
        assert {item["project_input_ref"] for item in adopted} == {"new-sequence", "unused-sequence"}
        assert next(item for item in adopted if item["project_input_ref"] == "new-sequence")["content_digest"] == inspected.json()["content_digest"]
        reopened = http.post(f"{saved_scope}/prompt-authoring:open", json={"node_id": "edit"})
        assert reopened.status_code == 200, reopened.text
        assert len(reopened.json()["residues"]) == 3
        assert http.get(f"{scope}/workspace").json() == before_workspace
        assert http.get(f"{scope}/inputs").json() == before_inputs
