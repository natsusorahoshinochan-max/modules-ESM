"""Deterministic provider-backed acceptance of the public backend contract."""

from __future__ import annotations

import copy
from collections import Counter
from typing import Any

import pytest

from tests.deterministic_acceptance.backend_client import (
    BackendAcceptanceClient,
)
from tests.deterministic_acceptance.provider_probe import ProviderCallProbe
from tests.fixtures.canonical_3gb1 import (
    PROTEINMPNN_SCORES,
    TM_VS_3GB1,
    TM_VS_ESM3,
)


PROJECT_ID = "canonical-3gb1"
RUN_SEED = 4242
EXPECTED_FINAL_PDB_HASHES = [
    "ff9656f022de5db54ff0defee387f569b36fe23612573962d5e65e81dc679471",
    "7eaef3e07bc4f4de76fbc8087938a55d1898be98717697f3706f9ae253a0a78c",
    "96282ab599e438e59493c2ee2f2c471dbc1b23c41ef73ac77a5364a6ce2f018f",
    "c43281106647c8732bdb387168db806b0b9889a74084e448ee2bc9cd8267064e",
    "f020f1878fc744c6f7cc110c990f1bffb7d78dcf88dbc8a9dacca92327b01d74",
    "4b9e7516547696f63866f7fd8fb788219e3c51996eda1dee2b6f7db954386859",
    "c81f6266d0f8cba75639e097e2f148b6ca6599169737856c54aaf9f4383b9f72",
    "c18fe603378487b56589e0ebacd6c4c04792eabca3bef667ba6752c74b97bd8c",
    "89939391e9f7a1ad660934ecdc75aa089afcdfb718d481da9554f88dd7fd027c",
    "a05f935a93e68bb9b5172b5f35e183d26f633050415ad353010c575dbe699064",
    "d3c410d2365e8d2d592fc8cba4f30902814a996b0b153557e6c11a6d94d76b95",
    "427a1531d2ecd2eca8a6196431f2685a0b0f85a13776eeba3db2e292c9bbacf8",
    "d857e90c1ae18ebf9574ad9768dfcc18bfa7e5d6f90080263b0b77695bc78837",
    "5cc56305f0b85f00bd582db2dc833c423cdb6b54a942e79dd7b7cc00376df8fd",
    "2a8755bd0d150f96037e5079475e1aede64075a3db2f044fc723d2262835b2f5",
]

pytestmark = pytest.mark.deterministic_acceptance


def _lineage_ids(
    manifest: dict[str, Any],
    node_id: str,
    output_port: str,
) -> list[str]:
    return [
        entry["candidate_id"]
        for entry in manifest["candidate_lineage"]
        if entry["node_id"] == node_id
        and entry["output_port"] == output_port
    ]


def _score_values(
    manifest: dict[str, Any],
    node_id: str,
    score_id: str,
) -> list[float]:
    return [
        score["value"]
        for score in manifest["scores"]
        if score["node_id"] == node_id
        and score["score_id"] == score_id
    ]


