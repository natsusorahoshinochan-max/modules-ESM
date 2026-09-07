"""Public Prompt contracts for Preview, Apply, execution and exact identity."""

from __future__ import annotations

import base64
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
from tests.support.public_request import prepare_rest_request
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
        f"/api/v2/projects/{project}/workflow/draft",
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
    response = preview(client, {})
    assert_source_rejected_without_write(
        client, {}, response, "share one ResidueLayout"
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
    result = apply_preview(client, corrected_doc)
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
    response = preview(client, document)
    assert_source_rejected_without_write(
        client, document, response, "uppercase amino-acid alphabet"
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
    response = preview(client, {})
    assert_source_rejected_without_write(
        client, {}, response, "share one ResidueLayout"
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


def test_merge_order_and_digest_control(client: tuple[TestClient, str]) -> None:
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
                "track_decisions": {
                    p: "adopt" if p == "sequence" else "preserve"
                    for p in (
                        "sequence",
                        "coordinates",
                        "secondary_structure",
                        "sasa",
                        "function_annotations",
                    )
                },
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
    first = preview(client, doc).json()
    assert first["diagnostics"] == []
    assert first["tracks"]["sequence"]["values"][0]["value"] == "A"
    save(client, nodes, list(reversed(edges)))
    second = preview(client, doc).json()
    assert second["diagnostics"] == []
    assert second["tracks"]["sequence"]["values"][0]["value"] == "G"
    assert first["preview_digest"] != second["preview_digest"]
    http, project = client
    rejected = http.post(
        f"/api/v2/projects/{project}/prompt-authoring:apply",
        json={
            "node_id": "edit",
            "document": doc,
            "preview_digest": first["preview_digest"],
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


def apply_preview(
    client: tuple[TestClient, str], document: dict[str, Any]
) -> dict[str, Any]:
    from protein_workbench_public.protocol import validate_schema

    http, project = client
    response = preview(client, document)
    assert response.status_code == 200, response.text
    result = response.json()
    validate_schema("#/$defs/PromptAuthoringPreview", result)
    assert result["diagnostics"] == []
    applied = http.post(
        f"/api/v2/projects/{project}/prompt-authoring:apply",
        json={
            "node_id": "edit",
            "document": document,
            "preview_digest": result["preview_digest"],
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
    result = apply_preview(client, document(after))
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
    result = apply_preview(client, changed)
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
    result = apply_preview(
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
                        "track_decisions": {
                            p: "adopt" if p == "function_annotations" else "preserve"
                            for p in (
                                "sequence",
                                "coordinates",
                                "secondary_structure",
                                "sasa",
                                "function_annotations",
                            )
                        },
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
    result = apply_preview(client, doc)
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
    http, project = client
    applied = http.post(
        f"/api/v2/projects/{project}/prompt-authoring:apply",
        json={
            "node_id": "edit",
            "document": document,
            "preview_digest": response.json()["preview_digest"],
        },
    )
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
    response: httpx.Response,
    message_fragment: str,
) -> None:
    """Source admission fails before Apply can mutate the saved Document."""
    http, project = client
    assert response.status_code == 400, response.text
    failure = response.json()
    validate_response("preview_prompt_authoring", 400, failure)
    assert failure["error"]["code"] == "malformed_request"
    assert failure["error"]["details"]["field_path"] == ["nodes", "edit", "inputs"]
    assert message_fragment in failure["error"]["message"]
    before = http.get(f"/api/v2/projects/{project}/workflow/draft")
    assert before.status_code == 200, before.text
    # A valid-shaped digest ensures this checks source rejection, not request admission.
    request = prepare_rest_request(
        "apply_prompt_authoring",
        {
            "project_id": project,
            "node_id": "edit",
            "document": document,
            "preview_digest": "sha256:" + "0" * 64,
        },
    )
    applied = http.request(request.method, request.route, json=request.json_body)
    assert applied.status_code == 400, applied.text
    validate_response("apply_prompt_authoring", 400, applied.json())
    for field in ("code", "message", "details", "retryable"):
        assert applied.json()["error"][field] == failure["error"][field]
    after = http.get(f"/api/v2/projects/{project}/workflow/draft")
    assert after.status_code == 200, after.text
    assert after.json() == before.json()
