"""Fresh installed canonical 3GB1 scientific acceptance."""

from __future__ import annotations

from tests.support.ledger import public_run_events, public_run_projection

from core.catalog.builder import build_frozen_catalog

from protein_workbench_public.bootstrap import module_registrations

from collections import Counter
from importlib.resources import files
import json
import math
import os
from pathlib import Path
from typing import Any

import pytest

from protein_workbench_public.workflow_codec import decode_workflow_document
from datatypes.candidate import CandidateCollection
from datatypes.observation import PairwiseCandidateMapping
from tests.support.protocol import validate_event
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
from tests.acceptance.installed_harness import (
    InstalledArtifact,
    installed_artifact,
    run_external_acceptance,
)


PROJECT_ROOT = Path(__file__).resolve().parent.parent
PROJECT_ID = "canonical-3gb1"
RUN_LABEL = "fresh-canonical-3gb1"
PROTEINMPNN_BINDING_ID = "proteinmpnn.design.local"
PROTEINMPNN_BINDING_VERSION = "11.0.0"
PROTEINMPNN_METHOD_ID = "proteinmpnn.design.v_48_020_8907e667"
PROTEINMPNN_METHOD_VERSION = "6.0.0"
REMOTE_BINDINGS = {
    "esm3.generate_paired.biohub_medium": {
        "binding_version": "8.0.0",
        "method_id": "esm3.generate_paired.esm3_medium_2024_08",
        "method_version": "5.0.0",
        "adapter_id": "esm3.biohub/adapter",
        "adapter_version": "8.0.0",
        "model": "esm3-medium-2024-08",
        "source": "Biohub",
    },
    "folding.fold.esmfold2_remote": {
        "binding_version": "9.0.0",
        "method_id": "folding.fold.esmfold2_fast_biohub_2026_05",
        "method_version": "4.0.0",
        "adapter_id": "folding.esmfold2_remote/adapter",
        "adapter_version": "9.0.0",
        "model": "esmfold2-fast-2026-05",
        "source": "Biohub",
    },
}