def test_canonical_workflow_is_auditable_through_public_protocol(
    backend_client: BackendAcceptanceClient,
    provider_call_probe: ProviderCallProbe,
) -> None:
    """REST, scoped WebSocket, manifest, and artifact APIs agree exactly."""
    accepted = backend_client.run_saved(PROJECT_ID, seed=RUN_SEED)
    assert accepted["valid"] is True
    assert accepted["errors"] == []
    run_id = accepted["run_id"]

    events = backend_client.receive_run_events(PROJECT_ID, run_id)
    assert [event["sequence"] for event in events] == list(
        range(1, len(events) + 1)
    )
    assert {
        (event["project_id"], event["run_id"])
        for event in events
    } == {(PROJECT_ID, run_id)}
    assert events[0]["type"] == "run_started"
    assert events[-1]["type"] == "run_completed"
    assert Counter(event["type"] for event in events) == Counter({
        "run_started": 1,
        "node_state": 48,
        "node_completed": 24,
        "run_completed": 1,
    })
    assert Counter(
        event["state"]
        for event in events
        if event["type"] == "node_state"
    ) == Counter({"queued": 24, "running": 24})
    assert events[0]["node_order"] == [
        "import_3gb1",
        "build_layout",
        "fixed_0",
        "compute_ss",
        "apply_edits",
        "insert_ss",
        "mask_seq",
        "mask_struct",
        "override_ss",
        "insert_seq",
        "insert_struct",
        "assemble",
        "esm3_gen",
        "fold_seq",
        "align_3gb1",
        "align_pw",
        "tm_3gb1",
        "tm_esm3",
        "merge_tm",
        "rank",
        "top3",
        "mpnn_0",
        "final_fold",
        "export_final",
    ]

    manifest = backend_client.manifest(PROJECT_ID, run_id)
    outputs = backend_client.outputs(PROJECT_ID, run_id)
    assert manifest["status"] == "completed"
    assert manifest["failures"] == []
    assert manifest["blocking_reasons"] == []
    assert manifest["effective_seeds"] == {
        "fixed_0": RUN_SEED,
        "insert_seq": RUN_SEED,
        "insert_ss": RUN_SEED,
        "insert_struct": RUN_SEED,
        "mask_seq": RUN_SEED,
        "mask_struct": RUN_SEED,
        "esm3_gen": 1603,
        "mpnn_0": RUN_SEED,
    }

    sequence_ids = _lineage_ids(
        manifest,
        "esm3_gen",
        "sequence_candidates",
    )
    sampled_structure_ids = _lineage_ids(
        manifest,
        "esm3_gen",
        "structure_candidates",
    )
    initial_fold_ids = _lineage_ids(manifest, "fold_seq", "candidates")
    selected_ids = _lineage_ids(manifest, "top3", "candidates")
    mpnn_ids = _lineage_ids(manifest, "mpnn_0", "candidates")
    final_ids = _lineage_ids(manifest, "final_fold", "candidates")
    assert sequence_ids == [
        f"seq-{run_id}-{index}" for index in range(10)
    ]
    assert sampled_structure_ids == [
        f"struct-{run_id}-{index}" for index in range(10)
    ]
    assert initial_fold_ids == [
        f"fold-{run_id}-seq-{run_id}-{index}" for index in range(10)
    ]
    assert selected_ids == initial_fold_ids[:3]
    assert mpnn_ids == [
        f"mpnn-{run_id}-{parent_index}-{sample_index}"
        for parent_index in range(3)
        for sample_index in range(5)
    ]
    assert final_ids == [
        f"fold-{run_id}-mpnn-{run_id}-{parent_index}-{sample_index}"
        for parent_index in range(3)
        for sample_index in range(5)
    ]

    lineage_by_id = {
        entry["candidate_id"]: entry
        for entry in manifest["candidate_lineage"]
    }
    assert [lineage_by_id[item]["parent_ids"] for item in sampled_structure_ids] == [
        [sequence_id] for sequence_id in sequence_ids
    ]
    assert [lineage_by_id[item]["parent_ids"] for item in initial_fold_ids] == [
        [sequence_id] for sequence_id in sequence_ids
    ]
    mpnn_parent_counts = Counter(
        lineage_by_id[item]["parent_ids"][0] for item in mpnn_ids
    )
    assert mpnn_parent_counts == Counter({
        selected_id: 5 for selected_id in selected_ids
    })
    assert [
        lineage_by_id[item]["parent_ids"] for item in final_ids
    ] == [[mpnn_id] for mpnn_id in mpnn_ids]

    assert _score_values(manifest, "tm_3gb1", "tm_vs_3gb1") == TM_VS_3GB1
    assert _score_values(manifest, "tm_esm3", "tm_vs_esm3") == TM_VS_ESM3
    assert _score_values(
        manifest,
        "mpnn_0",
        "proteinmpnn_score",
    ) == PROTEINMPNN_SCORES
    weighted = [
        score
        for score in manifest["scores"]
        if score["node_id"] == "rank"
        and score["score_id"] == "weighted_rank"
    ]
    assert len(weighted) == 10
    assert [score["value"] for score in weighted] == [
        0.30119,
        0.30119,
        0.30113,
        0.30107,
        0.30098,
        0.30083000000000004,
        0.30068,
        0.30050000000000004,
        0.30032000000000003,
        0.30008,
    ]
    assert [score["subjects"][0] for score in weighted[:3]] == selected_ids
    assert weighted[0]["details"] == {
        "metrics": [
            {"score": "tm_vs_3gb1", "weight": 0.7},
            {"score": "tm_vs_esm3", "weight": 0.3},
        ]
    }

    artifacts = outputs["artifacts"]
    assert len(artifacts) == 15
    assert [artifact["candidate_id"] for artifact in artifacts] == final_ids
    downloaded_hashes = []
    for artifact in artifacts:
        downloaded = backend_client.artifact(
            PROJECT_ID,
            run_id,
            artifact["reference"],
        )
        assert downloaded.payload.startswith(
            b"HEADER    CONTROLLED PROVIDER FIXTURE"
        )
        assert len(downloaded.payload) == artifact["size"]
        assert downloaded.sha256 == artifact["sha256"]
        downloaded_hashes.append(downloaded.sha256)
    assert downloaded_hashes == EXPECTED_FINAL_PDB_HASHES
    assert Counter(
        call["details"]["node_id"]
        for call in manifest["providers"]["calls"]
    ) == Counter({
        "compute_ss": 1,
        "esm3_gen": 20,
        "fold_seq": 10,
        "align_3gb1": 10,
        "align_pw": 10,
        "tm_3gb1": 10,
        "tm_esm3": 10,
        "mpnn_0": 3,
        "final_fold": 15,
    })
    assert len(provider_call_probe.calls()) == 49


