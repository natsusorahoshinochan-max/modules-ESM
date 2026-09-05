"""Public acceptance for the current immutable WebUI 3GB1 example."""

from __future__ import annotations

import hashlib

from fastapi.testclient import TestClient

from core.project.manager import WEBUI_3GB1_PROJECT_ID
from protein_workbench_public.bootstrap import create_application
from tests.support.protocol import validate_response


def test_webui_example_public_journey_and_prompt_contract(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.setenv("PROTEIN_WORKBENCH_DATA_ROOT", str(tmp_path))

    with TestClient(create_application()) as http:
        projects_response = http.get("/api/v2/projects")
        assert projects_response.status_code == 200
        example = next(
            project
            for project in projects_response.json()["projects"]
            if project["id"] == WEBUI_3GB1_PROJECT_ID
        )
        assert example["project_kind"] == "default_example"
        assert example["seed"] is True
        assert example["latest_run_id"] is None

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

        rejected = http.post(
            f"/api/v2/projects/{copied['id']}/prompt-authoring:apply",
            json={
                "node_id": author_node_id,
                "document": preview["normalized_document"],
                "preview_digest": "sha256:" + "0" * 64,
            },
        )
        assert rejected.status_code == 400
        validate_response(
            "apply_prompt_authoring",
            rejected.status_code,
            rejected.json(),
        )
        assert rejected.json()["error"]["details"]["field_path"] == [
            "preview_digest"
        ]

        apply_response = http.post(
            f"/api/v2/projects/{copied['id']}/prompt-authoring:apply",
            json={
                "node_id": author_node_id,
                "document": preview["normalized_document"],
                "preview_digest": preview["preview_digest"],
            },
        )
        assert apply_response.status_code == 200
        validate_response(
            "apply_prompt_authoring",
            apply_response.status_code,
            apply_response.json(),
        )
        assert apply_response.json()["draft"]["draft_revision"] > (
            draft["draft_revision"]
        )

        unchanged_example = http.get(
            f"/api/v2/projects/{WEBUI_3GB1_PROJECT_ID}/workflow/draft"
        ).json()
        assert unchanged_example["draft_revision"] == draft["draft_revision"]
