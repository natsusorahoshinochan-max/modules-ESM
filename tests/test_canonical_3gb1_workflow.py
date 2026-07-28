"""Canonical 3GB1 Workflow acceptance through public backend seams."""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections import Counter
from pathlib import Path
from unittest.mock import patch

from core import Executor, ModuleRegistry, TypeRegistry, discover_modules
from core.project import CANONICAL_3GB1_PROJECT_ID, ProjectManager
from core.recovery import RunRecoveryService
from modules.esm3_adapter import derive_esm3_call_seed
from tests.fixtures.canonical_3gb1 import (
    PROTEINMPNN_SCORES,
    TM_VS_3GB1,
    TM_VS_ESM3,
    ControlledESMClient,
    ControlledFoldProvider,
    ControlledProteinMPNNProvider,
    canonical_modules,
    installed_esm_sdk,
)


PROJECT_ROOT = Path(__file__).parent.parent
RUN_ID = "canonical-fixture-16"
RUN_SEED = 4242


def _score_values(
    manifest: dict[str, object],
    node_id: str,
    score_id: str,
) -> list[float]:
    return [
        score["value"]
        for score in manifest["scores"]
        if score["node_id"] == node_id and score["score_id"] == score_id
    ]


def test_canonical_workflow_produces_fifteen_auditable_pdbs(
    tmp_path: Path,
) -> None:
    """One fresh fixture-backed run proves counts, ranking, and lineage."""
    type_registry = TypeRegistry()
    module_registry = ModuleRegistry(type_registry)
    discover_modules(module_registry)
    manager = ProjectManager(
        tmp_path / "projects",
        module_registry=module_registry,
        cache_root=tmp_path / "cache",
        output_root=tmp_path / "outputs",
        run_root=tmp_path / "runs",
    )
    manager.ensure_seed_project(
        PROJECT_ROOT / "examples" / "3gb1_pipeline.json",
        PROJECT_ROOT / "examples" / "3gb1_pipeline_ui.json",
        version="16",
    )
    workflow = manager.load_workflow(CANONICAL_3GB1_PROJECT_ID)
    assert workflow.validate(module_registry).to_dict() == {
        "valid": True,
        "errors": [],
    }

    historical_esm3 = ControlledESMClient()
    historical_folds = ControlledFoldProvider()
    historical_mpnn = ControlledProteinMPNNProvider()
    with (
        installed_esm_sdk(),
        patch(
            "modules.esm3_adapter.create_esm3_client",
            return_value=historical_esm3,
        ),
        patch(
            "modules.esmfold2_adapter.fold_sequence",
            side_effect=historical_folds,
        ),
    ):
        asyncio.run(
            Executor().execute(
                workflow,
                canonical_modules(historical_mpnn),
                str(manager.project_dir(CANONICAL_3GB1_PROJECT_ID)),
                "historical-fixture-16",
                seed=RUN_SEED,
                project_manager=manager,
                project_id=CANONICAL_3GB1_PROJECT_ID,
                source_dir=PROJECT_ROOT,
            )
        )
    assert historical_esm3.sequence_calls == 10
    assert historical_folds.calls == 25
    assert historical_mpnn.parent_calls == 3

    workflow = manager.load_workflow(CANONICAL_3GB1_PROJECT_ID)
    esm3 = ControlledESMClient()
    folds = ControlledFoldProvider()
    mpnn = ControlledProteinMPNNProvider()
    modules = canonical_modules(mpnn)
    with (
        installed_esm_sdk(),
        patch(
            "modules.esm3_adapter.create_esm3_client",
            return_value=esm3,
        ),
        patch(
            "modules.esmfold2_adapter.fold_sequence",
            side_effect=folds,
        ),
    ):
        results = asyncio.run(
            Executor().execute(
                workflow,
                modules,
                str(manager.project_dir(CANONICAL_3GB1_PROJECT_ID)),
                RUN_ID,
                seed=RUN_SEED,
                project_manager=manager,
                project_id=CANONICAL_3GB1_PROJECT_ID,
                source_dir=PROJECT_ROOT,
                provider_readiness={
                    "biohub": {"ready": True, "fixture": True},
                    "local_open": {"ready": True, "fixture": True},
                    "controlled-proteinmpnn": {
                        "ready": True,
                        "fixture": True,
                    },
                    "mkdssp": {"ready": True, "fixture": True},
                },
                force_rerun_nodes=set(workflow.nodes),
            )
        )

    sequence_candidates = results["esm3_gen"]["sequence_candidates"].items
    sampled_structures = results["esm3_gen"]["structure_candidates"].items
    initial_folds = results["fold_seq"]["candidates"].items
    assert [candidate.candidate_id for candidate in sequence_candidates] == [
        f"seq-{RUN_ID}-{index}" for index in range(10)
    ]
    assert [candidate.parent_ids for candidate in sampled_structures] == [
        [f"seq-{RUN_ID}-{index}"] for index in range(10)
    ]
    assert [candidate.parent_ids for candidate in initial_folds] == [
        [f"seq-{RUN_ID}-{index}"] for index in range(10)
    ]

    selected_parent_ids = [
        f"fold-{RUN_ID}-seq-{RUN_ID}-{index}" for index in range(3)
    ]
    assert [
        candidate.candidate_id
        for candidate in results["top3"]["candidates"].items
    ] == selected_parent_ids

    mpnn_children = results["mpnn_0"]["candidates"].items
    assert len(mpnn_children) == 15
    assert Counter(
        child.parent_ids[0] for child in mpnn_children
    ) == Counter({parent_id: 5 for parent_id in selected_parent_ids})
    assert [
        score.value
        for score in results["mpnn_0"]["scores"].entries
    ] == PROTEINMPNN_SCORES
    assert [request.seed for request in mpnn.requests] == [RUN_SEED] * 3
    assert [request.num_sequences for request in mpnn.requests] == [5] * 3

    final_folds = results["final_fold"]["candidates"].items
    final_ids = [
        f"fold-{RUN_ID}-mpnn-{RUN_ID}-{parent_index}-{sample_index}"
        for parent_index in range(3)
        for sample_index in range(5)
    ]
    assert [candidate.candidate_id for candidate in final_folds] == final_ids
    assert len(results["export_final"]["file_paths"]) == 15

    recovery = RunRecoveryService(manager)
    manifest = recovery.manifest(CANONICAL_3GB1_PROJECT_ID, RUN_ID)
    outputs = recovery.outputs(CANONICAL_3GB1_PROJECT_ID, RUN_ID)
    assert manifest["status"] == "completed"
    assert manifest["failures"] == []
    assert manifest["blocking_reasons"] == []
    assert {
        item["provider"]: item["ready"]
        for item in manifest["providers"]["readiness"]
    } == {
        "biohub": True,
        "local_open": True,
        "controlled-proteinmpnn": True,
        "mkdssp": True,
    }
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
    assert all(entry["outcome"] == "bypass" for entry in manifest["cache"])
    export_cache = [
        entry for entry in manifest["cache"]
        if entry["node_id"] == "export_final"
    ]
    assert export_cache == [{
        "node_id": "export_final",
        "cache_key": export_cache[0]["cache_key"],
        "outcome": "bypass",
        "published": False,
        "consumer": {
            "project_id": CANONICAL_3GB1_PROJECT_ID,
            "run_id": RUN_ID,
            "node_id": "export_final",
        },
    }]

    assert _score_values(manifest, "tm_3gb1", "tm_vs_3gb1") == TM_VS_3GB1
    assert _score_values(manifest, "tm_esm3", "tm_vs_esm3") == TM_VS_ESM3
    assert _score_values(
        manifest,
        "mpnn_0",
        "proteinmpnn_score",
    ) == PROTEINMPNN_SCORES
    weighted_scores = [
        score
        for score in manifest["scores"]
        if score["node_id"] == "rank"
        and score["score_id"] == "weighted_rank"
    ]
    assert [score["value"] for score in weighted_scores] == [
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
    assert [score["subjects"][0] for score in weighted_scores[:3]] == (
        selected_parent_ids
    )
    assert weighted_scores[0]["details"] == {
        "metrics": [
            {"score": "tm_vs_3gb1", "weight": 0.7},
            {"score": "tm_vs_esm3", "weight": 0.3},
        ]
    }

    call_counts = Counter(
        call["details"]["node_id"]
        for call in manifest["providers"]["calls"]
    )
    assert call_counts == Counter({
        "compute_ss": 1,
        "esm3_gen": 20,
        "fold_seq": 10,
        "align_3gb1": 10,
        "tm_3gb1": 10,
        "align_pw": 10,
        "tm_esm3": 10,
        "mpnn_0": 3,
        "final_fold": 15,
    })
    assert esm3.sequence_calls == esm3.structure_calls == 10
    assert folds.calls == 25
    assert mpnn.parent_calls == 3

    provider_calls = manifest["providers"]["calls"]
    scientific_calls = [
        call
        for call in provider_calls
        if call["provider"] in {"biopython-svd", "tmtools"}
    ]
    assert [
        (
            call["details"]["node_id"],
            call["provider"],
            call["operation"],
        )
        for call in scientific_calls
    ] == [
        ("align_3gb1", "biopython-svd", "structure_align")
    ] * 10 + [
        ("align_pw", "biopython-svd", "structure_align")
    ] * 10 + [
        ("tm_3gb1", "tmtools", "tm_score")
    ] * 10 + [
        ("tm_esm3", "tmtools", "tm_score")
    ] * 10
    assert all(
        call["details"]["actual_call"] is True
        and call["details"]["call_count"] == 1
        and call["details"]["result"]["status"] == "succeeded"
        and call["details"]["candidate_id"]
        for call in scientific_calls
    )
    esm3_calls = [
        call for call in provider_calls
        if call["details"]["node_id"] == "esm3_gen"
    ]
    required_secondary_structure = (
        "EEEEEEEEEEEEEEEEEEE___HHHHHHHH____"
        "EEEEEEEEEEEEEEEEEEEEEE_______________"
    )
    assert {
        (
            call["details"]["secondary_structure_length"],
            call["details"]["secondary_structure_sha256"],
        )
        for call in esm3_calls
    } == {
        (
            71,
            hashlib.sha256(required_secondary_structure.encode()).hexdigest(),
        )
    }
    expected_esm3_seeds = {
        derive_esm3_call_seed(1603, sample_index, track)
        for sample_index in range(10)
        for track in ("sequence", "structure")
    }
    assert {
        call["details"]["effective_seed"] for call in esm3_calls
    } == expected_esm3_seeds
    assert {
        call["details"]["requested_seed"] for call in esm3_calls
    } == {1603}
    assert {
        call["details"]["seed_control"] for call in esm3_calls
    } == {"torch_local"}
    assert {
        call["details"]["seed_scope"] for call in esm3_calls
    } == {"per_sample_track"}

    lineage = manifest["candidate_lineage"]
    artifacts = outputs["artifacts"]
    assert [artifact["candidate_id"] for artifact in artifacts] == final_ids
    assert [artifact["reference"] for artifact in artifacts] == [
        f"final/{candidate_id}.pdb" for candidate_id in final_ids
    ]
    for artifact in artifacts:
        record, chunks = recovery.artifact_chunks(
            CANONICAL_3GB1_PROJECT_ID,
            RUN_ID,
            artifact["reference"],
        )
        payload = b"".join(chunks)
        assert payload
        assert record["size"] == len(payload)
        assert record["sha256"] == hashlib.sha256(payload).hexdigest()
        assert payload.startswith(b"HEADER    CONTROLLED PROVIDER FIXTURE")

    for final_index, final_id in enumerate(final_ids):
        parent_index = final_index // 5
        sample_index = final_index % 5
        mpnn_id = (
            f"mpnn-{RUN_ID}-{parent_index}-{sample_index}"
        )
        selected_parent = selected_parent_ids[parent_index]
        sequence_id = f"seq-{RUN_ID}-{parent_index}"
        sampled_id = f"struct-{RUN_ID}-{parent_index}"
        assert {
            "node_id": "final_fold",
            "output_port": "candidates",
            "candidate_id": final_id,
            "parent_ids": [mpnn_id],
        } in lineage
        assert {
            "node_id": "mpnn_0",
            "output_port": "candidates",
            "candidate_id": mpnn_id,
            "parent_ids": [selected_parent],
        } in lineage
        assert {
            "node_id": "fold_seq",
            "output_port": "candidates",
            "candidate_id": selected_parent,
            "parent_ids": [sequence_id],
        } in lineage
        assert {
            "node_id": "esm3_gen",
            "output_port": "structure_candidates",
            "candidate_id": sampled_id,
            "parent_ids": [sequence_id],
        } in lineage
        assert {
            "node_id": "align_pw",
            "output_port": "alignments",
            "candidate_id": selected_parent,
            "parent_ids": [sampled_id],
        } in lineage

        assert any(
            call["details"].get("candidate_id") == final_id
            and call["details"].get("parent_candidate_id") == mpnn_id
            for call in provider_calls
            if call["details"]["node_id"] == "final_fold"
        )
        assert any(
            mpnn_id in call["details"].get("candidate_ids", [])
            and call["details"].get("parent_candidate_id")
            == selected_parent
            for call in provider_calls
            if call["details"]["node_id"] == "mpnn_0"
        )
        assert any(
            call["details"].get("candidate_id") == selected_parent
            and call["details"].get("parent_candidate_id") == sequence_id
            for call in provider_calls
            if call["details"]["node_id"] == "fold_seq"
        )
        assert any(
            call["details"].get("candidate_id") == sequence_id
            and call["operation"] == "generate(track=sequence)"
            for call in esm3_calls
        )
        assert any(
            call["details"].get("candidate_id") == sampled_id
            and call["details"].get("parent_candidate_id") == sequence_id
            and call["operation"] == "generate(track=structure)"
            for call in esm3_calls
        )

    manifest_text = json.dumps(manifest, sort_keys=True)
    assert str(tmp_path) not in manifest_text
    assert "historical-fixture-16" not in manifest_text
    assert all(RUN_ID in artifact["candidate_id"] for artifact in artifacts)
    assert "authorization" not in manifest_text.lower()
    assert len(manifest["source"]["revision"]) == 40