def test_incompatible_edge_is_rejected_before_run_or_provider_work(
    backend_client: BackendAcceptanceClient,
    provider_call_probe: ProviderCallProbe,
) -> None:
    workflow = copy.deepcopy(backend_client.get_workflow(PROJECT_ID))
    secondary_structure_edge = next(
        edge
        for edge in workflow["edges"]
        if edge["target_node_id"] == "override_ss"
    )
    secondary_structure_edge["source_node_id"] = "import_3gb1"
    secondary_structure_edge["source_port"] = "structure"

    project_id = backend_client.create_project("invalid-edge")
    backend_client.save_workflow(project_id, workflow)
    before = backend_client.cache_entries(project_id)
    calls_before = provider_call_probe.calls()
    rejected = backend_client.run_saved_raw(project_id, seed=RUN_SEED)
    after = backend_client.cache_entries(project_id)
    calls_after = provider_call_probe.calls()

    assert rejected.status_code == 422
    assert "run_id" not in rejected.json()
    assert rejected.json()["valid"] is False
    assert {
        error["kind"] for error in rejected.json()["errors"]
    } >= {"port_type_mismatch"}
    assert before == after == {"project_id": project_id, "entries": []}
    assert calls_before == calls_after == []


def test_provider_failure_is_structured_and_unrelated_branch_completes(
    backend_client: BackendAcceptanceClient,
) -> None:
    project_id = backend_client.create_project("provider-failure")
    backend_client.save_workflow(
        project_id,
        {
            "nodes": [
                {
                    "node_id": "fails",
                    "module_id": "stub.echo",
                    "parameters": {"prefix": "fixture:fail"},
                },
                {
                    "node_id": "unrelated",
                    "module_id": "stub.echo",
                    "parameters": {"prefix": "fixture:unrelated"},
                },
                {
                    "node_id": "dependent",
                    "module_id": "stub.echo",
                    "parameters": {},
                },
            ],
            "edges": [{
                "source_node_id": "fails",
                "source_port": "text",
                "target_node_id": "dependent",
                "target_port": "text",
            }],
        },
    )

    accepted = backend_client.run_saved(project_id, seed=RUN_SEED)
    events = backend_client.receive_run_events(
        project_id,
        accepted["run_id"],
    )
    manifest = backend_client.manifest(project_id, accepted["run_id"])

    terminal_nodes = {
        event["node_id"]: event["type"]
        for event in events
        if event["type"] in {
            "node_completed",
            "node_failed",
            "node_blocked",
        }
    }
    assert terminal_nodes == {
        "fails": "node_failed",
        "unrelated": "node_completed",
        "dependent": "node_blocked",
    }
    failed = next(
        event for event in events if event["type"] == "node_failed"
    )
    assert failed["error"] == {
        "kind": "provider_failure",
        "message": "Node execution failed (provider_failure)",
        "module_id": "stub.echo",
        "retryable": False,
    }
    assert events[-1]["type"] == "run_failed"
    assert manifest["status"] == "failed"
    assert manifest["failures"] == [{
        "node_id": "fails",
        "kind": "provider_failure",
        "message": "Node execution failed (provider_failure)",
    }]
    assert manifest["blocking_reasons"] == [{
        "node_id": "dependent",
        "reason": {
            "kind": "upstream_terminal",
            "message": "Required upstream Node did not complete",
            "upstream_node_ids": ["fails"],
        },
    }]
    assert Counter(
        call["operation"] for call in manifest["providers"]["calls"]
    ) == Counter({"fail": 1, "unrelated": 1})
    assert "fixture-secret-must-not-leak" not in str(events)
    assert "fixture-secret-must-not-leak" not in str(manifest)


