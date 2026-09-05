"""Independent acceptance regressions; execute only on the cloud host."""
from __future__ import annotations

from collections.abc import Iterator
import base64
from typing import Any

import pytest
from fastapi.testclient import TestClient

from core.project.manager import WEBUI_3GB1_PROJECT_ID
from modules.prompt_authoring.package import _AssembleOperation, _DecomposeOperation
from modules.prompt_authoring.recipe import apply_prompt_recipe
from protein_workbench_public.bootstrap import create_application
from tests.fixtures.public_v2 import wait_for_testclient_run_terminal
from tests.test_prompt_assemble_materialize_v2 import _Call, _Port, _Value


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> Iterator[tuple[TestClient, str]]:
    monkeypatch.setenv("PROTEIN_WORKBENCH_DATA_ROOT", str(tmp_path))
    with TestClient(create_application(), raise_server_exceptions=False) as http:
        response = http.post(
            f"/api/v2/projects/{WEBUI_3GB1_PROJECT_ID}:copy",
            json={"name": "Independent acceptance regression"},
        )
        assert response.status_code == 201, response.text
        yield http, response.json()["id"]


def node(name: str, kind: str, document: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "node_id": name, "node_type_id": f"prompt_authoring.{kind}",
        "binding_id": f"prompt_authoring.{kind}.direct",
        "node_parameters": {} if document is None else {"document": document},
        "binding_parameters": {},
    }


def edge(source: str, output: str, target: str, port: str) -> dict[str, str]:
    return {"source_node_id": source, "source_port": output,
            "target_node_id": target, "target_port": port}


def save(client: tuple[TestClient, str], nodes: list[dict[str, Any]], edges: list[dict[str, str]]) -> None:
    http, project = client
    response = http.put(f"/api/v2/projects/{project}/workflow/draft", json={"workflow": {
        "schema_version": "2.1.0", "workflow_id": project,
        "nodes": nodes, "edges": edges, "observation_selectors": [], "selection_objectives": [],
    }})
    assert response.status_code == 200, response.text


def recipe(document: dict[str, Any]) -> Any:
    return apply_prompt_recipe(sequence_source=None, structure_source=None,
                               prompt_source=None, merge_sources=(), document=document)


def run_workflow(client: tuple[TestClient, str]) -> dict[str, Any]:
    http, project = client
    draft = http.get(f"/api/v2/projects/{project}/workflow/draft")
    assert draft.status_code == 200, draft.text
    committed = http.post(f"/api/v2/projects/{project}/workflow:commit", json={"workflow": draft.json()["workflow"]})
    assert committed.status_code == 200, committed.text
    started = http.post(f"/api/v2/projects/{project}/runs", json={
        "workflow_commit_id": committed.json()["workflow_commit_id"], "client_request_id": "independent-review",
    })
    assert started.status_code == 202, started.text
    result = wait_for_testclient_run_terminal(http, project, started.json()["run_id"], timeout_seconds=30)
    print("real Workflow Run:", result["status"], result["node_dispositions"])
    return result


def assembled_workflow(client: tuple[TestClient, str], *, annotations_document: dict[str, Any], optional_edges: bool) -> dict[str, Any]:
    base = {"chains": [{"chain_id": "A", "length": 3}]}
    nodes = [node("base", "author", base), node("annotation-base", "author", annotations_document),
             node("decompose", "decompose"), node("annotation-decompose", "decompose"),
             node("assemble", "assemble"), node("edit", "author", {})]
    edges = [edge("base", "protein_prompt", "decompose", "protein_prompt"),
             edge("annotation-base", "protein_prompt", "annotation-decompose", "protein_prompt"),
             edge("decompose", "sequence", "assemble", "sequence"),
             edge("decompose", "coordinates", "assemble", "coordinates"),
             edge("annotation-decompose", "function_annotations", "assemble", "function_annotations"),
             edge("assemble", "protein_prompt", "edit", "prompt_source")]
    if optional_edges:
        edges += [edge("decompose", track, "assemble", track) for track in ("secondary_structure", "sasa")]
    save(client, nodes, edges)
    return base


