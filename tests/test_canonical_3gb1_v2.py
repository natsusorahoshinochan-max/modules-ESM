"""Exact v2 acceptance for the maintained canonical 3GB1 Workflow.

The pre-agreed seams are the shipped Workflow document, the immutable
production Catalog/compiler, and the public installed-backend protocol.
"""

from __future__ import annotations

from core.catalog.builder import build_frozen_catalog

from protein_workbench_public.bootstrap import module_registrations

from collections import Counter
from dataclasses import replace
import hashlib
import json
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from starlette.websockets import WebSocketDisconnect
import torch

from core.workflow.authoring import WorkflowCommit
from core.workflow.compiler import (
    CompilationRequest,
    compile,
    lock_workflow,
)
from protein_workbench_public.workflow_codec import decode_workflow_document
from protein_workbench_public.bootstrap import create_application
from datatypes.candidate import (
    CandidateCollection,
    CandidateDataReference,
)
from datatypes.observation import (
    PairwiseCandidateMapping,
    ScoreCollection,
)
from modules.proteinmpnn.adapter import LocalProteinMPNNAdapter
from modules.structure_transform.domain import (
    CandidateResolvedResidueAxisAssociations,
)
from protein_workbench_public import artifact_content_disposition
from tests.fixtures.canonical_3gb1_v2 import (
    CANONICAL_PROVIDER_PROMPT_CONTENT_DIGEST,
    ControlledESM3Client,
    ControlledFoldingClient,
    ControlledProteinMPNNProvider,
    controlled_catalog,
    controlled_environment,
)
from tests.fixtures.public_v2 import (
    retrieve_typed_output_canonical_bytes,
    wait_for_testclient_run_terminal,
)


PROJECT_ROOT = Path(__file__).resolve().parent.parent
WORKFLOW_PATH = (
    PROJECT_ROOT / "examples" / "v2" / "canonical-3gb1.workflow.json"
)
EXPECTED_TOP_THREE = [
    "candidate-50c2b9947296a048c75cad2d9cc0220a3ae99ad38d6023b47c47bfd5e626cfd7",
    "candidate-7bbce318c17419b22c47b6f5dada2b99279db0e089571373c14da0636dbdb80f",
    "candidate-ce6705b0f150a1e7e66bf7f5bed22706c647b07d3ac34d7831d1040fd9fb2fd7",
]
EXPECTED_TOP_PARENT_INDICES = [2, 0, 3]
pytestmark = pytest.mark.deterministic_acceptance


def _workflow_payload() -> dict[str, Any]:
    return json.loads(WORKFLOW_PATH.read_text(encoding="utf-8"))


def _assert_workflow_commit_owner(
    app: FastAPI,
    *,
    workflow_commit_id: str,
) -> WorkflowCommit:
    owner = app.state.workflow_authoring
    commit = owner.load_active_commit("canonical-3gb1")
    draft = owner.load_draft("canonical-3gb1")
    compiled = owner.require_verified_commit(
        "canonical-3gb1",
        workflow_commit_id=workflow_commit_id,
    )
    plan = compiled.execution_plan

    assert commit.workflow_commit_id == workflow_commit_id
    assert commit.source_draft_revision == draft.draft_revision == 1
    assert commit.source_draft_digest == draft.draft_digest
    assert commit.workflow_commit_revision == 1
    assert plan.workflow_commit_revision == commit.workflow_commit_revision
    assert plan.workflow_digest == commit.workflow_digest
    assert plan.catalog_contract_digest == commit.catalog_contract_digest
    assert plan.contract_lock_digest == commit.contract_lock_digest
    assert plan.execution_plan_digest == commit.execution_plan_digest
    assert commit.workflow_commit_id == plan.execution_plan_digest.replace(
        "sha256:",
        "workflow-commit-",
    )
    return commit