def test_cancellation_and_overlapping_same_project_run_are_isolated(
    backend_client: BackendAcceptanceClient,
) -> None:
    project_id = backend_client.create_project("cancel-and-overlap")
    backend_client.save_workflow(
        project_id,
        {
            "nodes": [{
                "node_id": "provider",
                "module_id": "stub.echo",
                "parameters": {"prefix": "fixture:block"},
            }],
            "edges": [],
        },
    )
    accepted = backend_client.run_saved(project_id, seed=RUN_SEED)
    run_id = accepted["run_id"]
    observed: dict[str, Any] = {}

    def cancel_when_running(event: dict[str, Any]) -> None:
        if (
            event["type"] == "node_state"
            and event["state"] == "running"
            and not observed
        ):
            observed["overlap"] = backend_client.run_saved_raw(
                project_id,
                seed=RUN_SEED,
            )
            observed["cancel"] = backend_client.cancel(project_id, run_id)

    events = backend_client.receive_run_events(
        project_id,
        run_id,
        on_event=cancel_when_running,
    )
    manifest = backend_client.manifest(project_id, run_id)

    assert observed["overlap"].status_code == 409
    assert observed["overlap"].json() == {
        "error": {
            "kind": "active_run_conflict",
            "message": "Project already has an active run",
            "project_id": project_id,
            "active_run_id": run_id,
        }
    }
    assert observed["cancel"].status_code == 200
    assert observed["cancel"].json() == {
        "status": "cancellation_requested",
        "project_id": project_id,
        "run_id": run_id,
    }
    assert [event["type"] for event in events[-3:]] == [
        "run_cancellation_requested",
        "node_cancelled",
        "run_cancelled",
    ]
    assert manifest["status"] == "cancelled"
    assert manifest["node_states"][-1]["node_id"] == "provider"
    assert manifest["node_states"][-1]["old_state"] == "running"
    assert manifest["node_states"][-1]["state"] == "cancelled"