def test_matching_assembly_control(client: tuple[TestClient, str]) -> None:
    assembled_workflow(client, annotations_document={"chains": [{"chain_id": "A", "length": 3}]}, optional_edges=False)
    http, project = client
    response = http.post(f"/api/v2/projects/{project}/prompt-authoring:preview", json={"node_id": "edit", "document": {}})
    assert response.status_code == 200, response.text
    assert response.json()["diagnostics"] == []


def test_preview_accepts_repositioned_explicit_insertion(client: tuple[TestClient, str]) -> None:
    baseline = {"chains": [{"chain_id": "A", "length": 2}], "target_residues": [
        {"residue_id": "A:1", "origin": "source"},
        {"residue_id": "A:inserted.x", "origin": "inserted"},
        {"residue_id": "A:2", "origin": "source"},
    ]}
    candidate = {**baseline, "target_residues": [baseline["target_residues"][1], baseline["target_residues"][0], baseline["target_residues"][2]]}
    assert tuple(recipe(baseline).layout.residue_ids) == ("A:1", "A:inserted.x", "A:2")
    assert tuple(recipe(candidate).layout.residue_ids) == ("A:inserted.x", "A:1", "A:2")
    save(client, [node("edit", "author", baseline)], [])
    http, project = client
    response = http.post(f"/api/v2/projects/{project}/prompt-authoring:preview", json={"node_id": "edit", "document": candidate})
    assert response.status_code == 200, response.text
    assert response.json()["diagnostics"] == []


def test_preview_rejects_annotation_layout_mismatch_like_runtime(client: tuple[TestClient, str]) -> None:
    annotation_doc = {"chains": [{"chain_id": "A", "length": 2}], "function_annotations": [
        {"label": "site", "start_residue_id": "A:1", "end_residue_id": "A:2"},
    ]}
    base = assembled_workflow(client, annotations_document=annotation_doc, optional_edges=False)
    main = recipe(base)
    other = recipe(annotation_doc)
    main_outputs = _DecomposeOperation().execute(_Call(inputs={"protein_prompt": _Port("protein.prompt", "one", (_Value(main),))}))
    other_outputs = _DecomposeOperation().execute(_Call(inputs={"protein_prompt": _Port("protein.prompt", "one", (_Value(other),))}))
    inputs = {port: _Port(f"residue.condition.{port}", "one", (_Value(value),)) for port, value in main_outputs.items()}
    inputs["function_annotations"] = _Port("residue.condition.function_annotations", "one", (_Value(other_outputs["function_annotations"]),))
    with pytest.raises(ValueError, match="share one ResidueLayout"):
        _AssembleOperation().execute(_Call(inputs=inputs))
    http, project = client
    response = http.post(f"/api/v2/projects/{project}/prompt-authoring:preview", json={"node_id": "edit", "document": {}})
    print("mismatched-annotation-layout preview:", response.status_code, response.text)
    if response.status_code == 200 and not response.json()["diagnostics"]:
        preview = response.json()
        applied = http.post(f"/api/v2/projects/{project}/prompt-authoring:apply", json={
            "node_id": "edit", "document": preview["normalized_document"], "preview_digest": preview["preview_digest"],
        })
        print("mismatched-annotation-layout Apply:", applied.status_code)
    result = run_workflow(client)
    assert result["status"] == "failed"
    assert any(item["node_id"] == "assemble" and item["outcome"] == "failed" for item in result["node_dispositions"])
    assert response.status_code == 400 or (response.status_code == 200 and response.json()["diagnostics"]), "Preview admitted an assembly that execution rejects"


