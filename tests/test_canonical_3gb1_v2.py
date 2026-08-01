"""Exact v2 acceptance for the maintained canonical 3GB1 Workflow.

The pre-agreed seams are the shipped Workflow document, the immutable
production Catalog/compiler, and the public installed-backend protocol.
"""

from __future__ import annotations

from collections import Counter
import hashlib
import json
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
import pytest
from starlette.websockets import WebSocketDisconnect
import torch

from core import (
    build_discovered_frozen_catalog,
    compile_workflow,
    parse_workflow_document,
    relock_workflow,
)
from core.port_types import PORT_VALUE_NAMESPACE, canonical_json_bytes
from core.server import create_app
from datatypes import CandidateCollection, PairwiseCandidateMapping
from modules.proteinmpnn.adapter import LocalProteinMPNNAdapter
from scripts.fresh_remote_3gb1 import (
    CANONICAL_PROVIDER_PROMPT_CONTENT_DIGEST,
)
from tests.fixtures.canonical_3gb1_v2 import (
    ControlledESM3Client,
    ControlledFoldingClient,
    ControlledProteinMPNNProvider,
    controlled_catalog,
    controlled_environment,
)
from tests.fixtures.public_v2 import wait_for_testclient_run_terminal


PROJECT_ROOT = Path(__file__).resolve().parent.parent
WORKFLOW_PATH = (
    PROJECT_ROOT / "examples" / "v2" / "canonical-3gb1.workflow.json"
)
EXPECTED_TOP_THREE = [
    "candidate-0bc58261da5abcf20c4c9ef3f19d47398c1fe14cfa2b5384e84c5c8b9d5eb389",
    "candidate-0af4328aee79522591b146769a2a7f36ff5bf46ccecf2cb04b9ceca34a0c45ae",
    "candidate-a28632eac0a16b458780381efd977faa733bf4aec2d9fa653a8dcd9dcd9992e3",
]
EXPECTED_TOP_PARENT_INDICES = [5, 9, 8]
pytestmark = pytest.mark.deterministic_acceptance


def _workflow_payload() -> dict[str, Any]:
    return json.loads(WORKFLOW_PATH.read_text(encoding="utf-8"))


def test_canonical_seed_is_exact_locked_compilable_v2() -> None:
    catalog = build_discovered_frozen_catalog()
    workflow = parse_workflow_document(_workflow_payload())

    assert workflow.workflow_id == "canonical-3gb1"
    assert workflow.schema_version == "2.1.0"
    assert workflow.contract_lock
    assert relock_workflow(workflow, catalog) == workflow
    compiled = compile_workflow(
        workflow,
        workflow_revision=1,
        catalog=catalog,
    )
    assert compiled.receipt["accepted"] is True
    assert compiled.execution_plan.resolved_contracts == workflow.contract_lock

    nodes = {node.node_id: node for node in workflow.nodes}
    assert all(
        node.node_type_version == node.binding_version
        and not node.binding_parameters
        for node in nodes.values()
    )
    assert {
        node.node_id: node.node_type_version
        for node in nodes.values()
        if node.node_type_version != "2.1.0"
    } == {
        "align-fixed": "2.2.0",
        "score-fixed": "2.2.0",
        "align-paired": "2.2.0",
        "score-paired": "2.2.0",
        "import-3gb1": "3.0.0",
        "build-prompt": "3.0.0",
        "fixed-positions": "3.0.0",
        "generate-paired": "3.0.0",
        "fold-sequences": "3.0.0",
        "design-children": "4.0.0",
        "fold-final": "3.0.0",
        "export-final": "3.0.0",
    }
    assert nodes["mask-sequence"].node_parameters["effective_seed"] == 1603
    assert nodes["mask-structure"].node_parameters["effective_seed"] == 1603
    assert nodes["insert-masked"].node_parameters["effective_seed"] == 1603
    assert nodes["generate-paired"].node_parameters == {
        "effective_seed": 1603,
        "num_samples": 10,
    }
    assert nodes["fold-sequences"].node_parameters == {
        "effective_seed": 1603,
        "num_samples": 1,
    }
    assert nodes["rank-candidates"].node_parameters == {
        "objective_ids": ("fixed-3gb1", "paired-esm3"),
        "tie_policy": "candidate_id_ascending",
    }
    assert nodes["take-top-three"].node_parameters == {"k": 3}
    assert nodes["design-children"].node_parameters == {
        "effective_seed": 1603,
        "num_sequences": 5,
        "temperature": 0.1,
        "backbone_noise": 0,
    }
    assert nodes["fold-final"].node_parameters == {
        "effective_seed": 1603,
        "num_samples": 1,
    }

    objectives = {
        objective.objective_id: objective
        for objective in workflow.selection_objectives
    }
    assert set(objectives) == {"fixed-3gb1", "paired-esm3"}
    assert objectives["fixed-3gb1"].context_selector.pairing_mode == (
        "fixed_reference"
    )
    assert objectives["paired-esm3"].context_selector.pairing_mode == (
        "per_subject_counterpart"
    )
    assert objectives["fixed-3gb1"].source_partition != (
        objectives["paired-esm3"].source_partition
    )
    assert {
        objective.weight for objective in objectives.values()
    } == {0.7, 0.3}


