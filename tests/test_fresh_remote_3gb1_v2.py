"""Fresh installed canonical 3GB1 scientific acceptance."""

from __future__ import annotations

from collections import Counter
from importlib.resources import files
import json
import math
import os
from pathlib import Path
from typing import Any

import pytest

from core import build_discovered_frozen_catalog, parse_workflow_document
from datatypes import CandidateCollection, PairwiseCandidateMapping
from tests.acceptance.retained_evidence import (
    require_retained_evidence,
    retain_service_run,
)
from tests.acceptance.biohub_environment import (
    biohub_esm3_esmfold2_environment,
)
from tests.fixtures.canonical_3gb1_v2 import (
    CANONICAL_PROVIDER_PROMPT_CONTENT_DIGEST,
)
from tests.fixtures.public_v2 import wait_for_service_run_terminal_events
from tests.test_installed_backend_v2 import (
    InstalledArtifact,
    _run_external_acceptance,
    installed_artifact,
)


PROJECT_ROOT = Path(__file__).resolve().parent.parent
PROJECT_ID = "canonical-3gb1"
RUN_LABEL = "fresh-canonical-3gb1"
PROTEINMPNN_BINDING_ID = "proteinmpnn.design.local"
PROTEINMPNN_BINDING_VERSION = "10.0.0"
PROTEINMPNN_METHOD_ID = "proteinmpnn.design.v_48_020_8907e667"
PROTEINMPNN_METHOD_VERSION = "6.0.0"
REMOTE_BINDINGS = {
    "esm3.generate_paired.biohub_medium": {
        "binding_version": "7.0.0",
        "method_id": "esm3.generate_paired.esm3_medium_2024_08",
        "method_version": "5.0.0",
        "adapter_id": "esm3.biohub/adapter",
        "adapter_version": "7.0.0",
        "model": "esm3-medium-2024-08",
        "source": "Biohub",
    },
    "folding.fold.esmfold2_remote": {
        "binding_version": "7.0.0",
        "method_id": "folding.fold.esmfold2_fast_biohub_2026_05",
        "method_version": "4.0.0",
        "adapter_id": "folding.esmfold2_remote/adapter",
        "adapter_version": "7.0.0",
        "model": "esmfold2-fast-2026-05",
        "source": "Biohub",
    },
}


def _environment() -> dict[tuple[str, str], Any]:
    from modules.proteinmpnn.adapter import configured_runtime_fingerprint

    proteinmpnn_fingerprint = configured_runtime_fingerprint()
    environment = biohub_esm3_esmfold2_environment()
    environment[(PROTEINMPNN_BINDING_ID, PROTEINMPNN_BINDING_VERSION)] = {
        "values": {
            "device": "cpu",
            "provider_root": Path(
                os.environ["PROTEIN_WORKBENCH_PROTEINMPNN_ROOT"]
            ).resolve(),
            "resolved_runtime_fingerprint": proteinmpnn_fingerprint,
        },
        "safe_fingerprint": proteinmpnn_fingerprint,
        "invalidation_token": proteinmpnn_fingerprint,
    }
    return environment