def test_preview_preserves_connected_absent_optional_tracks(client: tuple[TestClient, str]) -> None:
    base = assembled_workflow(client, annotations_document={"chains": [{"chain_id": "A", "length": 3}]}, optional_edges=True)
    prompt = recipe(base)
    outputs = _DecomposeOperation().execute(_Call(inputs={"protein_prompt": _Port("protein.prompt", "one", (_Value(prompt),))}))
    inputs = {port: _Port(f"residue.condition.{port}", "one", (_Value(value),)) for port, value in outputs.items()}
    runtime_result = _AssembleOperation().execute(_Call(inputs=inputs))["protein_prompt"]
    assert runtime_result.secondary_structure is None and runtime_result.sasa is None
    assert run_workflow(client)["status"] == "succeeded"
    http, project = client
    response = http.post(f"/api/v2/projects/{project}/prompt-authoring:preview", json={"node_id": "edit", "document": {}})
    assert response.status_code == 200, response.text
    assert response.json()["diagnostics"] == []
    assert response.json()["tracks"]["secondary_structure"]["present"] is False


def test_preview_can_repair_stale_sequence_chain_declaration(client: tuple[TestClient, str]) -> None:
    source_doc = {"chains": [{"chain_id": "A", "length": 4}], "track_edits": [
        {"track": "sequence", "action": "replace", "residue_id": f"A:{i}", "value": "A"}
        for i in range(1, 5)
    ]}
    saved_doc = {"chains": [{"chain_id": "A", "length": 3}]}
    corrected_doc = {"chains": [{"chain_id": "A", "length": 4}]}
    materializer = {"node_id": "materialize", "node_type_id": "residue_data.materialize_sequence",
                    "binding_id": "residue_data.materialize_sequence.direct", "node_parameters": {}, "binding_parameters": {}}
    save(client, [node("base", "author", source_doc), node("decompose", "decompose"),
                  materializer, node("edit", "author", saved_doc)], [
        edge("base", "protein_prompt", "decompose", "protein_prompt"),
        edge("decompose", "sequence", "materialize", "sequence"),
        edge("materialize", "sequence", "edit", "sequence_source"),
    ])
    from modules.residue_data.implementation import materialize_sequence
    from datatypes.residue import ResidueTrack
    source_prompt = recipe(source_doc)
    sequence = materialize_sequence(ResidueTrack(source_prompt.layout, source_prompt.sequence))
    assert apply_prompt_recipe(sequence_source=sequence, structure_source=None, prompt_source=None,
                               merge_sources=(), document=corrected_doc).layout.length == 4
    http, project = client
    opened = http.post(f"/api/v2/projects/{project}/prompt-authoring:open", json={"node_id": "edit"})
    assert opened.status_code == 200, opened.text
    assert opened.json()["baseline_diagnostics"]
    assert opened.json()["residues"] == []
    response = preview(client, saved_doc)
    assert response.json()["diagnostics"]
    assert response.json()["baseline_diagnostics"]
    result = apply_preview(client, corrected_doc)
    assert result["baseline_diagnostics"]
    assert result["changes"] == []
    assert len(result["residues"]) == 4
    assert run_workflow(client)["status"] == "succeeded"


def preview(client: Any, document: dict[str, Any], node_id: str = "edit") -> Any:
    http, project = client
    return http.post(f"/api/v2/projects/{project}/prompt-authoring:preview", json={"node_id": node_id, "document": document})