def test_invalid_canonical_workflow_is_rejected_before_provider_calls(
    tmp_path: Path,
    monkeypatch,
) -> None:
    for name in ("PROJECT", "CACHE", "OUTPUT", "RUN"):
        root = tmp_path / name.lower()
        root.mkdir()
        monkeypatch.setenv(f"PROTEIN_WORKBENCH_{name}_ROOT", str(root))
    esm3 = ControlledESM3Client()
    folding = ControlledFoldingClient()
    workflow = _workflow_payload()
    generate = next(
        node
        for node in workflow["nodes"]
        if node["node_id"] == "generate-paired"
    )
    generate["binding_id"] = "esm3.generate_paired.biohub_open"
    app = create_app(
        frozen_catalog_override=controlled_catalog(),
        v2_environment_configuration=controlled_environment(
            esm3,
            folding,
        ),
    )

    with TestClient(app) as client:
        snapshot = client.get(
            "/api/v2/projects/canonical-3gb1/workflow"
        ).json()
        rejected = client.post(
            "/api/v2/projects/canonical-3gb1/workflow:compile",
            json={
                "workflow_revision": snapshot["workflow_revision"],
                "workflow": workflow,
            },
        )

    assert rejected.status_code == 422
    assert rejected.json()["error"]["code"] == "compile_rejected"
    assert not esm3.sequence_prompts
    assert not esm3.structure_prompts
    assert not folding.calls


def _decoded_output(
    catalog: Any,
    projection: dict[str, Any],
    node_id: str,
    output_port: str,
) -> Any:
    decoded = _decoded_outputs(catalog, projection, node_id, output_port)
    assert len(decoded) == 1
    return decoded[0]


def _decoded_outputs(
    catalog: Any,
    projection: dict[str, Any],
    node_id: str,
    output_port: str,
) -> tuple[Any, ...]:
    output = next(
        item
        for item in projection["outputs"]
        if item["node_id"] == node_id
        and item["output_port"] == output_port
    )
    reference = output["port_type"]
    codec = catalog.require_port_type(
        reference["contract_id"],
        reference["contract_version"],
    )
    return tuple(
        codec.decode(
            canonical_json_bytes({
                "schema_namespace": PORT_VALUE_NAMESPACE,
                "port_type_id": reference["contract_id"],
                "port_type_version": reference["contract_version"],
                "value": value,
            })
        )
        for value in output["values"]
    )


def _replay_events(
    client: TestClient,
    run_id: str,
) -> tuple[dict[str, Any], ...]:
    with client.websocket_connect(
        f"/api/v2/projects/canonical-3gb1/runs/{run_id}/events"
    ) as websocket:
        messages: list[dict[str, Any]] = []
        try:
            while True:
                messages.append(websocket.receive_json())
        except WebSocketDisconnect as closed:
            assert closed.code == 1000
    return tuple(
        message
        for message in messages
        if message["event"]["type"] not in {
            "replay_started",
            "replay_complete",
        }
    )


