"""Fresh canonical acceptance is checked only through public backend facts."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

import pytest

from scripts.verify_backend import seal_bundle_checksums, validate_fresh_bundle
from tests.deterministic_acceptance.backend_client import DownloadedArtifact
from tests.fresh_remote_acceptance.operator import (
    CANONICAL_MODULE_IDS,
    seal_fresh_remote_evidence,
    validate_fresh_remote_contract,
)


RUN_ID = "12345678-1234-1234-1234-123456789abc"
PROJECT_ID = "canonical-3gb1"
REVISION = "1" * 40
WORKFLOW_SHA256 = "2" * 64


class ArtifactClient:
    """External artifact API boundary with fixed literal PDB payloads."""

    def __init__(self, payloads: dict[str, bytes]) -> None:
        self.payloads = payloads
        self.requested: list[tuple[str, str, str]] = []

    def artifact(
        self,
        project_id: str,
        run_id: str,
        reference: str,
    ) -> DownloadedArtifact:
        self.requested.append((project_id, run_id, reference))
        payload = self.payloads[reference]
        return DownloadedArtifact(
            payload=payload,
            sha256=hashlib.sha256(payload).hexdigest(),
        )


def _candidate_ids(prefix: str, count: int) -> list[str]:
    return [f"{prefix}-{index}" for index in range(count)]


def _complete_public_run() -> tuple[
    dict[str, Any],
    dict[str, Any],
    list[dict[str, Any]],
    dict[str, bytes],
]:
    sequence_ids = _candidate_ids("sequence", 10)
    sampled_ids = _candidate_ids("sampled", 10)
    initial_ids = _candidate_ids("initial-fold", 10)
    selected_ids = initial_ids[:3]
    mpnn_ids = _candidate_ids("mpnn", 15)
    final_ids = _candidate_ids("final-fold", 15)
    lineage = []
    for sequence_id, sampled_id, initial_id in zip(
        sequence_ids,
        sampled_ids,
        initial_ids,
        strict=True,
    ):
        lineage.extend([
            {
                "node_id": "esm3_gen",
                "output_port": "sequence_candidates",
                "candidate_id": sequence_id,
                "parent_ids": ["esm3_gen"],
            },
            {
                "node_id": "esm3_gen",
                "output_port": "structure_candidates",
                "candidate_id": sampled_id,
                "parent_ids": [sequence_id],
            },
            {
                "node_id": "fold_seq",
                "output_port": "candidates",
                "candidate_id": initial_id,
                "parent_ids": [sequence_id],
            },
        ])
    for parent_index, parent_id in enumerate(selected_ids):
        for sample_index in range(5):
            child_index = parent_index * 5 + sample_index
            lineage.extend([
                {
                    "node_id": "mpnn_0",
                    "output_port": "candidates",
                    "candidate_id": mpnn_ids[child_index],
                    "parent_ids": [parent_id],
                },
                {
                    "node_id": "final_fold",
                    "output_port": "candidates",
                    "candidate_id": final_ids[child_index],
                    "parent_ids": [mpnn_ids[child_index]],
                },
            ])
    lineage.extend({
        "node_id": "top3",
        "output_port": "candidates",
        "candidate_id": selected_id,
        "parent_ids": [sequence_ids[index]],
    } for index, selected_id in enumerate(selected_ids))

    scores = []
    for index, initial_id in enumerate(initial_ids):
        scores.extend([
            {
                "node_id": "tm_3gb1",
                "output_port": "scores",
                "score_id": "tm_vs_3gb1",
                "value": round(0.90 - index * 0.01, 4),
                "subjects": [initial_id],
                "details": {},
            },
            {
                "node_id": "tm_esm3",
                "output_port": "scores",
                "score_id": "tm_vs_esm3",
                "value": round(0.80 - index * 0.01, 4),
                "subjects": [initial_id],
                "details": {},
            },
            {
                "node_id": "rank",
                "output_port": "scores",
                "score_id": "weighted_rank",
                "value": round(0.87 - index * 0.01, 4),
                "subjects": [initial_id],
                "details": {
                    "metrics": [
                        {"score": "tm_vs_3gb1", "weight": 0.7},
                        {"score": "tm_vs_esm3", "weight": 0.3},
                    ]
                },
            },
        ])
    for index, mpnn_id in enumerate(mpnn_ids):
        scores.append({
            "node_id": "mpnn_0",
            "output_port": "scores",
            "score_id": "proteinmpnn_score",
            "value": round(-0.1 - index * 0.01, 4),
            "subjects": [mpnn_id],
            "details": {},
        })

    payloads = {
        f"final/{candidate_id}.pdb": (
            f"HEADER    FRESH REMOTE {index:02d}\n"
            f"ATOM      1  CA  ALA A   1      {index:6.3f}   0.000   0.000\n"
            "END\n"
        ).encode()
        for index, candidate_id in enumerate(final_ids)
    }
    artifacts = [
        {
            "node_id": "export_final",
            "candidate_id": candidate_id,
            "output_port": "file_paths",
            "reference": reference,
            "size": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest(),
        }
        for candidate_id, (reference, payload) in zip(
            final_ids,
            payloads.items(),
            strict=True,
        )
    ]
    node_order = [
        "import_3gb1",
        "build_layout",
        "fixed_0",
        "compute_ss",
        "apply_edits",
        "override_ss",
        "mask_seq",
        "mask_struct",
        "insert_ss",
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
    events = [{
        "sequence": 1,
        "type": "run_started",
        "project_id": PROJECT_ID,
        "run_id": RUN_ID,
        "node_order": node_order,
    }]
    sequence = 2
    for node_id in node_order:
        events.extend([
            {
                "sequence": sequence,
                "type": "node_state",
                "state": "queued",
                "node_id": node_id,
                "project_id": PROJECT_ID,
                "run_id": RUN_ID,
            },
            {
                "sequence": sequence + 1,
                "type": "node_state",
                "state": "running",
                "node_id": node_id,
                "project_id": PROJECT_ID,
                "run_id": RUN_ID,
            },
            {
                "sequence": sequence + 2,
                "type": "node_completed",
                "node_id": node_id,
                "project_id": PROJECT_ID,
                "run_id": RUN_ID,
            },
        ])
        sequence += 3
    events.append({
        "sequence": sequence,
        "type": "run_completed",
        "project_id": PROJECT_ID,
        "run_id": RUN_ID,
    })

    provider_calls = []
    for node_id, provider, operation, model, count in (
        ("compute_ss", "mkdssp", "secondary_structure", "mkdssp", 1),
        (
            "esm3_gen",
            "local_open",
            "generate(track=sequence)",
            "esm3_sm_open_v1",
            10,
        ),
        (
            "esm3_gen",
            "local_open",
            "generate(track=structure)",
            "esm3_sm_open_v1",
            10,
        ),
        (
            "fold_seq",
            "biohub",
            "fold",
            "esmfold2-fast-2026-05",
            10,
        ),
        (
            "mpnn_0",
            "local-proteinmpnn",
            "design_sequences",
            "v_48_020",
            3,
        ),
        (
            "final_fold",
            "biohub",
            "fold",
            "esmfold2-fast-2026-05",
            15,
        ),
    ):
        provider_calls.extend({
            "provider": provider,
            "operation": operation,
            "model": model,
            "details": {"node_id": node_id},
        } for _ in range(count))

    manifest = {
        "schema_version": 1,
        "project_id": PROJECT_ID,
        "run_id": RUN_ID,
        "status": "completed",
        "source": {"revision": REVISION, "dirty": False},
        "workflow": {"sha256": WORKFLOW_SHA256},
        "modules": [
            {
                "node_id": node_id,
                "module_id": CANONICAL_MODULE_IDS[node_id],
                "version": "1",
            }
            for node_id in node_order
        ],
        "environment": {
            "python": "3.12.11",
            "implementation": "CPython",
            "platform": "darwin",
        },
        "models": [],
        "effective_seeds": {
            "fixed_0": 4242,
            "insert_seq": 4242,
            "insert_ss": 4242,
            "insert_struct": 4242,
            "mask_seq": 4242,
            "mask_struct": 4242,
            "esm3_gen": 1603,
            "mpnn_0": 4242,
        },
        "node_states": [
            {
                "sequence": index + 1,
                "node_id": node_id,
                "old_state": "running",
                "state": "completed",
            }
            for index, node_id in enumerate(node_order)
        ],
        "failures": [],
        "blocking_reasons": [],
        "cache": [
            {
                "node_id": node_id,
                "cache_key": f"cache-{index}",
                "outcome": "bypass",
                "published": False,
                "consumer": {
                    "project_id": PROJECT_ID,
                    "run_id": RUN_ID,
                    "node_id": node_id,
                },
            }
            for index, node_id in enumerate(node_order)
        ],
        "providers": {"readiness": [], "calls": provider_calls},
        "candidate_lineage": lineage,
        "scores": scores,
        "artifacts": artifacts,
    }
    return manifest, {"artifacts": artifacts}, events, payloads


def _complete_provider_events(
    manifest: dict[str, Any],
) -> list[dict[str, Any]]:
    lineage = manifest["candidate_lineage"]

    def entries(node_id: str, output_port: str) -> list[dict[str, Any]]:
        return [
            entry
            for entry in lineage
            if entry["node_id"] == node_id
            and entry["output_port"] == output_port
        ]

    events: list[dict[str, Any]] = []
    for operation, output_port in (
        ("esm3.generate_sequence", "sequence_candidates"),
        ("esm3.generate_structure", "structure_candidates"),
    ):
        for entry in entries("esm3_gen", output_port):
            events.append({
                "event_type": "provider_call",
                "provider": "local_open",
                "operation": operation,
                "run_id": RUN_ID,
                "node_id": "esm3_gen",
                "candidate_id": entry["candidate_id"],
                **(
                    {"parent_candidate_id": entry["parent_ids"][0]}
                    if operation == "esm3.generate_structure"
                    else {}
                ),
                "result": {"summary": {"result_type": "ESMProtein"}},
            })
    for node_id in ("fold_seq", "final_fold"):
        artifacts_by_candidate = {
            artifact["candidate_id"]: artifact
            for artifact in manifest["artifacts"]
        }
        for entry in entries(node_id, "candidates"):
            summary = {"pdb_sha256": "0" * 64}
            if entry["candidate_id"] in artifacts_by_candidate:
                summary = {
                    "pdb_sha256": artifacts_by_candidate[
                        entry["candidate_id"]
                    ]["sha256"]
                }
            events.append({
                "event_type": "provider_call",
                "provider": "biohub",
                "operation": "esmfold2.fold",
                "run_id": RUN_ID,
                "node_id": node_id,
                "candidate_id": entry["candidate_id"],
                "parent_candidate_id": entry["parent_ids"][0],
                "result": {"summary": summary},
            })
    mpnn_entries = entries("mpnn_0", "candidates")
    for parent_id in [
        entry["candidate_id"] for entry in entries("top3", "candidates")
    ]:
        events.append({
            "event_type": "provider_call",
            "provider": "local-proteinmpnn",
            "operation": "design_sequences",
            "run_id": RUN_ID,
            "node_id": "mpnn_0",
            "candidate_ids": [
                entry["candidate_id"]
                for entry in mpnn_entries
                if entry["parent_ids"] == [parent_id]
            ],
            "parent_candidate_id": parent_id,
            "result": {"summary": {"sequence_count": 5}},
        })
    events.append({
        "event_type": "provider_call",
        "provider": "mkdssp",
        "operation": "secondary_structure",
        "run_id": RUN_ID,
        "node_id": "compute_ss",
        "result": {"summary": {"residue_count": 56}},
    })
    for node_id in ("align_3gb1", "align_pw"):
        events.extend({
            "event_type": "provider_call",
            "provider": "biopython-svd",
            "operation": "structure_align",
            "run_id": RUN_ID,
            "node_id": node_id,
            "result": {"summary": {"aligned_residues": 56}},
        } for _ in range(10))
    for node_id, score_id in (
        ("tm_3gb1", "tm_vs_3gb1"),
        ("tm_esm3", "tm_vs_esm3"),
    ):
        node_scores = [
            score
            for score in manifest["scores"]
            if score["node_id"] == node_id
            and score["score_id"] == score_id
        ]
        events.extend({
            "event_type": "provider_call",
            "provider": "tmtools",
            "operation": "tm_score",
            "run_id": RUN_ID,
            "node_id": node_id,
            "result": {"summary": {"value": score["value"]}},
        } for score in node_scores)
    return events


def test_operator_retrieves_exactly_fifteen_run_bound_pdbs_and_seals_bundle(
    tmp_path: Path,
) -> None:
    manifest, outputs, events, payloads = _complete_public_run()
    client = ArtifactClient(payloads)

    contract = validate_fresh_remote_contract(
        manifest=manifest,
        outputs=outputs,
        events=events,
        expected_revision=REVISION,
        expected_workflow_sha256=WORKFLOW_SHA256,
        expected_modules={
            node_id: (module_id, "1")
            for node_id, module_id in CANONICAL_MODULE_IDS.items()
        },
    )
    provider_events = _complete_provider_events(manifest)
    sealed = seal_fresh_remote_evidence(
        evidence_root=tmp_path,
        client=client,
        contract=contract,
        manifest=manifest,
        events=events,
        provider_events=provider_events,
    )

    assert contract.provider_call_counts == Counter({
        ("local_open", "generate(track=sequence)"): 10,
        ("local_open", "generate(track=structure)"): 10,
        ("biohub", "fold"): 25,
        ("local-proteinmpnn", "design_sequences"): 3,
        ("mkdssp", "secondary_structure"): 1,
    })
    assert len(client.requested) == 15
    assert {request[:2] for request in client.requested} == {
        (PROJECT_ID, RUN_ID)
    }
    assert len(list((tmp_path / "artifacts").glob("*.pdb"))) == 15
    checksum_lines = (
        tmp_path / "artifact-checksums.sha256"
    ).read_text().splitlines()
    assert len(checksum_lines) == 15
    assert json.loads((tmp_path / "sealed-manifest.json").read_text())[
        "fresh_run"
    ] is True
    assert sealed.run_id == RUN_ID
    retained_files = {
        "command-transcript.txt": b"return_code=0\n",
        "environment-summary.json": b"{}\n",
        "provider-calls.jsonl": b"\n",
        "provider-summary.json": b"{}\n",
        "pytest.xml": b"<testsuites />\n",
    }
    for name, payload in retained_files.items():
        path = tmp_path / name
        path.write_bytes(payload)
        path.chmod(0o600)

    validated_run_id, validation_error = validate_fresh_bundle(
        tmp_path,
        expected_revision=REVISION,
        provider_events=provider_events,
    )

    assert validation_error is None
    assert validated_run_id == RUN_ID

    checksum_path = seal_bundle_checksums(tmp_path)
    sealed_run_id, sealed_validation_error = validate_fresh_bundle(
        tmp_path,
        expected_revision=REVISION,
        provider_events=provider_events,
    )

    assert checksum_path.name == "bundle-checksums.sha256"
    assert sealed_validation_error is None
    assert sealed_run_id == RUN_ID


def test_operator_rejects_any_historical_cache_hit() -> None:
    manifest, outputs, events, _ = _complete_public_run()
    manifest["cache"][3]["outcome"] = "hit"

    with pytest.raises(
        AssertionError,
        match="fresh acceptance cannot use historical Cache entries",
    ):
        validate_fresh_remote_contract(
            manifest=manifest,
            outputs=outputs,
            events=events,
            expected_revision=REVISION,
            expected_workflow_sha256=WORKFLOW_SHA256,
            expected_modules={
                node_id: (module_id, "1")
                for node_id, module_id in CANONICAL_MODULE_IDS.items()
            },
        )


def test_operator_accepts_cache_published_by_the_fresh_bypass_run() -> None:
    manifest, outputs, events, _ = _complete_public_run()
    for entry in manifest["cache"]:
        entry["published"] = entry["node_id"] != "export_final"

    contract = validate_fresh_remote_contract(
        manifest=manifest,
        outputs=outputs,
        events=events,
        expected_revision=REVISION,
        expected_workflow_sha256=WORKFLOW_SHA256,
        expected_modules={
            node_id: (module_id, "1")
            for node_id, module_id in CANONICAL_MODULE_IDS.items()
        },
    )

    assert contract.run_id == RUN_ID


def test_operator_rejects_noncanonical_websocket_node_outcome() -> None:
    manifest, outputs, events, _ = _complete_public_run()
    completed = [
        event for event in events if event["type"] == "node_completed"
    ]
    completed[1]["node_id"] = completed[0]["node_id"]

    with pytest.raises(AssertionError, match="outcomes are not canonical"):
        validate_fresh_remote_contract(
            manifest=manifest,
            outputs=outputs,
            events=events,
            expected_revision=REVISION,
            expected_workflow_sha256=WORKFLOW_SHA256,
            expected_modules={
                node_id: (module_id, "1")
                for node_id, module_id in CANONICAL_MODULE_IDS.items()
            },
        )


def test_operator_rejects_websocket_completion_before_running() -> None:
    manifest, outputs, events, _ = _complete_public_run()
    running = next(
        event
        for event in events
        if event.get("node_id") == "import_3gb1"
        and event.get("state") == "running"
    )
    completed = next(
        event
        for event in events
        if event.get("node_id") == "import_3gb1"
        and event.get("type") == "node_completed"
    )
    running["type"] = "node_completed"
    running.pop("state")
    completed["type"] = "node_state"
    completed["state"] = "running"

    with pytest.raises(AssertionError, match="transition order changed"):
        validate_fresh_remote_contract(
            manifest=manifest,
            outputs=outputs,
            events=events,
            expected_revision=REVISION,
            expected_workflow_sha256=WORKFLOW_SHA256,
            expected_modules={
                node_id: (module_id, "1")
                for node_id, module_id in CANONICAL_MODULE_IDS.items()
            },
        )


def test_bundle_rejects_wrong_provider_node_and_tm_result(
    tmp_path: Path,
) -> None:
    manifest, outputs, events, payloads = _complete_public_run()
    client = ArtifactClient(payloads)
    contract = validate_fresh_remote_contract(
        manifest=manifest,
        outputs=outputs,
        events=events,
        expected_revision=REVISION,
        expected_workflow_sha256=WORKFLOW_SHA256,
        expected_modules={
            node_id: (module_id, "1")
            for node_id, module_id in CANONICAL_MODULE_IDS.items()
        },
    )
    provider_events = _complete_provider_events(manifest)
    seal_fresh_remote_evidence(
        evidence_root=tmp_path,
        client=client,
        contract=contract,
        manifest=manifest,
        events=events,
        provider_events=provider_events,
    )
    for name in (
        "command-transcript.txt",
        "environment-summary.json",
        "provider-calls.jsonl",
        "provider-summary.json",
        "pytest.xml",
    ):
        path = tmp_path / name
        path.write_text("{}\n")
        path.chmod(0o600)
    sealed_manifest_path = tmp_path / "sealed-manifest.json"

    def replace_sealed_provider_events() -> None:
        sealed_manifest = json.loads(sealed_manifest_path.read_text())
        sealed_manifest["providers"]["validated_real_events"] = provider_events
        sealed_manifest_path.chmod(0o600)
        sealed_manifest_path.write_text(
            json.dumps(sealed_manifest, sort_keys=True) + "\n"
        )
        sealed_manifest_path.chmod(0o400)

    provider_events[0]["node_id"] = "fold_seq"
    replace_sealed_provider_events()

    _, error = validate_fresh_bundle(
        tmp_path,
        expected_revision=REVISION,
        provider_events=provider_events,
    )

    assert error == "provider evidence was not bound to the fresh run"

    provider_events[0]["node_id"] = "esm3_gen"
    tm_event = next(
        event
        for event in provider_events
        if event["operation"] == "tm_score"
    )
    tm_event["result"]["summary"]["value"] = 0.1234
    replace_sealed_provider_events()

    _, error = validate_fresh_bundle(
        tmp_path,
        expected_revision=REVISION,
        provider_events=provider_events,
    )

    assert error == "TM provider results did not match manifest scores"


def test_operator_rejects_module_version_drift() -> None:
    manifest, outputs, events, _ = _complete_public_run()
    expected_modules = {
        node_id: (module_id, "1")
        for node_id, module_id in CANONICAL_MODULE_IDS.items()
    }
    manifest["modules"][0]["version"] = "drifted"

    with pytest.raises(
        AssertionError,
        match="ModuleDefinition identity changed",
    ):
        validate_fresh_remote_contract(
            manifest=manifest,
            outputs=outputs,
            events=events,
            expected_revision=REVISION,
            expected_workflow_sha256=WORKFLOW_SHA256,
            expected_modules=expected_modules,
        )


def test_operator_rejects_weighted_score_that_does_not_match_objectives() -> None:
    manifest, outputs, events, _ = _complete_public_run()
    weighted = next(
        score
        for score in manifest["scores"]
        if score["score_id"] == "weighted_rank"
    )
    weighted["value"] += 0.005

    with pytest.raises(
        AssertionError,
        match="does not match its objective scores",
    ):
        validate_fresh_remote_contract(
            manifest=manifest,
            outputs=outputs,
            events=events,
            expected_revision=REVISION,
            expected_workflow_sha256=WORKFLOW_SHA256,
            expected_modules={
                node_id: (module_id, "1")
                for node_id, module_id in CANONICAL_MODULE_IDS.items()
            },
        )


def test_operator_rejects_extra_proteinmpnn_parent() -> None:
    manifest, outputs, events, _ = _complete_public_run()
    child = next(
        entry
        for entry in manifest["candidate_lineage"]
        if entry["node_id"] == "mpnn_0"
    )
    child["parent_ids"].append("unexpected-parent")

    with pytest.raises(
        AssertionError,
        match="five children per parent",
    ):
        validate_fresh_remote_contract(
            manifest=manifest,
            outputs=outputs,
            events=events,
            expected_revision=REVISION,
            expected_workflow_sha256=WORKFLOW_SHA256,
            expected_modules={
                node_id: (module_id, "1")
                for node_id, module_id in CANONICAL_MODULE_IDS.items()
            },
        )