def _values(
    service: Any,
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
    codec = catalog.require_port_type(
        output["port_type"]["contract_id"],
        output["port_type"]["contract_version"],
    )
    return tuple(
        codec.decode(
            service.typed_value(
                projection["project_id"],
                projection["run_id"],
                node_id,
                output_port,
                index,
            )[1]
        )
        for index in range(output["value_count"])
    )


def _one(
    service: Any,
    catalog: Any,
    projection: dict[str, Any],
    node_id: str,
    output_port: str,
) -> Any:
    values = _values(service, catalog, projection, node_id, output_port)
    assert len(values) == 1
    return values[0]


def _invocations_by_node(
    events: tuple[dict[str, Any], ...],
) -> dict[str, tuple[dict[str, Any], ...]]:
    payloads = tuple(message["event"] for message in events)
    node_by_attempt = {
        event["node_attempt_id"]: event["node_id"]
        for event in payloads
        if event["type"] == "node_attempt_started"
    }
    node_by_operation = {
        event["operation_attempt_id"]: node_by_attempt[event["node_attempt_id"]]
        for event in payloads
        if event["type"] == "operation_attempt_started"
    }
    terminal_by_invocation = {
        event["invocation_id"]: event
        for event in payloads
        if event["type"] == "engine_invocation_terminal"
    }
    grouped: dict[str, list[dict[str, Any]]] = {}
    for event in payloads:
        if event["type"] != "engine_invocation_started":
            continue
        node_id = node_by_operation[event["operation_attempt_id"]]
        assert terminal_by_invocation[event["invocation_id"]]["status"] == (
            "succeeded"
        )
        grouped.setdefault(node_id, []).append(event)
    return {key: tuple(value) for key, value in grouped.items()}


def _assert_exact_engine_invocations(
    catalog: Any,
    workflow: dict[str, Any],
    projection: dict[str, Any],
    events: tuple[dict[str, Any], ...],
) -> None:
    nodes = {node["node_id"]: node for node in workflow["nodes"]}
    dispositions = {
        item["node_id"]: item for item in projection["node_dispositions"]
    }
    invocations = _invocations_by_node(events)
    expected = {
        "generate-paired": ("esm3.generate_paired.biohub_medium", 20),
        "fold-sequences": ("folding.fold.esmfold2_remote", 10),
        "design-children": (PROTEINMPNN_BINDING_ID, 3),
        "fold-final": ("folding.fold.esmfold2_remote", 15),
    }
    assert sum(count for _, count in expected.values()) == 48
    assert set(invocations) == set(expected)
    assert sum(len(items) for items in invocations.values()) == 48
    for node_id, (binding_id, count) in expected.items():
        node = nodes[node_id]
        binding_version = (
            PROTEINMPNN_BINDING_VERSION
            if binding_id == PROTEINMPNN_BINDING_ID
            else REMOTE_BINDINGS[binding_id]["binding_version"]
        )
        assert (node["binding_id"], node["binding_version"]) == (
            binding_id,
            binding_version,
        )
        assert dispositions[node_id]["outcome"] == "succeeded"
        assert dispositions[node_id]["resolution"] == "executed"
        binding = catalog.require_contract(
            "binding", binding_id, binding_version
        )
        assert len(invocations[node_id]) == count
        assert all(
            invocation["engine_identity"]
            == binding.descriptor["method"]["contract_digest"]
            for invocation in invocations[node_id]
        )

    esm3 = invocations["generate-paired"]
    assert Counter(item["engine_role"] for item in esm3) == {
        "sequence_parent": 10,
        "structure_child": 10,
    }
    sequence_parents = {
        item["invocation_id"]
        for item in esm3
        if item["engine_role"] == "sequence_parent"
    }
    assert Counter(
        item["parent_invocation_id"]
        for item in esm3
        if item["engine_role"] == "structure_child"
    ) == Counter({parent: 1 for parent in sequence_parents})
    assert all(
        item["invocation_provenance"] == {
            "effective_randomness": {"control": "provider_uncontrolled"}
        }
        for item in esm3
    )

    for node_id, count in (("fold-sequences", 10), ("fold-final", 15)):
        folds = invocations[node_id]
        assert Counter(item["engine_role"] for item in folds) == Counter({
            f"fold_parent_{index}_sample_0": 1 for index in range(count)
        })
        assert all(
            item["invocation_provenance"] == {
                "effective_randomness": {
                    "control": "provider_uncontrolled"
                }
            }
            for item in folds
        )

    proteinmpnn = invocations["design-children"]
    assert Counter(item["engine_role"] for item in proteinmpnn) == {
        "design_parent_0": 1,
        "design_parent_1": 1,
        "design_parent_2": 1,
    }
    assert all(
        item["invocation_provenance"]["effective_randomness"]["control"]
        == "exact_seed"
        and type(
            item["invocation_provenance"]["effective_randomness"][
                "effective_seed"
            ]
        )
        is int
        and "provider_residue_projection" in item["invocation_provenance"]
        for item in proteinmpnn
    )

    for binding_id, expected_contract in REMOTE_BINDINGS.items():
        binding = catalog.require_contract(
            "binding", binding_id, expected_contract["binding_version"]
        )
        method = catalog.require_contract(
            "method",
            expected_contract["method_id"],
            expected_contract["method_version"],
        )
        assert binding.descriptor["method"] == method.reference()
        assert (
            binding.descriptor["route_behavior"]["behavior_id"],
            binding.descriptor["route_behavior"]["behavior_version"],
        ) == (
            expected_contract["adapter_id"],
            expected_contract["adapter_version"],
        )
        assert binding.descriptor["implementation_identity"]["model"] == (
            expected_contract["model"]
        )
        assert method.descriptor["model_identity"]["source"] == (
            expected_contract["source"]
        )

    proteinmpnn_method = catalog.require_contract(
        "method", PROTEINMPNN_METHOD_ID, PROTEINMPNN_METHOD_VERSION
    )
    proteinmpnn_binding = catalog.require_contract(
        "binding", PROTEINMPNN_BINDING_ID, PROTEINMPNN_BINDING_VERSION
    )
    assert proteinmpnn_binding.descriptor["method"] == (
        proteinmpnn_method.reference()
    )


def _assert_science(
    service: Any,
    catalog: Any,
    workflow: dict[str, Any],
    projection: dict[str, Any],
    events: tuple[dict[str, Any], ...],
) -> None:
    assert projection["status"] == "succeeded", events
    assert len(projection["node_dispositions"]) == len(workflow["nodes"])
    assert all(
        item["outcome"] == "succeeded"
        for item in projection["node_dispositions"]
    )
    _assert_exact_engine_invocations(catalog, workflow, projection, events)

    paired_sequences = _one(
        service, catalog, projection, "generate-paired", "sequence_candidates"
    )
    paired_structures = _one(
        service, catalog, projection, "generate-paired", "structure_candidates"
    )
    counterparts = _one(
        service, catalog, projection, "generate-paired", "counterpart_pairs"
    )
    prompt = _one(
        service,
        catalog,
        projection,
        "override-secondary-structure",
        "protein_prompt",
    )
    fixed_alignments = _values(
        service, catalog, projection, "align-fixed", "alignments"
    )
    paired_alignments = _values(
        service, catalog, projection, "align-paired", "alignments"
    )
    ranked = _one(
        service, catalog, projection, "rank-candidates", "candidates"
    )
    selected = _one(
        service, catalog, projection, "take-top-three", "candidates"
    )
    children = _one(
        service, catalog, projection, "design-children", "sequence_candidates"
    )
    final_folds = _one(
        service, catalog, projection, "fold-final", "structure_candidates"
    )

    assert type(paired_sequences) is CandidateCollection
    assert type(paired_structures) is CandidateCollection
    assert type(counterparts) is PairwiseCandidateMapping
    assert len(paired_sequences.items) == len(paired_structures.items) == 10
    assert len(counterparts.entries) == 10
    assert [item.parent_ids for item in paired_structures.items] == [
        (sequence.candidate_id,) for sequence in paired_sequences.items
    ]
    assert {
        (entry.subject.candidate_id, entry.reference.candidate_id)
        for entry in counterparts.entries
    } == {
        (sequence.candidate_id, structure.candidate_id)
        for sequence, structure in zip(
            paired_sequences.items,
            paired_structures.items,
            strict=True,
        )
    }
    assert {
        alignment.reference.candidate_id for alignment in fixed_alignments
    }.isdisjoint({
        alignment.reference.candidate_id for alignment in paired_alignments
    })
    assert len(fixed_alignments) == len(paired_alignments) == 10

    assert selected.items == ranked.items[:3]
    selected_ids = {candidate.candidate_id for candidate in selected.items}
    assert Counter(child.parent_ids[0] for child in children.items) == Counter({
        candidate_id: 5 for candidate_id in selected_ids
    })
    assert len(children.items) == len(final_folds.items) == 15
    assert [fold.parent_ids for fold in final_folds.items] == [
        (child.candidate_id,) for child in children.items
    ]
    assert {
        item["objective_id"]: item["declared_weight"]
        for item in projection["selection_results"][0]["objectives"]
    } == {"fixed-3gb1": 0.7, "paired-esm3": 0.3}

    prompt_output = next(
        output
        for output in projection["outputs"]
        if output["node_id"] == "override-secondary-structure"
        and output["output_port"] == "protein_prompt"
    )
    visible_backbones = sum(
        bool(is_visible)
        and value is not None
        and all(
            atom in value
            and all(
                isinstance(coordinate, (int, float))
                and math.isfinite(coordinate)
                for coordinate in value[atom]
            )
            for atom in ("N", "CA", "C")
        )
        for value, is_visible in zip(
            prompt.structure_track.values,
            prompt.structure_visibility_track.values,
            strict=True,
        )
    )
    assert prompt.num_residues == 71
    assert sum(value is None for value in prompt.sequence_track.values) == 35
    assert len(prompt.secondary_structure_track.values) == 71
    assert visible_backbones == 46
    assert prompt_output["content_digest"] == (
        CANONICAL_PROVIDER_PROMPT_CONTENT_DIGEST
    )
    assert "".join(
        value if value is not None else "_"
        for value in prompt.sequence_track.values
    ) == (
        "____Y_KL__N_GKT___G__TT__AVDA_T_E_KV_KQ_Y_A_D_N_GVD_G__W_YD_____TF_V_TE"
    )
    assert "".join(
        value if value is not None else "_"
        for value in prompt.secondary_structure_track.values
    ) == (
        "EEEEEEEEEEEEEEEEEEE___HHHHHHHH____EEEEEEEEEEEEEEEEEEEEEE_______________"
    )
    assert "".join(
        "1" if value else "0"
        for value in prompt.structure_visibility_track.values
    ) == (
        "10101011111011110111011111111111101111101011101011101101111111101111011"
    )
    assert len(projection["artifact_index"]) == 15
    assert [
        artifact["candidate_id"] for artifact in projection["artifact_index"]
    ] == [fold.candidate_id for fold in final_folds.items]


@pytest.mark.acceptance
@pytest.mark.live_provider
def test_fresh_canonical_3gb1_public_run() -> None:
    from core.server import create_app
    from fastapi.testclient import TestClient

    workflow = json.loads(
        files("examples").joinpath(
            "v2", "canonical-3gb1.workflow.json"
        ).read_text(encoding="utf-8")
    )
    catalog = build_discovered_frozen_catalog()
    app = create_app(v2_environment_configuration=_environment())
    with TestClient(app) as client:
        active_commit = client.get(
            f"/api/v2/projects/{PROJECT_ID}/workflow/active-commit"
        )
        active_commit.raise_for_status()
        commit = active_commit.json()
        assert commit["accepted"] is True
        assert commit["catalog_contract_digest"] == catalog.contract_digest
        assert commit["workflow_digest"] == parse_workflow_document(
            workflow
        ).digest
        started = client.post(
            f"/api/v2/projects/{PROJECT_ID}/runs",
            json={
                "workflow_commit_id": commit["workflow_commit_id"],
                "client_request_id": RUN_LABEL,
            },
        )
        started.raise_for_status()
        service = app.state.run_execution_v2
        wait_for_service_run_terminal_events(
            service,
            PROJECT_ID,
            started.json()["run_id"],
            timeout_seconds=75 * 60,
        )
        projection = service.projection(PROJECT_ID, started.json()["run_id"])
        events = service.public_events(PROJECT_ID, projection["run_id"])

        assert projection["workflow_commit_id"] == commit["workflow_commit_id"]
        assert projection["workflow_digest"] == commit["workflow_digest"]
        assert "derived_from_run_id" not in projection
        _assert_science(service, catalog, workflow, projection, events)
        retain_service_run(
            RUN_LABEL,
            catalog=catalog,
            service=service,
            projection=projection,
            events=events,
        )


@pytest.mark.acceptance
@pytest.mark.live_provider
def test_fresh_remote_3gb1_installed_public_run_retains_auditable_bundle(
    installed_artifact: InstalledArtifact,
    tmp_path: Path,
) -> None:
    evidence_root = Path(
        os.environ["PROTEIN_WORKBENCH_FRESH_EVIDENCE_STAGING"]
    )
    assert evidence_root.is_dir() and not any(evidence_root.iterdir())
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    env["PW_SOURCE_ROOT"] = str(PROJECT_ROOT)
    for name in ("PROJECT", "CACHE", "OUTPUT", "RUN"):
        isolated = tmp_path / name.lower()
        isolated.mkdir(mode=0o700)
        env[f"PROTEIN_WORKBENCH_{name}_ROOT"] = str(isolated)
    output = _run_external_acceptance(
        installed_artifact,
        tmp_path,
        selectors=(
            "tests/test_fresh_remote_3gb1_v2.py::"
            "test_fresh_canonical_3gb1_public_run",
        ),
        environment=env,
        timeout_seconds=80 * 60,
    )
    assert "Bearer " not in output
    require_retained_evidence(
        evidence_root,
        required_runs=(RUN_LABEL,),
    )