def test_fasta_source_must_be_admitted_before_overrides(client: Any) -> None:
    http, project = client
    imported = http.post(f"/api/v2/projects/{project}/inputs", json={
        "filename": "bad.fasta", "content_base64": base64.b64encode(b">source\nA!C\n").decode(),
    })
    assert imported.status_code == 201, imported.text
    source = {"node_id": "source", "node_type_id": "protein_io.import_sequence", "binding_id": "protein_io.import_sequence.direct",
              "node_parameters": {"project_input_ref": imported.json()["project_input_ref"]}, "binding_parameters": {}}
    document = {"chains": [{"chain_id": "A", "length": 3}], "track_edits": [
        {"track": "sequence", "action": "replace", "residue_id": "A:2", "value": "G"}]}
    save(client, [source, node("edit", "author", document)], [edge("source", "sequence", "edit", "sequence_source")])
    response = preview(client, document)
    print("FASTA preview", response.status_code, response.text)
    if response.status_code == 200 and not response.json()["diagnostics"]:
        p = response.json()
        applied = http.post(f"/api/v2/projects/{project}/prompt-authoring:apply", json={"node_id": "edit", "document": document, "preview_digest": p["preview_digest"]})
        print("FASTA Apply", applied.status_code)
    result = run_workflow(client)
    assert result["status"] == "failed"
    assert any(x["node_id"] == "source" and x["outcome"] == "failed" for x in result["node_dispositions"])
    assert response.status_code == 400 or (response.status_code == 200 and response.json()["diagnostics"])

@pytest.mark.parametrize("track,value", [("coordinates", {"atom_coordinates": [{"atom_name": "CA", "coordinates": [0, 1, 2]}]}), ("secondary_structure", "H"), ("sasa", 12)])
def test_other_assembly_layout_mismatches_are_diagnosed(client: Any, track: str, value: Any) -> None:
    base = {"chains": [{"chain_id": "A", "length": 3}]}
    other = {"chains": [{"chain_id": "A", "length": 2}], "track_edits": [{"track": track, "action": "replace", "residue_id": "A:1", "value": value}]}
    nodes = [node("base", "author", base), node("other", "author", other), node("d1", "decompose"), node("d2", "decompose"), node("assemble", "assemble"), node("edit", "author", {})]
    edges = [edge("base", "protein_prompt", "d1", "protein_prompt"), edge("other", "protein_prompt", "d2", "protein_prompt"), edge("assemble", "protein_prompt", "edit", "prompt_source")]
    edges += [edge("d2" if p == track else "d1", p, "assemble", p) for p in ("sequence", "coordinates", "function_annotations")]
    if track != "coordinates":
        edges.append(edge("d2", track, "assemble", track))
    save(client, nodes, edges)
    response = preview(client, {})
    print("mismatch", track, response.status_code, response.text)
    assert response.status_code == 400 or (response.status_code == 200 and response.json()["diagnostics"])

@pytest.mark.parametrize("track", ["secondary_structure", "sasa"])
def test_present_all_null_assembly_control(client: Any, track: str) -> None:
    document = {"chains": [{"chain_id": "A", "length": 3}], "track_edits": [{"track": track, "action": "clear", "residue_id": "A:1"}]}
    save(client, [node("base", "author", document), node("d", "decompose"), node("assemble", "assemble"), node("edit", "author", {})],
         [edge("base", "protein_prompt", "d", "protein_prompt"), edge("assemble", "protein_prompt", "edit", "prompt_source")] +
         [edge("d", p, "assemble", p) for p in ("sequence", "coordinates", "function_annotations", track)])
    response = preview(client, {})
    assert response.status_code == 200, response.text
    assert response.json()["diagnostics"] == []
    assert response.json()["tracks"][track]["present"] is True
    assert all(x["value"] is None for x in response.json()["tracks"][track]["values"])
    assert run_workflow(client)["status"] == "succeeded"

def test_random_insert_axis_change_variant(client: Any) -> None:
    # Same saved random IDs can move after a legitimate source deletion.
    for seed in range(50):
        base = {"chains": [{"chain_id": "A", "length": 4}], "random_operations": [{"kind": "insert", "seed": seed, "count": 2}]}
        changed = {**base, "target_residues": [{"residue_id": f"A:{i}", "origin": "source"} for i in (2, 3, 4)]}
        before = tuple(recipe(base).layout.residue_ids)
        after = tuple(recipe(changed).layout.residue_ids)
        common = set(before) & set(after)
        if [r for r in before if r in common] != [r for r in after if r in common]:
            break
    else:
        pytest.fail("could not realize test boundary")
    print("seed/layouts", seed, before, after)
    save(client, [node("edit", "author", base)], [])
    response = preview(client, changed)
    assert response.status_code == 200, response.text
    assert response.json()["diagnostics"] == []