def test_canonical_seed_is_exact_locked_compilable_v2() -> None:
    catalog = build_frozen_catalog(module_registrations())
    workflow = decode_workflow_document(_workflow_payload())

    assert workflow.workflow_id == "canonical-3gb1"
    assert workflow.schema_version == "2.1.0"
    assert workflow.contract_lock
    assert lock_workflow(replace(workflow, contract_lock=()), catalog) == workflow
    compiled = compile(
                   CompilationRequest(
                       workflow,
                       1,
                   ),
                   catalog,
               )
    assert compiled.resolved_contracts == workflow.contract_lock

    nodes = {node.node_id: node for node in workflow.nodes}
    assert all(not node.binding_parameters for node in nodes.values())
    expected_node_versions = {
        "import-3gb1": "6.0.0",
        "resolve-source-residue-axis": "4.0.0",
        "extract-imported-backbone": "4.0.0",
        "prompt-backbone-to-structure": "4.0.0",
        "resolve-imported-residue-axis": "4.0.0",
        "build-prompt": "5.0.0",
        "mask-sequence": "3.0.0",
        "mask-structure": "3.0.0",
        "insert-masked": "3.0.0",
        "override-secondary-structure": "3.0.0",
        "generate-paired": "8.0.0",
        "materialize-generated-confidence": "2.0.0",
        "fold-sequences": "8.0.0",
        "materialize-folded-confidence": "2.0.0",
        "rebind-counterparts": "4.0.0",
        "resolve-folded-residue-axes": "6.0.0",
        "resolve-generated-residue-axes": "6.0.0",
        "resolve-canonical-residue-axes": "6.0.0",
        "align-fixed": "5.0.0",
        "score-fixed": "6.0.0",
        "align-paired": "5.0.0",
        "score-paired": "6.0.0",
        "merge-scores": "5.0.0",
        "rank-candidates": "5.0.0",
        "take-top-three": "4.0.0",
        "resolve-selected-residue-axes": "6.0.0",
        "build-final-layout": "3.0.0",
        "fixed-positions": "4.0.0",
        "design-children": "10.0.0",
        "fold-final": "8.0.0",
        "materialize-final-confidence": "2.0.0",
        "export-final": "6.0.0",
    }
    assert {
        node.node_id: node.node_type_version for node in nodes.values()
    } == expected_node_versions
    expected_binding_versions = dict(expected_node_versions)
    expected_binding_versions.update({
        "design-children": "11.0.0",
        "fold-sequences": "9.0.0",
        "fold-final": "9.0.0",
    })
    assert {
        node.node_id: node.binding_version for node in nodes.values()
    } == expected_binding_versions
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
    workflow["edges"][0]["target_port"] = "missing"
    app = create_application(
        frozen_catalog_override=controlled_catalog(),
        _install_canonical_seed=True,
        v2_environment_configuration=controlled_environment(
            monkeypatch,
            esm3,
            folding,
        ),
    )

    with TestClient(app) as client:
        project_id = client.post(
            "/api/v2/projects",
            json={"name": "invalid canonical workflow"},
        ).json()["id"]
        workflow["workflow_id"] = project_id
        workflow["contract_lock"] = []
        rejected = client.post(
            f"/api/v2/projects/{project_id}/workflow:commit",
            json={
                "workflow": workflow,
            },
        )

    assert rejected.status_code == 422
    assert rejected.json()["error"]["code"] == "compile_rejected"
    assert not esm3.sequence_prompts
    assert not esm3.structure_prompts
    assert not folding.calls


def _decoded_output(
    client: TestClient,
    catalog: Any,
    projection: dict[str, Any],
    node_id: str,
    output_port: str,
) -> Any:
    decoded = _decoded_outputs(
        client,
        catalog,
        projection,
        node_id,
        output_port,
    )
    assert len(decoded) == 1
    return decoded[0]


def _decoded_outputs(
    client: TestClient,
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
            retrieve_typed_output_canonical_bytes(
                client,
                projection["project_id"],
                projection["run_id"],
                output,
                value_index,
            )
        )
        for value_index in range(output["value_count"])
    )