def test_repeated_canonical_execution_replays_cache_in_a_fresh_run_scope(
    backend_client: BackendAcceptanceClient,
) -> None:
    first = backend_client.run_saved(PROJECT_ID, seed=RUN_SEED)
    first_events = backend_client.receive_run_events(
        PROJECT_ID,
        first["run_id"],
    )
    first_manifest = backend_client.manifest(PROJECT_ID, first["run_id"])

    replay = backend_client.run_saved(PROJECT_ID, seed=RUN_SEED)
    replay_events = backend_client.receive_run_events(
        PROJECT_ID,
        replay["run_id"],
    )
    replay_manifest = backend_client.manifest(PROJECT_ID, replay["run_id"])
    replay_outputs = backend_client.outputs(PROJECT_ID, replay["run_id"])

    assert replay["run_id"] != first["run_id"]
    assert first_events[-1]["type"] == "run_completed"
    assert replay_events[-1]["type"] == "run_completed"
    assert [event["sequence"] for event in replay_events] == list(
        range(1, len(replay_events) + 1)
    )
    assert len(first_manifest["providers"]["calls"]) == 89
    assert replay_manifest["providers"]["calls"] == []
    assert Counter(
        entry["provider"]
        for entry in first_manifest["providers"]["readiness"]
    ) == Counter({
        "biohub": 1,
        "local_open": 1,
        "controlled-proteinmpnn": 1,
        "mkdssp": 1,
        "biopython-svd": 1,
        "tmtools": 1,
    })
    assert replay_manifest["providers"]["readiness"] == (
        first_manifest["providers"]["readiness"]
    )
    assert Counter(
        entry["outcome"] for entry in first_manifest["cache"]
    ) == Counter({"miss": 24})
    assert Counter(
        entry["outcome"] for entry in replay_manifest["cache"]
    ) == Counter({"hit": 23, "miss": 1})
    assert [
        entry["node_id"]
        for entry in replay_manifest["cache"]
        if entry["outcome"] == "miss"
    ] == ["export_final"]
    assert {
        (
            entry["consumer"]["project_id"],
            entry["consumer"]["run_id"],
        )
        for entry in replay_manifest["cache"]
    } == {(PROJECT_ID, replay["run_id"])}
    replay_hashes = []
    for artifact in replay_outputs["artifacts"]:
        downloaded = backend_client.artifact(
            PROJECT_ID,
            replay["run_id"],
            artifact["reference"],
        )
        assert downloaded.sha256 == artifact["sha256"]
        replay_hashes.append(downloaded.sha256)
    assert replay_hashes == EXPECTED_FINAL_PDB_HASHES


def test_client_readiness_claims_cannot_authorize_an_unready_workflow(
    unavailable_readiness_backend_client: BackendAcceptanceClient,
) -> None:
    claimed_ready = {
        provider: {"ready": True, "status": "ready"}
        for provider in (
            "biohub",
            "local_open",
            "controlled-proteinmpnn",
            "mkdssp",
            "biopython-svd",
            "tmtools",
        )
    }

    rejected = unavailable_readiness_backend_client.run_saved_raw(
        PROJECT_ID,
        seed=RUN_SEED,
        extra_options={
            "provider_readiness": claimed_ready,
            "readiness": claimed_ready,
        },
    )

    assert rejected.status_code == 503
    error = rejected.json()["error"]
    assert error["kind"] == "required_provider_unavailable"
    rejected_run_id = rejected.json()["run_id"]
    manifest = unavailable_readiness_backend_client.manifest(
        PROJECT_ID,
        rejected_run_id,
    )
    readiness = {
        item["provider"]: item
        for item in error["readiness"]
    }
    assert readiness["local_open"]["status"] == "unavailable"
    assert readiness["biohub"]["status"] == "failed"
    assert readiness["biohub"]["details"]["reason"] == "ambiguous_readiness"
    assert readiness["controlled-proteinmpnn"]["status"] == "failed"
    assert all(
        item["source"]["kind"] == "workflow_required_boundary"
        for item in readiness.values()
    )
    assert manifest["status"] == "failed"
    assert manifest["providers"]["readiness"] == error["readiness"]
    assert manifest["providers"]["calls"] == []
    assert manifest["node_states"] == []
    assert "fixture-secret-must-not-leak" not in rejected.text
    assert "fixture-secret-must-not-leak" not in str(manifest)