def test_canonical_v2_public_protocol_reproduces_scientific_intent(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """One provider-backed run proves the complete v2 canonical journey."""
    for name in ("PROJECT", "CACHE", "OUTPUT", "RUN"):
        root = tmp_path / name.lower()
        root.mkdir()
        monkeypatch.setenv(f"PROTEIN_WORKBENCH_{name}_ROOT", str(root))
    esm3 = ControlledESM3Client()
    folding = ControlledFoldingClient()
    proteinmpnn = ControlledProteinMPNNProvider()
    monkeypatch.setattr(
        "modules.proteinmpnn.package.LocalProteinMPNNAdapter",
        lambda **kwargs: LocalProteinMPNNAdapter(
            environment=kwargs["environment"],
            resources=kwargs["resources"],
            provider_factory=(
                lambda _environment, _directory: proteinmpnn
            ),
        ),
    )
    catalog = controlled_catalog()
    assert catalog.contract_digest == (
        build_discovered_frozen_catalog().contract_digest
    )
    controlled_configuration = controlled_environment(
        esm3,
        folding,
    )
    assert controlled_configuration[
        ("proteinmpnn.design.local", "4.0.0")
    ]["safe_fingerprint"] == "controlled-proteinmpnn-canonical-v2"
    app = create_app(
        frozen_catalog_override=catalog,
        v2_environment_configuration=controlled_configuration,
    )

    with TestClient(app) as client:
        catalog_snapshot = client.get("/api/v2/catalog")
        assert catalog_snapshot.status_code == 200
        assert catalog_snapshot.json()["catalog_contract_digest"] == (
            catalog.contract_digest
        )
        snapshot = client.get(
            "/api/v2/projects/canonical-3gb1/workflow"
        )
        assert snapshot.status_code == 200
        assert snapshot.json()["workflow"] == _workflow_payload()
        compiled = client.post(
            "/api/v2/projects/canonical-3gb1/workflow:compile",
            json={
                "workflow_revision": snapshot.json()["workflow_revision"],
                "workflow": snapshot.json()["workflow"],
            },
        )
        assert compiled.status_code == 200
        compile_receipt = compiled.json()
        assert compile_receipt["accepted"] is True
        assert compile_receipt["contract_lock_digest"] == (
            parse_workflow_document(
                snapshot.json()["workflow"]
            ).contract_lock_digest
        )

        def run(request_id: str) -> tuple[dict[str, Any], tuple[dict, ...]]:
            started = client.post(
                "/api/v2/projects/canonical-3gb1/runs",
                json={
                    "workflow_revision": snapshot.json()[
                        "workflow_revision"
                    ],
                    "compile_id": compile_receipt["compile_id"],
                    "client_request_id": request_id,
                },
            )
            assert started.status_code == 202
            run_id = started.json()["run_id"]
            projection = wait_for_testclient_run_terminal(
                client,
                "canonical-3gb1",
                run_id,
                timeout_seconds=60,
            )
            return projection, _replay_events(client, run_id)

        first, first_events = run("canonical-v2-first")

        assert first["status"] == "succeeded", first["node_dispositions"]
        assert len(first["node_dispositions"]) == 21
        assert {
            disposition["node_id"]
            for disposition in first["node_dispositions"]
        } == {
            node["node_id"] for node in _workflow_payload()["nodes"]
        }
        assert all(
            disposition["outcome"] == "succeeded"
            for disposition in first["node_dispositions"]
        )

        sequence_candidates = _decoded_output(
            catalog,
            first,
            "generate-paired",
            "sequence_candidates",
        )
        structure_candidates = _decoded_output(
            catalog,
            first,
            "generate-paired",
            "structure_candidates",
        )
        counterpart_pairs = _decoded_output(
            catalog,
            first,
            "generate-paired",
            "counterpart_pairs",
        )
        assert type(sequence_candidates) is CandidateCollection
        assert type(structure_candidates) is CandidateCollection
        assert type(counterpart_pairs) is PairwiseCandidateMapping
        assert len(sequence_candidates.items) == 10
        assert len(structure_candidates.items) == 10
        assert len(counterpart_pairs.entries) == 10
        assert [
            item.parent_ids for item in structure_candidates.items
        ] == [
            (sequence.candidate_id,)
            for sequence in sequence_candidates.items
        ]
        assert [
            (
                pair.subject_candidate_id,
                pair.reference_candidate_id,
            )
            for pair in counterpart_pairs.entries
        ] == [
            (sequence.candidate_id, structure.candidate_id)
            for sequence, structure in zip(
                sequence_candidates.items,
                structure_candidates.items,
                strict=True,
            )
        ]

        first_prompt = esm3.sequence_prompts[0]
        prompt_output = next(
            item
            for item in first["outputs"]
            if item["node_id"] == "override-secondary-structure"
            and item["output_port"] == "protein_prompt"
        )
        assert prompt_output["content_digest"] == (
            CANONICAL_PROVIDER_PROMPT_CONTENT_DIGEST
        )
        assert len(esm3.sequence_prompts) == len(esm3.structure_prompts) == 10
        assert len(first_prompt.sequence) == 71
        assert first_prompt.sequence.count("_") == 35
        assert first_prompt.secondary_structure == (
            "E" * 19
            + "_" * 3
            + "H" * 8
            + "_" * 4
            + "E" * 22
            + "_" * 15
        )
        assert tuple(first_prompt.coordinates.shape) == (71, 37, 3)
        visible_backbones = torch.isfinite(
            first_prompt.coordinates[:, (0, 1, 2), :]
        ).all(dim=(1, 2))
        assert int(visible_backbones.sum().item()) == 46

        initial_folds = _decoded_output(
            catalog,
            first,
            "fold-sequences",
            "structure_candidates",
        )
        rebound = _decoded_output(
            catalog,
            first,
            "rebind-counterparts",
            "pairing",
        )
        canonical_references = _decoded_output(
            catalog,
            first,
            "import-3gb1",
            "structure_candidates",
        )
        fixed_alignments = _decoded_outputs(
            catalog,
            first,
            "align-fixed",
            "alignments",
        )
        paired_alignments = _decoded_outputs(
            catalog,
            first,
            "align-paired",
            "alignments",
        )
        assert len(initial_folds.items) == len(rebound.entries) == 10
        assert len({
            pair.reference_candidate_id
            for pair in rebound.entries
        }) == 10
        assert {
            pair.subject_candidate_id for pair in rebound.entries
        } == {
            candidate.candidate_id for candidate in initial_folds.items
        }
        assert {
            pair.reference_candidate_id for pair in rebound.entries
        } == {
            candidate.candidate_id for candidate in structure_candidates.items
        }
        assert {
            alignment.reference.candidate_id
            for alignment in fixed_alignments
        } == {canonical_references.items[0].candidate_id}
        assert {
            (
                alignment.subject.candidate_id,
                alignment.reference.candidate_id,
            )
            for alignment in paired_alignments
        } == {
            (
                pair.subject_candidate_id,
                pair.reference_candidate_id,
            )
            for pair in rebound.entries
        }
        assert {
            alignment.reference.candidate_id
            for alignment in fixed_alignments
        }.isdisjoint({
            alignment.reference.candidate_id
            for alignment in paired_alignments
        })

        ranked = _decoded_output(
            catalog,
            first,
            "rank-candidates",
            "candidates",
        )
        selected = _decoded_output(
            catalog,
            first,
            "take-top-three",
            "candidates",
        )
        assert len(ranked.items) == 10
        assert selected.items == ranked.items[:3]
        assert [
            candidate.candidate_id for candidate in selected.items
        ] == EXPECTED_TOP_THREE
        assert [
            candidate.metadata["parent_index"] for candidate in selected.items
        ] == EXPECTED_TOP_PARENT_INDICES
        selection = first["selection_results"][0]
        assert selection["selection_node_id"] == "rank-candidates"
        assert [
            (
                objective["objective_id"],
                objective["source_partition"],
                objective["utility_transform"]["contract_id"],
                objective["declared_weight"],
                objective["effective_weight"],
            )
            for objective in selection["objectives"]
        ] == [
            (
                "fixed-3gb1",
                "structure_comparison.tm_score.fixed_reference",
                (
                    "structure_comparison.tm_score."
                    "fixed_reference.identity"
                ),
                0.7,
                0.7,
            ),
            (
                "paired-esm3",
                "structure_comparison.tm_score.per_subject_counterpart",
                (
                    "structure_comparison.tm_score."
                    "per_subject_counterpart.identity"
                ),
                0.3,
                0.3,
            ),
        ]

        children = _decoded_output(
            catalog,
            first,
            "design-children",
            "sequence_candidates",
        )
        assert len(children.items) == 15
        assert Counter(
            child.parent_ids[0] for child in children.items
        ) == Counter({
            parent.candidate_id: 5 for parent in selected.items
        })
        assert len(proteinmpnn.requests) == 3
        assert all(
            request.num_sequences == 5
            and request.temperature == 0.1
            and request.backbone_noise == 0
            for request in proteinmpnn.requests
        )
        assert len({request.seed for request in proteinmpnn.requests}) == 3
        call_seed_by_parent = {
            parent.candidate_id: request.seed
            for parent, request in zip(
                selected.items,
                proteinmpnn.requests,
                strict=True,
            )
        }
        assert all(
            child.metadata["effective_seed"] == 1603
            and child.metadata["effective_call_seed"]
            == call_seed_by_parent[child.parent_ids[0]]
            for child in children.items
        )

        final_folds = _decoded_output(
            catalog,
            first,
            "fold-final",
            "structure_candidates",
        )
        assert len(final_folds.items) == 15
        assert [
            folded.parent_ids for folded in final_folds.items
        ] == [(child.candidate_id,) for child in children.items]
        assert len(first["artifact_index"]) == 15
        assert [
            artifact["candidate_id"]
            for artifact in first["artifact_index"]
        ] == [
            candidate.candidate_id for candidate in final_folds.items
        ]
        downloaded_hashes: list[str] = []
        for artifact in first["artifact_index"]:
            downloaded = client.get(
                "/api/v2/projects/canonical-3gb1/runs/"
                f"{first['run_id']}/artifacts/"
                f"{artifact['artifact_reference']}"
            )
            assert downloaded.status_code == 200
            assert downloaded.headers["Digest"] == (
                artifact["content_digest"]
            )
            assert len(downloaded.content) == artifact["size"]
            assert (
                "sha256:" + hashlib.sha256(downloaded.content).hexdigest()
                == artifact["content_digest"]
            )
            downloaded_hashes.append(artifact["content_digest"])
        assert len(set(downloaded_hashes)) == 15

        event_payloads = [message["event"] for message in first_events]
        assert [message["sequence"] for message in first_events] == sorted(
            message["sequence"] for message in first_events
        )
        assert event_payloads[-1] == {
            "type": "run_terminal",
            "status": "succeeded",
        }
        assert sum(
            event["type"] == "node_disposition"
            for event in event_payloads
        ) == 21
        attempt_starts = Counter(
            event["operation_attempt_id"]
            for event in event_payloads
            if event["type"] == "operation_attempt_started"
        )
        attempt_terminals = Counter(
            event["operation_attempt_id"]
            for event in event_payloads
            if event["type"] == "operation_attempt_terminal"
        )
        invocation_terminals = Counter(
            event["invocation_id"]
            for event in event_payloads
            if event["type"] == "engine_invocation_terminal"
        )
        invocation_starts = Counter(
            event["invocation_id"]
            for event in event_payloads
            if event["type"] == "engine_invocation_started"
        )
        assert attempt_starts == attempt_terminals
        assert invocation_starts == invocation_terminals
        assert set(attempt_starts.values()) == {1}
        assert set(invocation_starts.values()) == {1}
        readiness_sequences = [
            message["sequence"]
            for message in first_events
            if message["event"]["type"] == "readiness_attested"
        ]
        attempt_sequences = [
            message["sequence"]
            for message in first_events
            if message["event"]["type"] == "node_attempt_started"
        ]
        assert readiness_sequences
        assert max(readiness_sequences) < min(attempt_sequences)
        proteinmpnn_readiness = next(
            message["event"]
            for message in first_events
            if message["event"]["type"] == "readiness_attested"
            and message["event"]["binding"]["contract_id"]
            == "proteinmpnn.design.local"
        )
        assert proteinmpnn_readiness["binding"]["contract_version"] == (
            "4.0.0"
        )

        esm_calls_before = len(esm3.sequence_prompts)
        fold_calls_before = len(folding.calls)
        mpnn_calls_before = len(proteinmpnn.requests)
        replay, replay_events = run("canonical-v2-replay")
        assert replay["status"] == "succeeded"
        assert replay["run_id"] != first["run_id"]

        def stable_outputs(projection: dict[str, Any]) -> list[tuple]:
            return [
                (
                    output["node_id"],
                    output["output_port"],
                    output["port_type"],
                    output["content_digest"],
                    output["values"],
                )
                for output in projection["outputs"]
            ]

        assert stable_outputs(replay) == stable_outputs(first)
        assert replay["selection_results"] == first["selection_results"]
        assert [
            artifact["content_digest"]
            for artifact in replay["artifact_index"]
        ] == downloaded_hashes
        assert len(esm3.sequence_prompts) == esm_calls_before + 10
        assert len(folding.calls) == fold_calls_before + 25
        assert len(proteinmpnn.requests) == mpnn_calls_before
        replayed_nodes = {
            disposition["node_id"]
            for disposition in replay["node_dispositions"]
            if disposition.get("resolution") == "cache_replayed"
        }
        replay_attempt_nodes = {
            message["event"]["node_attempt_id"]: (
                message["event"]["node_id"]
            )
            for message in replay_events
            if message["event"]["type"] == "node_attempt_started"
        }
        replay_attempt_starts = Counter(
            message["event"]["node_id"]
            for message in replay_events
            if message["event"]["type"] == "node_attempt_started"
        )
        replay_operation_starts = Counter(
            replay_attempt_nodes[message["event"]["node_attempt_id"]]
            for message in replay_events
            if message["event"]["type"] == "operation_attempt_started"
        )
        assert replayed_nodes
        assert replayed_nodes <= set(replay_attempt_starts)
        assert replayed_nodes.isdisjoint(replay_operation_starts)
        assert replay_events[-1]["event"] == {
            "type": "run_terminal",
            "status": "succeeded",
        }