def _exact_structure_references(
    catalog: Any,
    candidates: CandidateCollection,
) -> set[CandidateDataReference]:
    structure_codec = catalog.require_port_type(
        "protein.structure",
        "4.0.0",
    )
    return {
        CandidateDataReference(
            candidate_id=candidate.candidate_id,
            data_type_id="protein.structure",
            content_digest=structure_codec.content_digest(candidate.data),
        )
        for candidate in candidates.items
    }


def _assert_exact_structure_axes(
    catalog: Any,
    associations: CandidateResolvedResidueAxisAssociations,
    candidates: CandidateCollection,
    *,
    expected_length: int = 71,
) -> None:
    assert type(associations) is CandidateResolvedResidueAxisAssociations
    expected_references = _exact_structure_references(catalog, candidates)
    assert {entry.subject for entry in associations.entries} == (
        expected_references
    )
    assert len(associations.entries) == len(candidates.items)
    for entry in associations.entries:
        axis = entry.residue_axis
        assert axis.layout.length == expected_length
        assert len(axis.layout.residue_ids or ()) == expected_length
        assert len(axis.sequence) == expected_length
        assert len(axis.residue_names) == expected_length
        assert len(axis.residue_coordinates) == expected_length
        assert len(axis.ca_coordinate_mask) == expected_length
        assert len(axis.complete_backbone_mask) == expected_length