def test_merge_order_and_digest_control(client: Any) -> None:
    def source(letter: str) -> dict[str, Any]:
        return {"chains": [{"chain_id": "A", "length": 1}], "track_edits": [{"track": "sequence", "action": "replace", "residue_id": "A:1", "value": letter}]}
    doc = {"chains": [{"chain_id": "A", "length": 1}], "source_merges": [{"source_index": 0,
        "correspondence": [{"disposition": "match", "source_residue_id": "A:1", "target_residue_id": "A:1"}],
        "track_decisions": {p: "adopt" if p == "sequence" else "preserve" for p in ("sequence", "coordinates", "secondary_structure", "sasa", "function_annotations")}}]}
    nodes = [node("a", "author", source("A")), node("b", "author", source("G")), node("edit", "author", doc)]
    edges = [edge("a", "protein_prompt", "edit", "merge_sources"), edge("b", "protein_prompt", "edit", "merge_sources")]
    save(client, nodes, edges)
    first = preview(client, doc).json()
    assert first["diagnostics"] == []
    assert first["tracks"]["sequence"]["values"][0]["value"] == "A"
    save(client, nodes, list(reversed(edges)))
    second = preview(client, doc).json()
    assert second["diagnostics"] == []
    assert second["tracks"]["sequence"]["values"][0]["value"] == "G"
    assert first["preview_digest"] != second["preview_digest"]
    http, project = client
    rejected = http.post(f"/api/v2/projects/{project}/prompt-authoring:apply", json={"node_id": "edit", "document": doc, "preview_digest": first["preview_digest"]})
    assert rejected.status_code == 400

@pytest.mark.parametrize("mode", ["explicit", "inherited", "merged"])
def test_overlapping_annotations_across_sources(client: Any, mode: str) -> None:
    source = {"chains": [{"chain_id": "A", "length": 3}], "function_annotations": [
        {"label": "one", "start_residue_id": "A:1", "end_residue_id": "A:2"},
        {"label": "two", "start_residue_id": "A:2", "end_residue_id": "A:3"}]}
    if mode == "explicit":
        saved, doc = {}, {"function_annotations": source["function_annotations"]}
        edges = [edge("source", "protein_prompt", "edit", "prompt_source")]
    elif mode == "inherited":
        saved, doc = {}, {}
        edges = [edge("source", "protein_prompt", "edit", "prompt_source")]
    else:
        saved = {"chains": [{"chain_id": "A", "length": 3}]}
        doc = {**saved, "source_merges": [{"source_index": 0,
            "correspondence": [{"disposition": "match", "source_residue_id": f"A:{i}", "target_residue_id": f"A:{i}"} for i in (1,2,3)],
            "track_decisions": {p: "adopt" if p == "function_annotations" else "preserve" for p in ("sequence", "coordinates", "secondary_structure", "sasa", "function_annotations")}}]}
        edges = [edge("source", "protein_prompt", "edit", "merge_sources")]
    save(client, [node("source", "author", source), node("edit", "author", saved)], edges)
    response = preview(client, doc)
    print("overlap", mode, response.status_code, response.text)
    assert response.status_code == 200, response.text
    assert response.json()["diagnostics"] == []
    assert len(response.json()["function_annotations"]) == 2


def test_upstream_author_document_uses_owning_schema(client: Any) -> None:
    source = {"chains": [{"chain_id": "A", "length": 1}], "composition_id": "forbidden-old-field"}
    save(client, [node("source", "author", source), node("edit", "author", {})], [edge("source", "protein_prompt", "edit", "prompt_source")])
    response = preview(client, {})
    print("invalid upstream schema preview", response.status_code, response.text)
    http, project = client
    draft = http.get(f"/api/v2/projects/{project}/workflow/draft").json()
    committed = http.post(f"/api/v2/projects/{project}/workflow:commit", json={"workflow": draft["workflow"]})
    print("invalid upstream schema commit", committed.status_code, committed.text)
    assert committed.status_code == 422
    assert response.status_code == 400 or (response.status_code == 200 and response.json()["diagnostics"])