def _environment() -> dict[tuple[str, str], Any]:
    environment = biohub_esm3_esmfold2_environment()
    environment[(PROTEINMPNN_BINDING_ID, PROTEINMPNN_BINDING_VERSION)] = {
        "values": {
            "device": "cpu",
            "provider_root": Path(
                os.environ["PROTEIN_WORKBENCH_PROTEINMPNN_ROOT"]
            ).resolve(),
        },
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
    grouped: dict[str, list[dict[str, Any]]] = {}
    for event in payloads:
        if event["type"] != "engine_invocation_started":
            continue
        node_id = node_by_operation[event["operation_attempt_id"]]
        grouped.setdefault(node_id, []).append(event)
    return {key: tuple(value) for key, value in grouped.items()}


def _assert_provider_invocations(
    catalog: Any,
    workflow: dict[str, Any],
    projection: dict[str, Any],
    events: tuple[dict[str, Any], ...],
) -> None:
    nodes = {node["node_id"]: node for node in workflow["nodes"]}
    dispositions = {
        item["node_id"]: item for item in projection["node_dispositions"]
    }
    terminal_by_invocation = {
        message["event"]["invocation_id"]: message["event"]
        for message in events
        if message["event"]["type"] == "engine_invocation_terminal"
    }
    invocations = _invocations_by_node(events)
    expected = {
        "generate-paired": ("esm3.generate_paired.biohub_medium", 20),
        "fold-sequences": ("folding.fold.esmfold2_remote", 10),
        "design-children": (PROTEINMPNN_BINDING_ID, 3),
        "fold-final": ("folding.fold.esmfold2_remote", 15),
    }
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
        assert all(
            terminal_by_invocation[invocation["invocation_id"]]["status"]
            == "succeeded"
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


def _provider_invocation_contract_fixture(
) -> tuple[Any, dict[str, Any], dict[str, Any], tuple[dict[str, Any], ...]]:
    catalog = build_frozen_catalog(module_registrations())
    workflow_nodes: list[dict[str, Any]] = []
    dispositions: list[dict[str, Any]] = []
    event_payloads: list[dict[str, Any]] = []

    def add_node(
        node_id: str,
        binding_id: str,
        binding_version: str,
        calls: tuple[
            tuple[
                str,
                str,
                str | None,
                dict[str, Any] | None,
                str,
            ],
            ...,
        ],
    ) -> None:
        workflow_nodes.append({
            "node_id": node_id,
            "binding_id": binding_id,
            "binding_version": binding_version,
        })
        dispositions.append({
            "node_id": node_id,
            "outcome": "succeeded",
            "resolution": "executed",
        })
        node_attempt_id = f"node-attempt-{node_id}"
        operation_attempt_id = f"operation-attempt-{node_id}"
        event_payloads.extend(
            (
                {
                    "type": "node_attempt_started",
                    "node_attempt_id": node_attempt_id,
                    "node_id": node_id,
                },
                {
                    "type": "operation_attempt_started",
                    "operation_attempt_id": operation_attempt_id,
                    "node_attempt_id": node_attempt_id,
                },
            )
        )
        engine_identity = catalog.require_contract(
            "binding", binding_id, binding_version
        ).descriptor["method"]["contract_digest"]
        for (
            invocation_id,
            engine_role,
            parent_invocation_id,
            provenance,
            terminal_status,
        ) in calls:
            started = {
                "type": "engine_invocation_started",
                "operation_attempt_id": operation_attempt_id,
                "invocation_id": invocation_id,
                "engine_identity": engine_identity,
                "engine_role": engine_role,
            }
            if parent_invocation_id is not None:
                started["parent_invocation_id"] = parent_invocation_id
            if provenance is not None:
                started["invocation_provenance"] = provenance
            event_payloads.extend(
                (
                    started,
                    {
                        "type": "engine_invocation_terminal",
                        "invocation_id": invocation_id,
                        "status": terminal_status,
                    },
                )
            )

    uncontrolled = {
        "effective_randomness": {"control": "provider_uncontrolled"}
    }
    add_node(
        "generate-paired",
        "esm3.generate_paired.biohub_medium",
        "8.0.0",
        tuple(
            call
            for index in range(10)
            for call in (
                (
                    f"sequence-parent-{index}",
                    "sequence_parent",
                    None,
                    uncontrolled,
                    "succeeded",
                ),
                (
                    f"structure-child-{index}",
                    "structure_child",
                    f"sequence-parent-{index}",
                    uncontrolled,
                    "succeeded",
                ),
            )
        ),
    )
    for node_id, count in (("fold-sequences", 10), ("fold-final", 15)):
        add_node(
            node_id,
            "folding.fold.esmfold2_remote",
            "9.0.0",
            tuple(
                (
                    f"{node_id}-{index}",
                    f"fold_parent_{index}_sample_0",
                    None,
                    uncontrolled,
                    "succeeded",
                )
                for index in range(count)
            ),
        )
    add_node(
        "design-children",
        PROTEINMPNN_BINDING_ID,
        PROTEINMPNN_BINDING_VERSION,
        tuple(
            (
                f"design-child-{index}",
                f"design_parent_{index}",
                None,
                {
                    "effective_randomness": {
                        "control": "exact_seed",
                        "effective_seed": 1603 + index,
                    },
                    "provider_residue_projection": {
                        "position_semantics": "one_based_chain_local",
                        "workbench_chain_order": ["A"],
                        "provider_structure_chain_order": ["A"],
                        "provider_chain_order": ["A"],
                        "entries": [
                            {
                                "residue_id": "A:1",
                                "segment_index": 0,
                                "provider_chain_id": "A",
                                "provider_position": 1,
                            }
                        ],
                    },
                },
                "succeeded",
            )
            for index in range(3)
        ),
    )
    add_node(
        "align-fixed",
        "structure_comparison.align_fixed_reference.sequence_primary_affine",
        "5.0.0",
        (
            (
                "local-alignment-failed-attempt",
                "evidence_tm_score",
                None,
                None,
                "failed",
            ),
            (
                "local-alignment-retry",
                "evidence_tm_score",
                None,
                None,
                "succeeded",
            ),
        ),
    )
    return (
        catalog,
        {"nodes": workflow_nodes},
        {"node_dispositions": dispositions},
        tuple(
            {
                "schema_namespace": "protein-workbench-public/v2",
                "project_id": "canonical-3gb1-fixture",
                "run_id": "run-fixture",
                "sequence": sequence,
                "cursor": f"cursor-{sequence}",
                "emitted_at": "2026-08-17T00:00:00+00:00",
                "event": event,
            }
            for sequence, event in enumerate(event_payloads, start=1)
        ),
    )


def test_provider_invocation_contract_allows_local_workflow_invocations(
) -> None:
    fixture = _provider_invocation_contract_fixture()
    for message in fixture[3]:
        validate_event(message)
    _assert_provider_invocations(*fixture)


def test_provider_invocation_contract_rejects_a_missing_call() -> None:
    catalog, workflow, projection, events = (
        _provider_invocation_contract_fixture()
    )
    incomplete = tuple(
        message
        for message in events
        if message["event"].get("invocation_id") != "fold-final-14"
    )
    for message in incomplete:
        validate_event(message)

    with pytest.raises(AssertionError):
        _assert_provider_invocations(
            catalog,
            workflow,
            projection,
            incomplete,
        )


def test_provider_invocation_contract_rejects_the_wrong_binding() -> None:
    catalog, workflow, projection, events = (
        _provider_invocation_contract_fixture()
    )
    wrong_workflow = {
        "nodes": [
            {
                **node,
                "binding_version": (
                    "6.0.0"
                    if node["node_id"] == "generate-paired"
                    else node["binding_version"]
                ),
            }
            for node in workflow["nodes"]
        ]
    }

    with pytest.raises(AssertionError):
        _assert_provider_invocations(
            catalog,
            wrong_workflow,
            projection,
            events,
        )


@pytest.mark.parametrize(
    ("invocation_id", "replacement"),
    (
        ("design-child-0", {"engine_identity": "sha256:" + "0" * 64}),
        ("design-child-0", {"engine_role": "wrong-role"}),
        ("fold-final-0", {"status": "failed"}),
    ),
)
def test_provider_invocation_contract_rejects_wrong_invocation_evidence(
    invocation_id: str,
    replacement: dict[str, Any],
) -> None:
    catalog, workflow, projection, events = (
        _provider_invocation_contract_fixture()
    )
    changed = tuple(
        {
            **message,
            "event": {**message["event"], **replacement},
        }
        if message["event"].get("invocation_id") == invocation_id
        and (
            (
                "status" in replacement
                and message["event"]["type"]
                == "engine_invocation_terminal"
            )
            or (
                "status" not in replacement
                and message["event"]["type"]
                == "engine_invocation_started"
            )
        )
        else message
        for message in events
    )
    for message in changed:
        validate_event(message)

    with pytest.raises(AssertionError):
        _assert_provider_invocations(
            catalog,
            workflow,
            projection,
            changed,
        )


def _assert_science(
    service: Any,
    catalog: Any,
    workflow: dict[str, Any],
    projection: dict[str, Any],
    events: tuple[dict[str, Any], ...],
) -> None:
    assert projection["status"] == "succeeded", events
    workflow_node_ids = {node["node_id"] for node in workflow["nodes"]}
    assert len(projection["node_dispositions"]) == len(workflow["nodes"])
    assert {
        item["node_id"] for item in projection["node_dispositions"]
    } == workflow_node_ids
    assert all(
        item["outcome"] == "succeeded"
        for item in projection["node_dispositions"]
    )
    event_payloads = tuple(message["event"] for message in events)
    passing_remote_readiness = {
        event["binding"]["contract_id"]
        for event in event_payloads
        if event["type"] == "readiness_attested"
        and event["conclusion"] == "passing"
        and event["binding"]["contract_id"] in REMOTE_BINDINGS
    }
    assert passing_remote_readiness == set(REMOTE_BINDINGS)
    _assert_provider_invocations(catalog, workflow, projection, events)

    paired_sequences = _one(
        service, catalog, projection, "generate-paired", "sequence_candidates"
    )
    paired_structures = _one(
        service, catalog, projection, "generate-paired", "structure_candidates"
    )
    folded_structures = _one(
        service, catalog, projection, "fold-sequences", "structure_candidates"
    )
    counterparts = _one(
        service, catalog, projection, "generate-paired", "counterpart_pairs"
    )
    rebound_counterparts = _one(
        service, catalog, projection, "rebind-counterparts", "pairing"
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
    assert type(folded_structures) is CandidateCollection
    assert type(counterparts) is PairwiseCandidateMapping
    assert type(rebound_counterparts) is PairwiseCandidateMapping
    assert len(paired_sequences.items) == len(paired_structures.items) == 10
    assert len(folded_structures.items) == 10
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
    assert len(fixed_alignments) == len(paired_alignments) == 10
    fixed_references = {
        alignment.reference.candidate_id for alignment in fixed_alignments
    }
    paired_references = {
        alignment.reference.candidate_id for alignment in paired_alignments
    }
    fixed_subjects = {
        alignment.subject.candidate_id for alignment in fixed_alignments
    }
    paired_subjects = {
        alignment.subject.candidate_id for alignment in paired_alignments
    }
    folded_ids = {
        candidate.candidate_id for candidate in folded_structures.items
    }
    assert len(fixed_references) == 1
    assert paired_references == {
        candidate.candidate_id for candidate in paired_structures.items
    }
    assert fixed_subjects == paired_subjects == folded_ids
    assert {
        (
            alignment.subject.candidate_id,
            alignment.reference.candidate_id,
        )
        for alignment in paired_alignments
    } == {
        (entry.subject.candidate_id, entry.reference.candidate_id)
        for entry in rebound_counterparts.entries
    }
    assert fixed_references.isdisjoint(paired_references)

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
        (artifact["candidate_id"], artifact["filename"])
        for artifact in projection["artifact_index"]
    ] == [
        (fold.candidate_id, f"structure-{index:04d}.pdb")
        for index, fold in enumerate(final_folds.items)
    ]
    assert all(
        artifact["artifact_kind"] == "candidate"
        and artifact["node_id"] == "export-final"
        and artifact["output_port"] == "candidate_artifacts"
        and artifact["media_type"] == "chemical/x-pdb"
        for artifact in projection["artifact_index"]
    )


@pytest.mark.acceptance
@pytest.mark.live_provider
def test_fresh_canonical_3gb1_public_run() -> None:
    from protein_workbench_public.bootstrap import create_application
    from fastapi.testclient import TestClient

    workflow = json.loads(
        files("examples").joinpath(
            "v2", "canonical-3gb1.workflow.json"
        ).read_text(encoding="utf-8")
    )
    catalog = build_frozen_catalog(module_registrations())
    app = create_application(v2_environment_configuration=_environment())
    with TestClient(app) as client:
        active_commit = client.get(
            f"/api/v2/projects/{PROJECT_ID}/workflow/active-commit"
        )
        active_commit.raise_for_status()
        commit = active_commit.json()
        assert commit["accepted"] is True
        assert commit["catalog_contract_digest"] == catalog.contract_digest
        assert commit["workflow_digest"] == decode_workflow_document(
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
        service = app.state.run_runtime
        wait_for_service_run_terminal_events(
            service,
            PROJECT_ID,
            started.json()["run_id"],
            timeout_seconds=75 * 60,
        )
        projection = public_run_projection(
            service,
            PROJECT_ID,
            started.json()["run_id"],
        )
        events = public_run_events(service, PROJECT_ID, projection["run_id"])

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
        os.environ["PROTEIN_WORKBENCH_ACCEPTANCE_EVIDENCE_STAGING"]
    )
    assert evidence_root.is_dir() and not any(evidence_root.iterdir())
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    env["PW_SOURCE_ROOT"] = str(PROJECT_ROOT)
    for name in ("PROJECT", "CACHE", "OUTPUT", "RUN"):
        isolated = tmp_path / name.lower()
        isolated.mkdir(mode=0o700)
        env[f"PROTEIN_WORKBENCH_{name}_ROOT"] = str(isolated)
    output = run_external_acceptance(
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
