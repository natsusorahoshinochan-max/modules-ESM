"""Public acceptance for the separate immutable WebUI 3GB1 example."""

from __future__ import annotations

from collections import Counter
from typing import Any

from fastapi.testclient import TestClient

from core.project.manager import WEBUI_3GB1_PROJECT_ID, WEBUI_3GB1_RUN_ID
from protein_workbench_public.bootstrap import create_application


def _fields(value: dict[str, Any]) -> dict[str, Any]:
    return value["fields"]


def _typed(
    http: TestClient,
    node_id: str,
    output_port: str,
) -> dict[str, Any]:
    response = http.get(
        f"/api/v2/projects/{WEBUI_3GB1_PROJECT_ID}/runs/"
        f"{WEBUI_3GB1_RUN_ID}/outputs/{node_id}/{output_port}/values/0"
    )
    assert response.status_code == 200
    return response.json()["value"]


def _candidate_fields(value: dict[str, Any]) -> list[dict[str, Any]]:
    return [_fields(item) for item in _fields(value)["items"]]


def test_webui_example_public_journey_and_scientific_contracts(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.setenv("PROTEIN_WORKBENCH_DATA_ROOT", str(tmp_path))

    with TestClient(create_application()) as http:
        projects_response = http.get("/api/v2/projects")
        assert projects_response.status_code == 200
        projects = projects_response.json()["projects"]
        example = next(
            project
            for project in projects
            if project["id"] == WEBUI_3GB1_PROJECT_ID
        )
        assert example["project_kind"] == "default_example"
        assert example["seed"] is True
        assert example["latest_run_id"] == WEBUI_3GB1_RUN_ID

        draft_response = http.get(
            f"/api/v2/projects/{WEBUI_3GB1_PROJECT_ID}/workflow/draft"
        )
        assert draft_response.status_code == 200
        draft = draft_response.json()
        workflow = draft["workflow"]
        assert len(workflow["nodes"]) == 36
        nodes = {node["node_id"]: node for node in workflow["nodes"]}
        assert nodes["generate-paired"]["binding_id"] == (
            "esm3.generate_paired.biohub_medium"
        )
        assert nodes["generate-paired"]["node_parameters"] == {
            "effective_seed": 1603,
            "num_samples": 7,
        }
        assert nodes["fold-stage-one"]["binding_id"] == (
            "folding.fold.esmfold2_remote"
        )
        assert nodes["design-children"]["binding_id"] == (
            "proteinmpnn.design.local"
        )
        assert nodes["design-children"]["node_parameters"] == {
            "effective_seed": 1603,
            "num_sequences": 3,
        }
        assert nodes["relation-final"]["node_type_id"] == (
            "collection_ops.compose_relations"
        )
        assert nodes["relation-generated-structure-parent"]["node_type_id"] == (
            "collection_ops.relate_by_parent"
        )
        assert nodes["relation-generated-pairs"]["node_type_id"] == (
            "collection_ops.invert_relation"
        )
        assert nodes["align-final"]["node_type_id"] == (
            "structure_comparison.align_pairs"
        )
        assert nodes["tm-final"]["node_type_id"] == (
            "structure_comparison.tm_score_from_alignments"
        )

        objectives = {
            item["objective_id"]: item
            for item in workflow["selection_objectives"]
        }
        for prefix in ("stage-one", "final"):
            assert objectives[f"{prefix}-plddt"]["weight"] == 0.5
            assert objectives[f"{prefix}-parent-tm"]["weight"] == 0.5
        assert objectives["final-plddt"]["utility_transform"][
            "contract_id"
        ] == (
            "structure.plddt.mean_residue."
            "esmfold2_fast_biohub_2026_05.percent_to_unit"
        )
        assert objectives["final-parent-tm"]["utility_transform"][
            "contract_id"
        ] == (
            "structure_comparison.tm_score."
            "explicit_relation.identity"
        )

        counts = {
            ("generate-paired", "structure_candidates"): 7,
            ("take-top-four", "candidates"): 4,
            ("fold-stage-one", "structure_candidates"): 4,
            ("take-top-two", "candidates"): 2,
            ("design-children", "sequence_candidates"): 6,
            ("fold-final", "structure_candidates"): 6,
            ("take-top-three", "candidates"): 3,
        }
        typed_candidates = {
            key: _candidate_fields(_typed(http, *key)) for key in counts
        }
        assert {
            key: len(value) for key, value in typed_candidates.items()
        } == counts

        top_two_ids = {
            item["candidate_id"]
            for item in typed_candidates[("take-top-two", "candidates")]
        }
        designed = typed_candidates[("design-children", "sequence_candidates")]
        assert Counter(item["parent_ids"][0] for item in designed) == {
            candidate_id: 3 for candidate_id in top_two_ids
        }
        designed_ids = {item["candidate_id"] for item in designed}
        folded = typed_candidates[("fold-final", "structure_candidates")]
        assert {item["parent_ids"][0] for item in folded} == designed_ids

        relation = _fields(_typed(http, "relation-final", "relation"))
        pair_entries = [_fields(item) for item in relation["entries"]]
        assert len(pair_entries) == 6
        reference_ids = [
            _fields(item["reference"])["candidate_id"]
            for item in pair_entries
        ]
        assert Counter(reference_ids) == {
            candidate_id: 3 for candidate_id in top_two_ids
        }

        tm_scores = _fields(_typed(http, "tm-final", "scores"))["entries"]
        assert len(tm_scores) == 6
        for encoded in tm_scores:
            observation = _fields(encoded)
            assert _fields(observation["metric"])["contract_id"] == (
                "structure_comparison.tm_score"
            )
            context = _fields(observation["context"])
            assert context["pairing_mode"] == "explicit_relation"
            assert _fields(_fields(context["subject"])["candidate"])[
                "candidate_id"
            ] == _fields(observation["subject"])["candidate_id"]
            assert _fields(_fields(context["reference"])["candidate"])[
                "candidate_id"
            ] in top_two_ids

        run_response = http.get(
            f"/api/v2/projects/{WEBUI_3GB1_PROJECT_ID}/runs/"
            f"{WEBUI_3GB1_RUN_ID}"
        )
        assert run_response.status_code == 200
        run_projection = run_response.json()
        generated_outputs = [
            output
            for output in run_projection["outputs"]
            if output["node_id"] == "generate-paired"
        ]
        assert {output["output_port"] for output in generated_outputs} == {
            "sequence_candidates",
            "structure_candidates",
            "confidence_facts",
            "sequence_reconstruction_candidates",
            "sequence_reconstruction_confidence_facts",
        }
        relation_outputs = [
            output
            for output in run_projection["outputs"]
            if output["node_id"] in {
                "relation-generated-structure-parent",
                "relation-generated-pairs",
            }
        ]
        assert len(relation_outputs) == 2
        assert all(
            output["materialization"] == {
                "run_id": WEBUI_3GB1_RUN_ID,
                "resolution": "executed",
            }
            and output["producer_provenance"]["producer_run_id"]
            == WEBUI_3GB1_RUN_ID
            for output in relation_outputs
        )
        final_selection = next(
            item
            for item in run_projection["selection_results"]
            if item["selection_node_id"] == "rank-final"
        )
        assert [item["effective_weight"] for item in final_selection["objectives"]] == [
            0.5,
            0.5,
        ]
        assert final_selection["objectives"][1]["context_selector"][
            "pairing_mode"
        ] == "explicit_relation"

        copy_response = http.post(
            f"/api/v2/projects/{WEBUI_3GB1_PROJECT_ID}:copy",
            json={"name": "WebUI acceptance copy"},
        )
        assert copy_response.status_code == 201
        copied = copy_response.json()
        assert copied["project_kind"] == "personal"
        assert copied["copied_from_project_id"] == WEBUI_3GB1_PROJECT_ID
        assert copied["latest_run_id"] is None
        search = http.get(
            "/api/v2/projects", params={"name": "acceptance copy"}
        )
        assert [item["id"] for item in search.json()["projects"]] == [
            copied["id"]
        ]
        canonical_copy = http.post(
            "/api/v2/projects/canonical-3gb1:copy",
            json={"name": "must not copy canonical verification"},
        )
        assert canonical_copy.status_code == 404
        assert canonical_copy.json()["error"]["code"] == (
            "cross_scope_access_denied"
        )

        author_node_id = next(
            node["node_id"]
            for node in draft["workflow"]["nodes"]
            if node["node_type_id"] == "prompt_authoring.author"
        )
        opened_response = http.post(
            f"/api/v2/projects/{copied['id']}/prompt-authoring:open",
            json={"node_id": author_node_id},
        )
        assert opened_response.status_code == 200
        opened = opened_response.json()
        residues = opened["residues"]
        assert len(residues) == 56
        assert any(item["residue_label"] == "39" for item in residues)
        labels = {
            item["residue_handle"]: item["residue_label"] for item in residues
        }
        sequence = {
            labels[item["residue_handle"]]: item
            for item in opened["tracks"]["sequence"]
        }
        structure = {
            labels[item["residue_handle"]]: item
            for item in opened["tracks"]["structure"]
        }
        assert sequence["39"]["value"] is not None
        assert structure["39"]["value"] is not None
        assert all(
            item["value"] is None
            for item in opened["tracks"]["secondary_structure"]
        )
        assert all(
            item["value"] is None for item in opened["tracks"]["sasa"]
        )
        assert opened["function_annotations"] == []

        preview_response = http.post(
            f"/api/v2/projects/{copied['id']}/prompt-authoring:preview",
            json={
                "node_id": author_node_id,
                "document": opened["document"],
            },
        )
        assert preview_response.status_code == 200
        preview = preview_response.json()
        assert preview["summary"]["chains"] == [
            {"chain_id": "A", "length": 57}
        ]
        assert len(preview["residues"]) == 57
        assert not any(
            item["residue_label"] == "39" for item in preview["residues"]
        )
        assert (
            len(
                [
                    item
                    for item in preview["residues"]
                    if item["residue_label"].startswith("inserted.")
                ]
            )
            == 2
        )
        assert preview["diagnostics"] == []
        apply_response = http.post(
            f"/api/v2/projects/{copied['id']}/prompt-authoring:apply",
            json={
                "node_id": author_node_id,
                "document": preview["normalized_document"],
                "preview_digest": preview["preview_digest"],
            },
        )
        assert apply_response.status_code == 200
        applied = apply_response.json()["draft"]
        assert len(applied["workflow"]["nodes"]) == 36
        assert applied["draft_revision"] > draft["draft_revision"]

        unchanged_example = http.get(
            f"/api/v2/projects/{WEBUI_3GB1_PROJECT_ID}/workflow/draft"
        ).json()
        assert unchanged_example["draft_revision"] == draft["draft_revision"]