def apply_preview(client: tuple[TestClient, str], document: dict[str, Any]) -> dict[str, Any]:
    from protein_workbench_public.protocol import validate_schema
    http, project = client
    response = preview(client, document)
    assert response.status_code == 200, response.text
    result = response.json()
    validate_schema("#/$defs/PromptAuthoringPreview", result)
    assert result["diagnostics"] == []
    applied = http.post(f"/api/v2/projects/{project}/prompt-authoring:apply", json={
        "node_id": "edit", "document": document, "preview_digest": result["preview_digest"],
    })
    assert applied.status_code == 200, applied.text
    opened = http.post(f"/api/v2/projects/{project}/prompt-authoring:open", json={"node_id": "edit"})
    assert opened.status_code == 200, opened.text
    validate_schema("#/$defs/PromptAuthoringSnapshot", opened.json())
    assert opened.json()["document"] == result["normalized_document"]
    return result


@pytest.mark.parametrize("before,after,expected", [
    (("A:1", "A:x", "A:2"), ("A:x", "A:1", "A:2"), ("A:x", "A:1", "A:2")),
    (("A:1", "A:2", "A:3", "B:1", "B:2"), ("A:2", "B:2"), ("A:1", "A:2", "A:3", "B:1", "B:2")),
    (("A:1", "A:2", "B:1"), ("B:1",), ("B:1", "A:1", "A:2")),
    (("A:1", "A:2", "A:3"), ("A:2", "A:x", "A:3"), ("A:1", "A:2", "A:x", "A:3")),
])
def test_projection_axis_obeys_candidate_order(before: tuple[str, ...], after: tuple[str, ...], expected: tuple[str, ...]) -> None:
    from datatypes.prompt import ProteinPrompt
    from datatypes.residue import ResidueLayout
    from modules.prompt_authoring.authoring import PromptAuthoringService
    def prompt(ids: tuple[str, ...]) -> ProteinPrompt:
        return ProteinPrompt(ResidueLayout(ids), tuple(None for _ in ids), tuple(None for _ in ids))
    axis = PromptAuthoringService._display_axis(prompt(before), prompt(after))
    assert axis == expected
    assert len(axis) == len(set(before) | set(after))
    assert tuple(r for r in axis if r in after) == after


def test_order_change_and_apply_preserve_identity(client: tuple[TestClient, str]) -> None:
    source = [{"residue_id": f"A:{i}", "origin": "source"} for i in (1, 2)]
    inserted = {"residue_id": "A:inserted.x", "origin": "inserted"}
    base = {"chains": [{"chain_id": "A", "length": 2}], "target_residues": [source[0], inserted, source[1]]}
    changed = {**base, "target_residues": [inserted, *source]}
    save(client, [node("edit", "author", base)], [])
    result = apply_preview(client, changed)
    assert [r["residue_id"] for r in result["residues"]] == ["A:inserted.x", "A:1", "A:2"]
    assert [c["kind"] for c in result["changes"]] == ["residue_order"]
    change = result["changes"][0]
    assert change["action"] == "replace"
    assert change["after_residue_handles"] == [r["residue_handle"] for r in result["residues"]]
    assert set(change["before_residue_handles"]) == set(change["after_residue_handles"])
    assert run_workflow(client)["status"] == "succeeded"


def test_ordinary_deletion_does_not_report_order_change(client: tuple[TestClient, str]) -> None:
    base = {"chains": [{"chain_id": "A", "length": 3}]}
    save(client, [node("edit", "author", base)], [])
    result = apply_preview(client, {**base, "target_residues": [{"residue_id": "A:2", "origin": "source"}]})
    assert [c["action"] for c in result["changes"]] == ["delete", "delete"]
    assert [r["residue_id"] for r in result["residues"] if r["state"] != "pending-delete"] == ["A:2"]


