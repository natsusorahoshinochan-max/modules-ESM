"""Public Prompt contracts for Preview, Apply, execution and exact identity."""

from __future__ import annotations

import base64
from tests.support.prompt_authoring import workflow_with_prompt_document

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from core.project.manager import WEBUI_3GB1_PROJECT_ID
from datatypes.prompt import ProteinPrompt
from modules.prompt_authoring.prompt_types import PROTEIN_PROMPT_PORT_TYPE
from modules.prompt_authoring.recipe import apply_prompt_recipe
from protein_workbench_public.bootstrap import create_application
from tests.support import inprocess_runs
from tests.support.protocol import validate_response
from tests.support.public_runs import PublicRunClient


@pytest.fixture
def client(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> Iterator[tuple[TestClient, str]]:
    monkeypatch.setenv("PROTEIN_WORKBENCH_DATA_ROOT", str(tmp_path))
    with TestClient(create_application(), raise_server_exceptions=False) as http:
        response = http.post(
            f"/api/v2/projects/{WEBUI_3GB1_PROJECT_ID}:copy",
            json={"name": "Public Prompt contract"},
        )
        assert response.status_code == 201, response.text
        yield http, response.json()["id"]


def draft_revision(client: tuple[TestClient, str]) -> int:
    http, project = client
    workspace = http.get(f"/api/v2/projects/{project}/workspace").json()
    draft = workspace["draft"]
    return draft["draft_revision"] if draft is not None else 0


def node(
    name: str, kind: str, document: dict[str, Any] | None = None
) -> dict[str, Any]:
    return {
        "node_id": name,
        "node_type_id": f"prompt_authoring.{kind}",
        "binding_id": f"prompt_authoring.{kind}.direct",
        "node_parameters": {} if document is None else {"document": document},
        "binding_parameters": {},
    }


def edge(source: str, output: str, target: str, port: str) -> dict[str, str]:
    return {
        "source_node_id": source,
        "source_port": output,
        "target_node_id": target,
        "target_port": port,
    }


def save(
    client: tuple[TestClient, str],
    nodes: list[dict[str, Any]],
    edges: list[dict[str, str]],
) -> None:
    http, project = client
    response = http.put(
        f"/api/v2/projects/{project}/workspace",
        json={
            "workflow": {
                "schema_version": "2.1.0",
                "workflow_id": project,
                "nodes": nodes,
                "edges": edges,
                "observation_selectors": [],
                "selection_objectives": [],
            }
        },
    )
    assert response.status_code == 200, response.text


def recipe(document: dict[str, Any]) -> ProteinPrompt:
    return apply_prompt_recipe(
        sequence_source=None,
        structure_source=None,
        prompt_source=None,
        merge_sources=(),
        document=document,
    )


def run_workflow(client: tuple[TestClient, str]) -> dict[str, Any]:
    http, project = client
    draft = http.get(f"/api/v2/projects/{project}/workflow/draft")
    assert draft.status_code == 200, draft.text
    committed = PublicRunClient(http).commit_workflow(project, draft.json()["workflow"])
    result = inprocess_runs.run_committed_workflow(
        http,
        project,
        workflow_commit_id=committed["workflow_commit_id"],
        request_id="independent-review",
        timeout_seconds=30,
    )
    return result


def assembled_workflow(
    client: tuple[TestClient, str],
    *,
    annotations_document: dict[str, Any],
    optional_edges: bool,
) -> dict[str, Any]:
    base = {"chains": [{"chain_id": "A", "length": 3}]}
    nodes = [
        node("base", "author", base),
        node("annotation-base", "author", annotations_document),
        node("decompose", "decompose"),
        node("annotation-decompose", "decompose"),
        node("assemble", "assemble"),
        node("edit", "author", {}),
    ]
    edges = [
        edge("base", "protein_prompt", "decompose", "protein_prompt"),
        edge(
            "annotation-base",
            "protein_prompt",
            "annotation-decompose",
            "protein_prompt",
        ),
        edge("decompose", "sequence", "assemble", "sequence"),
        edge("decompose", "coordinates", "assemble", "coordinates"),
        edge(
            "annotation-decompose",
            "function_annotations",
            "assemble",
            "function_annotations",
        ),
        edge("assemble", "protein_prompt", "edit", "prompt_source"),
    ]
    if optional_edges:
        edges += [
            edge("decompose", track, "assemble", track)
            for track in ("secondary_structure", "sasa")
        ]
    save(client, nodes, edges)
    return base


def test_matching_assembly_control(client: tuple[TestClient, str]) -> None:
    assembled_workflow(
        client,
        annotations_document={"chains": [{"chain_id": "A", "length": 3}]},
        optional_edges=False,
    )
    http, project = client
    response = http.post(
        f"/api/v2/projects/{project}/prompt-authoring:preview",
        json={"node_id": "edit", "document": {}},
    )
    assert response.status_code == 200, response.text
    assert response.json()["diagnostics"] == []


def test_preview_accepts_repositioned_explicit_insertion(
    client: tuple[TestClient, str]
) -> None:
    baseline = {
        "chains": [{"chain_id": "A", "length": 2}],
        "target_residues": [
            {"residue_id": "A:1", "origin": "source"},
            {"residue_id": "A:inserted.x", "origin": "inserted"},
            {"residue_id": "A:2", "origin": "source"},
        ],
    }
    candidate = {
        **baseline,
        "target_residues": [
            baseline["target_residues"][1],
            baseline["target_residues"][0],
            baseline["target_residues"][2],
        ],
    }
    assert tuple(recipe(baseline).layout.residue_ids) == ("A:1", "A:inserted.x", "A:2")
    assert tuple(recipe(candidate).layout.residue_ids) == ("A:inserted.x", "A:1", "A:2")
    save(client, [node("edit", "author", baseline)], [])
    http, project = client
    response = http.post(
        f"/api/v2/projects/{project}/prompt-authoring:preview",
        json={"node_id": "edit", "document": candidate},
    )
    assert response.status_code == 200, response.text
    assert response.json()["diagnostics"] == []


def test_preview_rejects_annotation_layout_mismatch_like_runtime(
    client: tuple[TestClient, str]
) -> None:
    annotation_doc = {
        "chains": [{"chain_id": "A", "length": 2}],
        "function_annotations": [
            {"label": "site", "start_residue_id": "A:1", "end_residue_id": "A:2"},
        ],
    }
    assembled_workflow(
        client, annotations_document=annotation_doc, optional_edges=False
    )
    assert_source_rejected_without_write(
        client, {}, "share one ResidueLayout"
    )
    result = run_workflow(client)
    assert result["status"] == "failed"
    assert any(
        item["node_id"] == "assemble" and item["outcome"] == "failed"
        for item in result["node_dispositions"]
    )


def test_preview_preserves_connected_absent_optional_tracks(
    client: tuple[TestClient, str]
) -> None:
    assembled_workflow(
        client,
        annotations_document={"chains": [{"chain_id": "A", "length": 3}]},
        optional_edges=True,
    )
    projection = run_workflow(client)
    assert projection["status"] == "succeeded"
    http, project = client
    for node_id in ("assemble", "edit"):
        output = next(
            item
            for item in projection["outputs"]
            if item["node_id"] == node_id and item["output_port"] == "protein_prompt"
        )
        canonical = PublicRunClient(http).typed_output_bytes(
            project, projection["run_id"], output, 0
        )
        prompt = PROTEIN_PROMPT_PORT_TYPE.decode(canonical)
        assert prompt.secondary_structure is None
        assert prompt.sasa is None
    response = preview(client, {})
    assert response.status_code == 200, response.text
    assert response.json()["diagnostics"] == []
    for track in ("secondary_structure", "sasa"):
        assert response.json()["tracks"][track]["present"] is False


def test_preview_can_repair_stale_sequence_chain_declaration(
    client: tuple[TestClient, str]
) -> None:
    source_doc = {
        "chains": [{"chain_id": "A", "length": 4}],
        "track_edits": [
            {
                "track": "sequence",
                "action": "replace",
                "residue_id": f"A:{i}",
                "value": "A",
            }
            for i in range(1, 5)
        ],
    }
    saved_doc = {"chains": [{"chain_id": "A", "length": 3}]}
    corrected_doc = {"chains": [{"chain_id": "A", "length": 4}]}
    materializer = {
        "node_id": "materialize",
        "node_type_id": "residue_data.materialize_sequence",
        "binding_id": "residue_data.materialize_sequence.direct",
        "node_parameters": {},
        "binding_parameters": {},
    }
    save(
        client,
        [
            node("base", "author", source_doc),
            node("decompose", "decompose"),
            materializer,
            node("edit", "author", saved_doc),
        ],
        [
            edge("base", "protein_prompt", "decompose", "protein_prompt"),
            edge("decompose", "sequence", "materialize", "sequence"),
            edge("materialize", "sequence", "edit", "sequence_source"),
        ],
    )
    from datatypes.residue import ResidueTrack
    from modules.residue_data.implementation import materialize_sequence

    source_prompt = recipe(source_doc)
    sequence = materialize_sequence(
        ResidueTrack(source_prompt.layout, source_prompt.sequence)
    )
    assert (
        apply_prompt_recipe(
            sequence_source=sequence,
            structure_source=None,
            prompt_source=None,
            merge_sources=(),
            document=corrected_doc,
        ).layout.length
        == 4
    )
    http, project = client
    opened = http.post(
        f"/api/v2/projects/{project}/prompt-authoring:open", json={"node_id": "edit"}
    )
    assert opened.status_code == 200, opened.text
    assert opened.json()["baseline_diagnostics"]
    assert opened.json()["residues"] == []
    response = preview(client, saved_doc)
    assert response.json()["diagnostics"]
    assert response.json()["baseline_diagnostics"]
    result = preview_and_save_workspace(client, corrected_doc)
    assert result["baseline_diagnostics"]
    assert result["changes"] == []
    assert len(result["residues"]) == 4
    assert run_workflow(client)["status"] == "succeeded"


def preview(
    client: tuple[TestClient, str], document: dict[str, Any], node_id: str = "edit"
) -> httpx.Response:
    http, project = client
    return http.post(
        f"/api/v2/projects/{project}/prompt-authoring:preview",
        json={"node_id": node_id, "document": document},
    )


def test_fasta_source_must_be_admitted_before_overrides(
    client: tuple[TestClient, str]
) -> None:
    http, project = client
    imported = http.post(
        f"/api/v2/projects/{project}/inputs",
        json={
            "filename": "bad.fasta",
            "content_base64": base64.b64encode(b">source\nA!C\n").decode(),
        },
    )
    assert imported.status_code == 201, imported.text
    source = {
        "node_id": "source",
        "node_type_id": "protein_io.import_sequence",
        "binding_id": "protein_io.import_sequence.direct",
        "node_parameters": {"project_input_ref": imported.json()["project_input_ref"]},
        "binding_parameters": {},
    }
    document = {
        "chains": [{"chain_id": "A", "length": 3}],
        "track_edits": [
            {
                "track": "sequence",
                "action": "replace",
                "residue_id": "A:2",
                "value": "G",
            }
        ],
    }
    save(
        client,
        [source, node("edit", "author", document)],
        [edge("source", "sequence", "edit", "sequence_source")],
    )
    assert_source_rejected_without_write(
        client, document, "uppercase amino-acid alphabet"
    )
    result = run_workflow(client)
    assert result["status"] == "failed"
    assert any(
        x["node_id"] == "source" and x["outcome"] == "failed"
        for x in result["node_dispositions"]
    )


@pytest.mark.parametrize(
    "track,value",
    [
        (
            "coordinates",
            {"atom_coordinates": [{"atom_name": "CA", "coordinates": [0, 1, 2]}]},
        ),
        ("secondary_structure", "H"),
        ("sasa", 12),
    ],
)
def test_other_assembly_layout_mismatches_are_diagnosed(
    client: tuple[TestClient, str], track: str, value: Any
) -> None:
    base = {"chains": [{"chain_id": "A", "length": 3}]}
    other = {
        "chains": [{"chain_id": "A", "length": 2}],
        "track_edits": [
            {"track": track, "action": "replace", "residue_id": "A:1", "value": value}
        ],
    }
    nodes = [
        node("base", "author", base),
        node("other", "author", other),
        node("d1", "decompose"),
        node("d2", "decompose"),
        node("assemble", "assemble"),
        node("edit", "author", {}),
    ]
    edges = [
        edge("base", "protein_prompt", "d1", "protein_prompt"),
        edge("other", "protein_prompt", "d2", "protein_prompt"),
        edge("assemble", "protein_prompt", "edit", "prompt_source"),
    ]
    edges += [
        edge("d2" if p == track else "d1", p, "assemble", p)
        for p in ("sequence", "coordinates", "function_annotations")
    ]
    if track != "coordinates":
        edges.append(edge("d2", track, "assemble", track))
    save(client, nodes, edges)
    assert_source_rejected_without_write(
        client, {}, "share one ResidueLayout"
    )


@pytest.mark.parametrize("track", ["secondary_structure", "sasa"])
def test_present_all_null_assembly_control(
    client: tuple[TestClient, str], track: str
) -> None:
    document = {
        "chains": [{"chain_id": "A", "length": 3}],
        "track_edits": [{"track": track, "action": "clear", "residue_id": "A:1"}],
    }
    save(
        client,
        [
            node("base", "author", document),
            node("d", "decompose"),
            node("assemble", "assemble"),
            node("edit", "author", {}),
        ],
        [
            edge("base", "protein_prompt", "d", "protein_prompt"),
            edge("assemble", "protein_prompt", "edit", "prompt_source"),
        ]
        + [
            edge("d", p, "assemble", p)
            for p in ("sequence", "coordinates", "function_annotations", track)
        ],
    )
    response = preview(client, {})
    assert response.status_code == 200, response.text
    assert response.json()["diagnostics"] == []
    assert response.json()["tracks"][track]["present"] is True
    assert all(x["value"] is None for x in response.json()["tracks"][track]["values"])
    assert run_workflow(client)["status"] == "succeeded"


def test_random_insert_axis_change_variant(client: tuple[TestClient, str]) -> None:
    # Same saved random IDs can move after a legitimate source deletion.
    for seed in range(50):
        base = {
            "chains": [{"chain_id": "A", "length": 4}],
            "random_operations": [{"kind": "insert", "seed": seed, "count": 2}],
        }
        changed = {
            **base,
            "target_residues": [
                {"residue_id": f"A:{i}", "origin": "source"} for i in (2, 3, 4)
            ],
        }
        before = tuple(recipe(base).layout.residue_ids)
        after = tuple(recipe(changed).layout.residue_ids)
        common = set(before) & set(after)
        if [r for r in before if r in common] != [r for r in after if r in common]:
            break
    else:
        pytest.fail("could not realize test boundary")
    save(client, [node("edit", "author", base)], [])
    response = preview(client, changed)
    assert response.status_code == 200, response.text
    assert response.json()["diagnostics"] == []


def test_merge_order_and_revision_conflict(client: tuple[TestClient, str]) -> None:
    def source(letter: str) -> dict[str, Any]:
        return {
            "chains": [{"chain_id": "A", "length": 1}],
            "track_edits": [
                {
                    "track": "sequence",
                    "action": "replace",
                    "residue_id": "A:1",
                    "value": letter,
                }
            ],
        }

    doc = {
        "chains": [{"chain_id": "A", "length": 1}],
        "source_merges": [
            {
                "source_index": 0,
                "correspondence": [
                    {
                        "disposition": "match",
                        "source_residue_id": "A:1",
                        "target_residue_id": "A:1",
                    }
                ],
                "track_adoptions": [{"track": "sequence", "source_residue_ids": ["A:1"], "mask_policy": "adopt"}],
                "adopt_annotations": [],
                "remove_annotations": [],
            }
        ],
    }
    nodes = [
        node("a", "author", source("A")),
        node("b", "author", source("G")),
        node("edit", "author", doc),
    ]
    edges = [
        edge("a", "protein_prompt", "edit", "merge_sources"),
        edge("b", "protein_prompt", "edit", "merge_sources"),
    ]
    save(client, nodes, edges)
    original_revision = draft_revision(client)
    first = preview(client, doc).json()
    assert first["diagnostics"] == []
    assert first["tracks"]["sequence"]["values"][0]["value"] == "A"
    save(client, nodes, list(reversed(edges)))
    second = preview(client, doc).json()
    assert second["diagnostics"] == []
    assert second["tracks"]["sequence"]["values"][0]["value"] == "G"
    http, project = client
    workspace = http.get(f"/api/v2/projects/{project}/workspace").json()
    rejected = http.put(
        f"/api/v2/projects/{project}/workspace",
        json={
            "workflow": workflow_with_prompt_document(workspace["draft"]["workflow"], "edit", first["normalized_document"]),
            "expected_draft_revision": original_revision,
        },
    )
    assert rejected.status_code == 400


def test_upstream_author_document_uses_owning_schema(
    client: tuple[TestClient, str]
) -> None:
    source = {
        "chains": [{"chain_id": "A", "length": 1}],
        "composition_id": "forbidden-old-field",
    }
    save(
        client,
        [node("source", "author", source), node("edit", "author", {})],
        [edge("source", "protein_prompt", "edit", "prompt_source")],
    )
    response = preview(client, {})
    http, project = client
    draft = http.get(f"/api/v2/projects/{project}/workflow/draft").json()
    committed = http.post(
        f"/api/v2/projects/{project}/workflow:commit",
        json={"workflow": draft["workflow"]},
    )
    assert committed.status_code == 422
    assert response.status_code == 400, response.text
    validate_response("preview_prompt_authoring", 400, response.json())
    error = response.json()["error"]
    assert error["code"] == "malformed_request"
    assert error["details"]["field_path"] == [
        "nodes",
        "source",
        "node_parameters",
        "document",
        "composition_id",
    ]


def preview_and_save_workspace(
    client: tuple[TestClient, str], document: dict[str, Any]
) -> dict[str, Any]:
    from protein_workbench_public.protocol import validate_schema

    http, project = client
    response = preview(client, document)
    assert response.status_code == 200, response.text
    result = response.json()
    validate_schema("#/$defs/PromptAuthoringPreview", result)
    assert result["diagnostics"] == []
    workspace = http.get(f"/api/v2/projects/{project}/workspace").json()
    applied = http.put(
        f"/api/v2/projects/{project}/workspace",
        json={
            "workflow": workflow_with_prompt_document(workspace["draft"]["workflow"], "edit", result["normalized_document"]),
            "expected_draft_revision": workspace["draft"]["draft_revision"],
        },
    )
    assert applied.status_code == 200, applied.text
    opened = http.post(
        f"/api/v2/projects/{project}/prompt-authoring:open", json={"node_id": "edit"}
    )
    assert opened.status_code == 200, opened.text
    validate_schema("#/$defs/PromptAuthoringSnapshot", opened.json())
    assert opened.json()["document"] == result["normalized_document"]
    return result


@pytest.mark.parametrize(
    "chains,before,after,expected",
    [
        ((2,), ("A:1", "A:x", "A:2"), ("A:x", "A:1", "A:2"), ("A:x", "A:1", "A:2")),
        (
            (3, 2),
            ("A:1", "A:2", "A:3", "B:1", "B:2"),
            ("A:2", "B:2"),
            ("A:1", "A:2", "A:3", "B:1", "B:2"),
        ),
        ((2, 1), ("A:1", "A:2", "B:1"), ("B:1",), ("B:1", "A:1", "A:2")),
        (
            (3,),
            ("A:1", "A:2", "A:3"),
            ("A:2", "A:x", "A:3"),
            ("A:1", "A:2", "A:x", "A:3"),
        ),
    ],
    ids=(
        "move-insertion",
        "delete-with-successors",
        "delete-entire-chain",
        "delete-and-insert",
    ),
)
def test_projection_axis_obeys_candidate_order(
    client: tuple[TestClient, str],
    chains: tuple[int, ...],
    before: tuple[str, ...],
    after: tuple[str, ...],
    expected: tuple[str, ...],
) -> None:
    declarations = [
        {"chain_id": chain_id, "length": length}
        for chain_id, length in zip(("A", "B"), chains)
    ]
    source_ids = {
        f"{chain['chain_id']}:{index}"
        for chain in declarations
        for index in range(1, chain["length"] + 1)
    }

    def document(ids: tuple[str, ...]) -> dict[str, Any]:
        return {
            "chains": declarations,
            "target_residues": [
                {
                    "residue_id": residue_id,
                    "origin": "source" if residue_id in source_ids else "inserted",
                }
                for residue_id in ids
            ],
        }

    save(client, [node("edit", "author", document(before))], [])
    result = preview_and_save_workspace(client, document(after))
    axis = tuple(residue["residue_id"] for residue in result["residues"])
    assert axis == expected
    assert len(axis) == len(set(before) | set(after))
    assert set(axis) == set(before) | set(after)
    assert (
        tuple(
            residue["residue_id"]
            for residue in result["residues"]
            if residue["state"] != "pending-delete"
        )
        == after
    )


def test_order_change_and_apply_preserve_identity(
    client: tuple[TestClient, str]
) -> None:
    source = [{"residue_id": f"A:{i}", "origin": "source"} for i in (1, 2)]
    inserted = {"residue_id": "A:inserted.x", "origin": "inserted"}
    base = {
        "chains": [{"chain_id": "A", "length": 2}],
        "target_residues": [source[0], inserted, source[1]],
    }
    changed = {**base, "target_residues": [inserted, *source]}
    save(client, [node("edit", "author", base)], [])
    result = preview_and_save_workspace(client, changed)
    assert [r["residue_id"] for r in result["residues"]] == [
        "A:inserted.x",
        "A:1",
        "A:2",
    ]
    assert [c["kind"] for c in result["changes"]] == ["residue_order"]
    change = result["changes"][0]
    assert change["action"] == "replace"
    assert change["after_residue_handles"] == [
        r["residue_handle"] for r in result["residues"]
    ]
    assert set(change["before_residue_handles"]) == set(change["after_residue_handles"])
    assert run_workflow(client)["status"] == "succeeded"


def test_ordinary_deletion_does_not_report_order_change(
    client: tuple[TestClient, str]
) -> None:
    base = {"chains": [{"chain_id": "A", "length": 3}]}
    save(client, [node("edit", "author", base)], [])
    result = preview_and_save_workspace(
        client, {**base, "target_residues": [{"residue_id": "A:2", "origin": "source"}]}
    )
    assert [c["action"] for c in result["changes"]] == ["delete", "delete"]
    assert [
        r["residue_id"] for r in result["residues"] if r["state"] != "pending-delete"
    ] == ["A:2"]


@pytest.mark.parametrize("mode", ["explicit", "inherited", "merged"])
@pytest.mark.parametrize("annotation_case", ["touching", "nested"])
def test_annotation_contract_has_no_overlap_policy(
    client: tuple[TestClient, str], mode: str, annotation_case: str
) -> None:
    if annotation_case == "touching":
        length = 3
        annotations = [
            {"label": "one", "start_residue_id": "A:1", "end_residue_id": "A:2"},
            {"label": "two", "start_residue_id": "A:2", "end_residue_id": "A:3"},
        ]
        expected_labels = ["one", "two"]
    else:
        length = 4
        annotations = [
            {"label": "outer", "start_residue_id": "A:1", "end_residue_id": "A:4"},
            {"label": "another", "start_residue_id": "A:1", "end_residue_id": "A:4"},
            {"label": "inner", "start_residue_id": "A:2", "end_residue_id": "A:3"},
            {"label": "partial", "start_residue_id": "A:3", "end_residue_id": "A:4"},
        ]
        expected_labels = ["another", "outer", "inner", "partial"]
    base = {"chains": [{"chain_id": "A", "length": length}]}
    if mode == "explicit" and annotation_case == "nested":
        save(client, [node("edit", "author", base)], [])
        doc = {**base, "function_annotations": annotations}
    else:
        if mode == "merged":
            doc = {
                **base,
                "source_merges": [
                    {
                        "source_index": 0,
                        "correspondence": [
                            {
                                "disposition": "match",
                                "source_residue_id": f"A:{i}",
                                "target_residue_id": f"A:{i}",
                            }
                            for i in range(1, length + 1)
                        ],
                        "track_adoptions": [],
                        "adopt_annotations": annotations,
                        "remove_annotations": [],
                    }
                ],
            }
        else:
            doc = {"function_annotations": annotations} if mode == "explicit" else {}
        save(
            client,
            [
                node("source", "author", {**base, "function_annotations": annotations}),
                node("edit", "author", base if mode == "merged" else {}),
            ],
            [
                edge(
                    "source",
                    "protein_prompt",
                    "edit",
                    "merge_sources" if mode == "merged" else "prompt_source",
                )
            ],
        )
    result = preview_and_save_workspace(client, doc)
    assert len(result["function_annotations"]) == len(annotations)
    assert [
        a["label"]
        for a in result["function_annotations"]
        if a["state"] != "pending-delete"
    ] == expected_labels
    assert run_workflow(client)["status"] == "succeeded"


def test_duplicate_annotation_is_rejected_without_deduplication(
    client: tuple[TestClient, str]
) -> None:
    base = {"chains": [{"chain_id": "A", "length": 2}]}
    annotation = {"label": "site", "start_residue_id": "A:1", "end_residue_id": "A:2"}
    save(client, [node("edit", "author", base)], [])
    document = {**base, "function_annotations": [annotation, annotation]}
    response = preview(client, document)
    assert response.status_code == 200
    assert response.json()["diagnostics"]
    assert response.json()["normalized_document"]["function_annotations"] == [
        annotation,
        annotation,
    ]

def test_deleted_overlap_policy_is_not_admitted(client: tuple[TestClient, str]) -> None:
    base = {"chains": [{"chain_id": "A", "length": 1}]}
    save(client, [node("edit", "author", base)], [])
    response = preview(client, {**base, "overlap_policy": "allow"})
    assert response.status_code == 400
    assert response.json()["error"]["details"]["field_path"] == ["document"]
    assert "overlap_policy" in response.json()["error"]["message"]


@pytest.mark.parametrize(
    "chain_length,operations",
    [
        (3, [{"kind": "insert", "seed": 42, "count": 1}]),
        (
            2,
            [
                {"kind": "insert", "seed": 5, "count": 1},
                {"kind": "insert", "seed": 5, "count": 1},
            ],
        ),
    ],
    ids=("single-insertion", "same-seed-successive-insertions"),
)
def test_open_random_trace_matches_preview(
    client: tuple[TestClient, str], chain_length: int, operations: list[dict[str, Any]]
) -> None:
    base = {
        "chains": [{"chain_id": "A", "length": chain_length}],
        "random_operations": operations,
    }
    save(client, [node("edit", "author", base)], [])
    http, project = client
    opened_response = http.post(
        f"/api/v2/projects/{project}/prompt-authoring:open", json={"node_id": "edit"}
    )
    assert opened_response.status_code == 200, opened_response.text
    opened = opened_response.json()
    first_response = preview(client, base)
    assert first_response.status_code == 200, first_response.text
    first = first_response.json()
    assert first["diagnostics"] == []
    repeated_response = preview(client, base)
    assert repeated_response.status_code == 200, repeated_response.text
    repeated = repeated_response.json()
    assert (
        opened["random_selections"]
        == first["random_selections"]
        == repeated["random_selections"]
    )
    selections = first["random_selections"]
    assert tuple(item["operation_index"] for item in selections) == tuple(
        range(len(operations))
    )
    assert all(item["kind"] == "insert" for item in selections)
    assert all(len(item["realized_residue_handles"]) == 1 for item in selections)
    handles = [item["realized_residue_handles"][0] for item in selections]
    assert len(set(handles)) == len(operations)
    residue_ids = {
        item["residue_handle"]: item["residue_id"] for item in first["residues"]
    }
    inserted_ids = {residue_ids[handle] for handle in handles}
    assert len(inserted_ids) == len(operations)
    ordered_ids = tuple(item["residue_id"] for item in first["residues"])
    source_ids = tuple(f"A:{index}" for index in range(1, chain_length + 1))
    assert inserted_ids == set(ordered_ids) - set(source_ids)
    assert (
        tuple(
            residue_id for residue_id in ordered_ids if residue_id not in inserted_ids
        )
        == source_ids
    )
    assert ordered_ids == tuple(item["residue_id"] for item in repeated["residues"])
    assert ordered_ids == tuple(item["residue_id"] for item in opened["residues"])
    assert ordered_ids == recipe(base).layout.residue_ids


def assert_source_rejected_without_write(
    client: tuple[TestClient, str],
    document: dict[str, Any],
    message_fragment: str,
) -> None:
    """A rejected prospective Preview leaves the whole saved workspace intact."""
    http, project = client
    before = http.get(f"/api/v2/projects/{project}/workspace")
    assert before.status_code == 200, before.text
    response = preview(client, document)
    assert response.status_code == 400, response.text
    failure = response.json()
    validate_response("preview_prompt_authoring", 400, failure)
    assert failure["error"]["code"] == "malformed_request"
    assert failure["error"]["details"]["field_path"] == ["nodes", "edit", "inputs"]
    assert message_fragment in failure["error"]["message"]
    after = http.get(f"/api/v2/projects/{project}/workspace")
    assert after.status_code == 200, after.text
    assert after.json() == before.json()


def test_prospective_prompt_graph_preview_is_read_only_and_workspace_save_is_one_revision(
    client: tuple[TestClient, str], monkeypatch: pytest.MonkeyPatch,
) -> None:
    http, project = client
    base = f"/api/v2/projects/{project}"
    workspace_before = http.get(f"{base}/workspace").json()
    before = workspace_before["draft"]
    candidate = before["workflow"]
    candidate["nodes"].extend([
        node("prospective-source", "author", {"chains": [{"chain_id": "A", "length": 2}]}),
        node("prospective-edit", "author", {}),
    ])
    candidate["edges"].append(edge("prospective-source", "protein_prompt", "prospective-edit", "prompt_source"))
    opened = http.post(f"{base}/prompt-authoring:open", json={"node_id": "prospective-edit", "workflow": candidate})
    assert opened.status_code == 200, opened.text
    assert len(opened.json()["residues"]) == 2
    document = {"track_edits": [{"track": "sequence", "action": "replace", "residue_id": "A:1", "value": "W"}]}
    request = {"node_id": "prospective-edit", "workflow": candidate, "document": document}
    previewed = http.post(f"{base}/prompt-authoring:preview", json=request)
    assert previewed.status_code == 200, previewed.text
    preview = previewed.json()
    assert preview["diagnostics"] == []
    untouched = http.get(f"{base}/workflow/draft").json()
    assert untouched["draft_revision"] == before["draft_revision"]
    assert all(item["node_id"] != "prospective-edit" for item in untouched["workflow"]["nodes"])
    from modules.prompt_authoring.authoring import PromptAuthoringService

    def reject_repeat_preview(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("confirmed workspace edits must not evaluate Prompt again")

    monkeypatch.setattr(PromptAuthoringService, "preview", reject_repeat_preview)
    applied = http.put(f"{base}/workspace", json={
        "workflow": workflow_with_prompt_document(request["workflow"], request["node_id"], previewed.json()["normalized_document"]),
        "expected_draft_revision": draft_revision((http, project)),
        "ui_state": {"positions": {request["node_id"]: {"x": 120, "y": 80}}},
    })
    assert applied.status_code == 200, applied.text
    assert applied.json()["workspace_revision"] == workspace_before["workspace_revision"] + 1
    assert applied.json()["ui_state"] == {"positions": {"prospective-edit": {"x": 120, "y": 80}}}
    draft = applied.json()["draft"]
    assert draft["draft_revision"] == before["draft_revision"] + 1
    saved = next(item for item in draft["workflow"]["nodes"] if item["node_id"] == "prospective-edit")
    assert saved["node_parameters"]["document"] == document
    assert edge("prospective-source", "protein_prompt", "prospective-edit", "prompt_source") in draft["workflow"]["edges"]


def test_prompt_save_rejects_newer_draft(client: tuple[TestClient, str]) -> None:
    http, project = client
    base = f"/api/v2/projects/{project}"
    save(client, [node("edit", "author", {"chains": [{"chain_id": "A", "length": 2}]})], [])
    before = http.get(f"{base}/workflow/draft").json()
    candidate = before["workflow"]
    request = {"node_id": "edit", "workflow": candidate, "document": {"chains": [{"chain_id": "A", "length": 3}]}}
    previewed = http.post(f"{base}/prompt-authoring:preview", json=request)
    assert previewed.status_code == 200, previewed.text
    saved = http.put(f"{base}/workspace", json={"workflow": candidate})
    assert saved.status_code == 200, saved.text
    checkpoint = http.get(f"{base}/workflow/draft").json()
    applied = http.put(f"{base}/workspace", json={
        "workflow": workflow_with_prompt_document(request["workflow"], request["node_id"], previewed.json()["normalized_document"]),
        "expected_draft_revision": before["draft_revision"],
        "ui_state": {"positions": {request["node_id"]: {"x": 120, "y": 80}}},
    })
    assert applied.status_code == 400, applied.text
    assert "Workflow changed while the editor was open" in applied.text
    assert http.get(f"{base}/workflow/draft").json() == checkpoint


def test_prospective_prompt_can_create_first_draft_atomically(client: tuple[TestClient, str]) -> None:
    http, _ = client
    created = http.post("/api/v2/projects", json={"name": "First prospective Prompt"})
    assert created.status_code == 201, created.text
    project = created.json()["id"]
    base = f"/api/v2/projects/{project}"
    document = {"chains": [{"chain_id": "A", "length": 2}]}
    workflow = {"schema_version": "2.1.0", "workflow_id": project, "nodes": [node("edit", "author", document)], "edges": [], "observation_selectors": [], "selection_objectives": []}
    request = {"node_id": "edit", "workflow": workflow, "document": document}
    previewed = http.post(f"{base}/prompt-authoring:preview", json=request)
    assert previewed.status_code == 200, previewed.text
    assert http.get(f"{base}/workflow/draft").status_code == 404
    applied = http.put(f"{base}/workspace", json={
        "workflow": workflow_with_prompt_document(request["workflow"], request["node_id"], previewed.json()["normalized_document"]),
        "expected_draft_revision": draft_revision((http, project)),
        "ui_state": {"positions": {request["node_id"]: {"x": 120, "y": 80}}},
    })
    assert applied.status_code == 200, applied.text
    assert applied.json()["draft"]["draft_revision"] == 1


def test_prompt_version_first_edit_forks_once_and_keeps_return_workspace(client: tuple[TestClient, str]) -> None:
    http, project = client
    base = f"/api/v2/projects/{project}"
    save(client, [node("edit", "author", {"chains": [{"chain_id": "A", "length": 2}]})], [])
    named = http.post(f"{base}/versions", json={"name": "Old Prompt"})
    assert named.status_code == 201, named.text
    save(client, [node("edit", "author", {"chains": [{"chain_id": "A", "length": 3}]})], [])
    http.put(f"{base}/workspace", json={"ui_state": {"zoom": 1.25}})
    before = http.get(f"{base}/workspace").json()
    viewed = http.get(f"{base}/versions/{named.json()['version_id']}").json()
    candidate = viewed["workspace"]["draft"]["workflow"]
    context = {"version_id": named.json()["version_id"], "return_workspace_revision": before["workspace_revision"], "ui_state": {"zoom": 2}}
    document = {"chains": [{"chain_id": "A", "length": 4}]}
    request = {"node_id": "edit", "workflow": candidate, "document": document, "version_context": {"version_id": context["version_id"]}}
    previewed = http.post(f"{base}/prompt-authoring:preview", json=request)
    assert previewed.status_code == 200, previewed.text
    assert http.get(f"{base}/workspace").json() == before
    assert next(item for item in previewed.json()["residues"] if item["residue_id"] == "A:3")["state"] == "inserted"
    applied = http.post(f"{base}/versions/{context['version_id']}:fork", json={
        "workflow": workflow_with_prompt_document(candidate, "edit", previewed.json()["normalized_document"]),
        "ui_state": context["ui_state"],
        "return_workspace_revision": context["return_workspace_revision"],
    })
    assert applied.status_code == 200, applied.text
    after = http.get(f"{base}/workspace").json()
    assert after["workspace_revision"] == before["workspace_revision"] + 1
    assert after["ui_state"] == {"zoom": 2}
    assert after["source_version_id"] == context["version_id"]
    assert after["return_workspace_revision"] == before["workspace_revision"]
    assert after["draft"]["workflow"]["nodes"][0]["node_parameters"]["document"] == document
    restored = http.post(f"{base}/workspace:return", json={"workspace_revision": before["workspace_revision"]})
    assert restored.status_code == 200, restored.text
    assert restored.json()["draft"] == before["draft"]
    assert restored.json()["ui_state"] == before["ui_state"]


def test_esm3_compatibility_projection_does_not_reject_valid_multichain_prompt(client: tuple[TestClient, str]) -> None:
    http, project = client
    document = {"chains": [{"chain_id": "A", "length": 1}, {"chain_id": "B", "length": 1}]}
    save(client, [node("edit", "author", document)], [])
    result = preview_and_save_workspace(client, document)
    assert result["diagnostics"] == []
    assert result["esm3_conditioning"]["status"] == "unsupported"
    opened = http.post(f"/api/v2/projects/{project}/prompt-authoring:open", json={"node_id": "edit"})
    assert opened.status_code == 200, opened.text
    validate_response("open_prompt_authoring", 200, opened.json())
    assert opened.json()["esm3_conditioning"]["status"] == "unsupported"


def test_merge_target_projection_preserves_each_scientific_stage(client: tuple[TestClient, str]) -> None:
    base_document = {"chains": [{"chain_id": "A", "length": 1}], "track_edits": [{"track": "sequence", "action": "replace", "residue_id": "A:1", "value": "A"}]}
    source_document = {"chains": [{"chain_id": "A", "length": 1}], "track_edits": [{"track": "sequence", "action": "replace", "residue_id": "A:1", "value": "G"}]}
    save(client, [node("base", "author", base_document), node("incoming", "author", source_document), node("edit", "author", {})], [edge("base", "protein_prompt", "edit", "prompt_source"), edge("incoming", "protein_prompt", "edit", "merge_sources")])
    document = {
        "source_merges": [{"source_index": 0, "correspondence": [{"disposition": "match", "source_residue_id": "A:1", "target_residue_id": "A:1"}], "track_adoptions": [{"track": "sequence", "source_residue_ids": ["A:1"], "mask_policy": "preserve"}], "adopt_annotations": [], "remove_annotations": []}],
        "track_edits": [{"track": "sequence", "action": "replace", "residue_id": "A:1", "value": "T"}],
    }
    response = preview(client, document)
    assert response.status_code == 200, response.text
    result = response.json()
    validate_response("preview_prompt_authoring", 200, result)
    assert result["diagnostics"] == []
    assert [stage["merge_index"] for stage in result["merge_targets"]] == [0, 1]
    assert [stage["tracks"]["sequence"]["values"][0]["value"] for stage in result["merge_targets"]] == ["A", "G"]
    assert result["tracks"]["sequence"]["values"][0]["value"] == "T"


def test_prospective_graph_can_repair_an_unfinished_upstream_prompt(client: tuple[TestClient, str]) -> None:
    http, project = client
    base = f"/api/v2/projects/{project}"
    save(client, [node("upstream", "author", {}), node("edit", "author", {})], [edge("upstream", "protein_prompt", "edit", "prompt_source")])
    before = http.get(f"{base}/workflow/draft").json()
    candidate = before["workflow"]
    candidate["nodes"][0]["node_parameters"]["document"] = {"chains": [{"chain_id": "A", "length": 2}]}
    request = {"node_id": "edit", "workflow": candidate, "document": {}}
    response = http.post(f"{base}/prompt-authoring:preview", json=request)
    assert response.status_code == 200, response.text
    result = response.json()
    validate_response("preview_prompt_authoring", 200, result)
    assert result["diagnostics"] == []
    assert len(result["baseline_diagnostics"]) == 1
    assert len(result["residues"]) == 2
    assert http.get(f"{base}/workflow/draft").json()["draft_revision"] == before["draft_revision"]
    applied = http.put(f"{base}/workspace", json={
        "workflow": workflow_with_prompt_document(request["workflow"], request["node_id"], result["normalized_document"]),
        "expected_draft_revision": draft_revision((http, project)),
        "ui_state": {"positions": {request["node_id"]: {"x": 120, "y": 80}}},
    })
    assert applied.status_code == 200, applied.text


@pytest.mark.parametrize("broken_kind,diagnostic", [("missing_node", "workflow_draft_not_found"), ("missing_input", "project_input_not_found"), ("missing_port", "malformed_request"), ("invalid_parameters", "malformed_request")])
def test_prospective_graph_repairs_known_baseline_authoring_errors(client: tuple[TestClient, str], broken_kind: str, diagnostic: str) -> None:
    http, project = client
    base = f"/api/v2/projects/{project}"
    edit = node("edit", "author", {})
    upstream: list[dict[str, Any]] = []
    incoming = [edge("absent", "protein_prompt", "edit", "prompt_source")]
    if broken_kind == "missing_input":
        upstream = [{"node_id": "import", "node_type_id": "protein_io.import_sequence", "binding_id": "protein_io.import_sequence.direct", "node_parameters": {"project_input_ref": "missing-input"}, "binding_parameters": {}}]
        incoming = [edge("import", "sequence", "edit", "sequence_source")]
    elif broken_kind == "missing_port":
        upstream = [node("assemble", "assemble")]
        incoming = [edge("assemble", "protein_prompt", "edit", "prompt_source")]
    elif broken_kind == "invalid_parameters":
        edit["node_parameters"] = {"document": {"chains": [{"chain_id": "A", "length": 0}]}}
        incoming = []
    save(client, [*upstream, edit], incoming)
    before = http.get(f"{base}/workflow/draft").json()
    candidate = {**before["workflow"], "nodes": [node("edit", "author", {"chains": [{"chain_id": "A", "length": 2}]})], "edges": []}
    request = {"node_id": "edit", "workflow": candidate, "document": {"chains": [{"chain_id": "A", "length": 2}]}}
    response = http.post(f"{base}/prompt-authoring:preview", json=request)
    assert response.status_code == 200, response.text
    result = response.json()
    validate_response("preview_prompt_authoring", 200, result)
    assert result["diagnostics"] == []
    assert result["baseline_diagnostics"][0]["code"] == diagnostic
    applied = http.put(f"{base}/workspace", json={
        "workflow": workflow_with_prompt_document(request["workflow"], request["node_id"], result["normalized_document"]),
        "expected_draft_revision": draft_revision((http, project)),
        "ui_state": {"positions": {request["node_id"]: {"x": 120, "y": 80}}},
    })
    assert applied.status_code == 200, applied.text
    assert applied.json()["draft"]["draft_revision"] == before["draft_revision"] + 1