def _assert_prediction_confidence(
    catalog: Any,
    observations: ScoreCollection,
    candidates: CandidateCollection,
    *,
    expected_method_id: str,
    expected_method_version: str,
) -> None:
    assert type(observations) is ScoreCollection
    expected_references = _exact_structure_references(catalog, candidates)
    expected_metrics = {
        ("structure.ptm", "2.1.0"),
        ("structure.plddt.per_residue", "3.0.0"),
        ("structure.plddt.mean_residue", "3.0.0"),
        ("structure.pae", "3.0.0"),
    }
    assert len(observations.entries) == 4 * len(candidates.items)
    assert {entry.subject for entry in observations.entries} == (
        expected_references
    )
    assert {
        (entry.metric.contract_id, entry.metric.contract_version)
        for entry in observations.entries
    } == expected_metrics
    assert {
        (entry.method.contract_id, entry.method.contract_version)
        for entry in observations.entries
    } == {(expected_method_id, expected_method_version)}
    assert {
        entry.source_partition for entry in observations.entries
    } == {"prediction_confidence"}

    for subject in expected_references:
        subject_entries = tuple(
            entry
            for entry in observations.entries
            if entry.subject == subject
        )
        assert {
            (entry.metric.contract_id, entry.metric.contract_version)
            for entry in subject_entries
        } == expected_metrics
        for entry in subject_entries:
            metric_id = entry.metric.contract_id
            if metric_id == "structure.ptm":
                assert entry.residue_axis is None
                assert type(entry.value) is float
                continue

            axis = entry.residue_axis
            assert axis is not None
            assert axis.axis_kind == "prediction_input"
            assert axis.axis_contract.contract_id == (
                "structure_prediction.prediction_residue_axis"
            )
            assert axis.axis_contract.contract_version == "2.0.0"
            assert axis.layout.length == 71
            assert len(axis.layout.residue_ids or ()) == 71
            if metric_id == "structure.plddt.per_residue":
                assert len(entry.value) == 71
            elif metric_id == "structure.plddt.mean_residue":
                assert type(entry.value) is float
            else:
                assert metric_id == "structure.pae"
                assert len(entry.value) == 71
                assert {len(row) for row in entry.value} == {71}


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
                lambda _environment, _directory, _models: proteinmpnn
            ),
        ),
    )
    catalog = controlled_catalog()
    assert catalog.contract_digest == (
        build_frozen_catalog(module_registrations()).contract_digest
    )
    controlled_configuration = controlled_environment(
        monkeypatch,
        esm3,
        folding,
    )
    app = create_application(
        frozen_catalog_override=catalog,
        _install_canonical_seed=True,
        v2_environment_configuration=controlled_configuration,
    )

    with TestClient(app) as client:
        catalog_snapshot = client.get("/api/v2/catalog")
        assert catalog_snapshot.status_code == 200
        assert catalog_snapshot.json()["catalog_contract_digest"] == (
            catalog.contract_digest
        )
        draft = client.get(
            "/api/v2/projects/canonical-3gb1/workflow/draft"
        )
        assert draft.status_code == 200
        expected_draft = _workflow_payload()
        expected_draft["contract_lock"] = []
        assert draft.json()["workflow"] == expected_draft
        active = client.get(
            "/api/v2/projects/canonical-3gb1/workflow/active-commit"
        )
        assert active.status_code == 200
        workflow_commit_id = active.json()["workflow_commit_id"]
        commit = _assert_workflow_commit_owner(
            app,
            workflow_commit_id=workflow_commit_id,
        )
        assert commit.contract_lock_digest == decode_workflow_document(
            _workflow_payload()
        ).contract_lock_digest

        def run(request_id: str) -> tuple[dict[str, Any], tuple[dict, ...]]:
            started = client.post(
                "/api/v2/projects/canonical-3gb1/runs",
                json={
                    "workflow_commit_id": workflow_commit_id,
                    "client_request_id": request_id,
                },
            )
            assert started.status_code == 202
            run_id = started.json()["run_id"]
            projection = wait_for_testclient_run_terminal(
                client,
                "canonical-3gb1",
                run_id,
                timeout_seconds=180,
            )
            return projection, _replay_events(client, run_id)

        first, first_events = run("canonical-v2-first")

        assert first["status"] == "succeeded", first["node_dispositions"]
        expected_node_ids = {
            node["node_id"] for node in _workflow_payload()["nodes"]
        }
        assert len(first["node_dispositions"]) == len(expected_node_ids)
        assert {
            disposition["node_id"]
            for disposition in first["node_dispositions"]
        } == expected_node_ids
        assert all(
            disposition["outcome"] == "succeeded"
            for disposition in first["node_dispositions"]
        )
        for output in first["outputs"]:
            assert "values" not in output
            assert {
                "node_id",
                "output_port",
                "port_type",
                "content_digest",
                "value_count",
                "value_manifest_reference",
                "result_identity",
                "materialization",
                "producer_provenance",
            } <= set(output)
            for value_index in range(output["value_count"]):
                canonical = retrieve_typed_output_canonical_bytes(
                    client,
                    first["project_id"],
                    first["run_id"],
                    output,
                    value_index,
                )
                assert canonical

        sequence_candidates = _decoded_output(
            client,
            catalog,
            first,
            "generate-paired",
            "sequence_candidates",
        )
        structure_candidates = _decoded_output(
            client,
            catalog,
            first,
            "generate-paired",
            "structure_candidates",
        )
        counterpart_pairs = _decoded_output(
            client,
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
                pair.subject.candidate_id,
                pair.reference.candidate_id,
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
            client,
            catalog,
            first,
            "fold-sequences",
            "structure_candidates",
        )
        rebound = _decoded_output(
            client,
            catalog,
            first,
            "rebind-counterparts",
            "pairing",
        )
        canonical_references = _decoded_output(
            client,
            catalog,
            first,
            "import-3gb1",
            "structure_candidates",
        )
        folded_residue_axes = _decoded_output(
            client,
            catalog,
            first,
            "resolve-folded-residue-axes",
            "residue_axes",
        )
        generated_residue_axes = _decoded_output(
            client,
            catalog,
            first,
            "resolve-generated-residue-axes",
            "residue_axes",
        )
        canonical_residue_axes = _decoded_output(
            client,
            catalog,
            first,
            "resolve-canonical-residue-axes",
            "residue_axes",
        )
        generated_confidence = _decoded_output(
            client,
            catalog,
            first,
            "materialize-generated-confidence",
            "observations",
        )
        folded_confidence = _decoded_output(
            client,
            catalog,
            first,
            "materialize-folded-confidence",
            "observations",
        )
        fixed_alignments = _decoded_outputs(
            client,
            catalog,
            first,
            "align-fixed",
            "alignments",
        )
        paired_alignments = _decoded_outputs(
            client,
            catalog,
            first,
            "align-paired",
            "alignments",
        )
        _assert_exact_structure_axes(
            catalog,
            folded_residue_axes,
            initial_folds,
        )
        _assert_exact_structure_axes(
            catalog,
            generated_residue_axes,
            structure_candidates,
        )
        _assert_exact_structure_axes(
            catalog,
            canonical_residue_axes,
            canonical_references,
            expected_length=56,
        )
        _assert_prediction_confidence(
            catalog,
            generated_confidence,
            structure_candidates,
            expected_method_id=(
                "esm3.generate_paired.esm3_medium_2024_08"
            ),
            expected_method_version="5.0.0",
        )
        _assert_prediction_confidence(
            catalog,
            folded_confidence,
            initial_folds,
            expected_method_id=(
                "folding.fold.esmfold2_fast_biohub_2026_05"
            ),
            expected_method_version="4.0.0",
        )
        assert len(initial_folds.items) == len(rebound.entries) == 10
        assert len({
            pair.reference.candidate_id
            for pair in rebound.entries
        }) == 10
        assert {
            pair.subject.candidate_id for pair in rebound.entries
        } == {
            candidate.candidate_id for candidate in initial_folds.items
        }
        assert {
            pair.reference.candidate_id for pair in rebound.entries
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
                pair.subject.candidate_id,
                pair.reference.candidate_id,
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
            client,
            catalog,
            first,
            "rank-candidates",
            "candidates",
        )
        selected = _decoded_output(
            client,
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
        selected_residue_axes = _decoded_output(
            client,
            catalog,
            first,
            "resolve-selected-residue-axes",
            "residue_axes",
        )
        _assert_exact_structure_axes(
            catalog,
            selected_residue_axes,
            selected,
        )
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
            client,
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
            client,
            catalog,
            first,
            "fold-final",
            "structure_candidates",
        )
        final_confidence = _decoded_output(
            client,
            catalog,
            first,
            "materialize-final-confidence",
            "observations",
        )
        assert len(final_folds.items) == 15
        assert [
            folded.parent_ids for folded in final_folds.items
        ] == [(child.candidate_id,) for child in children.items]
        _assert_prediction_confidence(
            catalog,
            final_confidence,
            final_folds,
            expected_method_id=(
                "folding.fold.esmfold2_fast_biohub_2026_05"
            ),
            expected_method_version="4.0.0",
        )
        assert len(first["artifact_index"]) == 15
        assert [
            artifact["candidate_id"]
            for artifact in first["artifact_index"]
        ] == [
            candidate.candidate_id for candidate in final_folds.items
        ]
        assert [
            artifact["filename"]
            for artifact in first["artifact_index"]
        ] == [
            f"structure-{index:04d}.pdb" for index in range(15)
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
            assert downloaded.headers["Content-Disposition"] == (
                artifact_content_disposition(artifact["filename"])
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
        ) == len(expected_node_ids)
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
        workflow_nodes = {
            node["node_id"]: node for node in _workflow_payload()["nodes"]
        }
        attempt_sequences = {
            message["event"]["node_id"]: message["sequence"]
            for message in first_events
            if message["event"]["type"] == "node_attempt_started"
        }
        readiness_messages = [
            message
            for message in first_events
            if message["event"]["type"] == "readiness_attested"
        ]
        assert readiness_messages
        for message in readiness_messages:
            binding = message["event"]["binding"]
            bound_nodes = [
                node_id
                for node_id, node in workflow_nodes.items()
                if (
                    node["binding_id"],
                    node["binding_version"],
                )
                == (
                    binding["contract_id"],
                    binding["contract_version"],
                )
            ]
            assert bound_nodes
            assert min(
                attempt_sequences[node_id] for node_id in bound_nodes
            ) < message["sequence"]
        proteinmpnn_readiness = next(
            message["event"]
            for message in first_events
            if message["event"]["type"] == "readiness_attested"
            and message["event"]["binding"]["contract_id"]
            == "proteinmpnn.design.local"
        )
        assert proteinmpnn_readiness["binding"]["contract_version"] == (
            "11.0.0"
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
                    output["value_count"],
                    output["value_manifest_reference"],
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