@pytest.mark.parametrize("mode", ["explicit", "inherited", "merged"])
def test_annotation_contract_has_no_overlap_policy(client: tuple[TestClient, str], mode: str) -> None:
    annotations = [
        {"label": "outer", "start_residue_id": "A:1", "end_residue_id": "A:4"},
        {"label": "another", "start_residue_id": "A:1", "end_residue_id": "A:4"},
        {"label": "inner", "start_residue_id": "A:2", "end_residue_id": "A:3"},
        {"label": "partial", "start_residue_id": "A:3", "end_residue_id": "A:4"},
    ]
    base = {"chains": [{"chain_id": "A", "length": 4}]}
    if mode == "explicit":
        save(client, [node("edit", "author", base)], [])
        doc = {**base, "function_annotations": annotations}
    else:
        doc = {} if mode == "inherited" else {**base, "source_merges": [{"source_index": 0,
            "correspondence": [{"disposition": "match", "source_residue_id": f"A:{i}", "target_residue_id": f"A:{i}"} for i in range(1, 5)],
            "track_decisions": {p: "adopt" if p == "function_annotations" else "preserve" for p in ("sequence", "coordinates", "secondary_structure", "sasa", "function_annotations")}}]}
        save(client, [node("source", "author", {**base, "function_annotations": annotations}), node("edit", "author", base if mode == "merged" else {})],
             [edge("source", "protein_prompt", "edit", "prompt_source" if mode == "inherited" else "merge_sources")])
    result = apply_preview(client, doc)
    assert [a["label"] for a in result["function_annotations"] if a["state"] != "pending-delete"] == ["another", "outer", "inner", "partial"]
    assert run_workflow(client)["status"] == "succeeded"


def test_duplicate_annotation_is_rejected_without_deduplication(client: tuple[TestClient, str]) -> None:
    base = {"chains": [{"chain_id": "A", "length": 2}]}
    annotation = {"label": "site", "start_residue_id": "A:1", "end_residue_id": "A:2"}
    save(client, [node("edit", "author", base)], [])
    document = {**base, "function_annotations": [annotation, annotation]}
    response = preview(client, document)
    assert response.status_code == 200
    assert response.json()["diagnostics"]
    assert response.json()["normalized_document"]["function_annotations"] == [annotation, annotation]
    http, project = client
    applied = http.post(f"/api/v2/projects/{project}/prompt-authoring:apply", json={"node_id": "edit", "document": document, "preview_digest": response.json()["preview_digest"]})
    assert applied.status_code == 400
    saved = http.get(f"/api/v2/projects/{project}/workflow/draft").json()
    assert saved["workflow"]["nodes"][0]["node_parameters"]["document"] == base


def test_deleted_overlap_policy_is_not_admitted(client: tuple[TestClient, str]) -> None:
    base = {"chains": [{"chain_id": "A", "length": 1}]}
    save(client, [node("edit", "author", base)], [])
    response = preview(client, {**base, "overlap_policy": "allow"})
    assert response.status_code == 400
    assert response.json()["error"]["details"]["field_path"] == ["document"]
    assert "overlap_policy" in response.json()["error"]["message"]


def test_open_random_trace_matches_preview(client: tuple[TestClient, str]) -> None:
    base = {"chains": [{"chain_id": "A", "length": 3}], "random_operations": [{"kind": "insert", "seed": 42, "count": 1}]}
    save(client, [node("edit", "author", base)], [])
    http, project = client
    opened = http.post(f"/api/v2/projects/{project}/prompt-authoring:open", json={"node_id": "edit"}).json()
    result = preview(client, base).json()
    assert opened["random_selections"] == result["random_selections"]
    assert len(opened["random_selections"][0]["realized_residue_handles"]) == 1