def test_traversal_like_project_input_is_rejected_without_run_creation(
    backend_client: BackendAcceptanceClient,
) -> None:
    workflow = copy.deepcopy(backend_client.get_workflow(PROJECT_ID))
    imported = next(
        node
        for node in workflow["nodes"]
        if node["node_id"] == "import_3gb1"
    )
    imported["parameters"]["file_path"] = "../../outside.pdb"

    project_id = backend_client.create_project("invalid-input")
    backend_client.save_workflow(project_id, workflow)
    rejected = backend_client.run_saved_raw(project_id, seed=RUN_SEED)

    assert rejected.status_code == 422
    assert rejected.json() == {
        "error": {
            "kind": "invalid_storage_path",
            "field": "input_path",
            "message": "Invalid input_path",
        }
    }
    assert backend_client.cache_entries(project_id) == {
        "project_id": project_id,
        "entries": [],
    }


def test_fixture_backend_rejects_uncontrolled_provider_modules(
    backend_client: BackendAcceptanceClient,
    provider_call_probe: ProviderCallProbe,
) -> None:
    project_id = backend_client.create_project("uncontrolled-provider")
    backend_client.save_workflow(
        project_id,
        {
            "nodes": [
                {
                    "node_id": "import_sequence",
                    "module_id": "import.sequence",
                    "parameters": {"file_path": "inputs/sequence.fasta"},
                },
                {
                    "node_id": "simplefold",
                    "module_id": "simplefold.fold",
                    "parameters": {},
                },
            ],
            "edges": [{
                "source_node_id": "import_sequence",
                "source_port": "sequence",
                "target_node_id": "simplefold",
                "target_port": "sequence",
            }],
        },
    )

    rejected = backend_client.run_saved_raw(project_id, seed=RUN_SEED)

    assert rejected.status_code == 422
    assert rejected.json() == {
        "error": {
            "kind": "module_not_allowed",
            "message": "Workflow contains a Module disabled by this backend",
            "module_ids": ["import.sequence", "simplefold.fold"],
        }
    }
    assert provider_call_probe.calls() == []


def test_websocket_and_manifest_reads_cannot_cross_run_scope_or_origin(
    backend_client: BackendAcceptanceClient,
) -> None:
    project_a = backend_client.create_project("scope-a")
    project_b = backend_client.create_project("scope-b")
    echo_workflow = {
        "nodes": [{
            "node_id": "echo",
            "module_id": "stub.echo",
            "parameters": {},
        }],
        "edges": [],
    }
    backend_client.save_workflow(project_a, echo_workflow)
    backend_client.save_workflow(project_b, echo_workflow)
    run_a = backend_client.run_saved(project_a, seed=RUN_SEED)["run_id"]
    run_b = backend_client.run_saved(project_b, seed=RUN_SEED)["run_id"]
    backend_client.receive_run_events(project_a, run_a)
    backend_client.receive_run_events(project_b, run_b)

    assert backend_client.websocket_rejection_status(
        project_a,
        run_b,
    ) == 403
    assert backend_client.websocket_rejection_status(
        project_a,
        run_a,
        origin="https://untrusted.example",
    ) == 403
    leaked_manifest = backend_client.manifest_raw(project_a, run_b)
    assert leaked_manifest.status_code == 404
    assert leaked_manifest.json() == {
        "error": {
            "kind": "run_not_found",
            "message": "Run was not found in this project",
        }
    }
