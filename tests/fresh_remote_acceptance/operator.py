"""Validate and seal one fresh canonical run through public backend APIs."""

from __future__ import annotations

import hashlib
import json
import math
import os
import stat
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from tests.deterministic_acceptance.backend_client import DownloadedArtifact


PROJECT_ID = "canonical-3gb1"
CANONICAL_MODULE_CONTRACT = (
    ("import_3gb1", "import.structure"),
    ("build_layout", "prompt.build_residue_layout"),
    ("fixed_0", "prompt.random_fixed_positions"),
    ("compute_ss", "compute.dssp"),
    ("apply_edits", "prompt.apply_residue_edits"),
    ("override_ss", "prompt.override_residue_track"),
    ("mask_seq", "prompt.random_mask"),
    ("mask_struct", "prompt.random_mask"),
    ("insert_ss", "prompt.random_insert_masked"),
    ("insert_seq", "prompt.random_insert_masked"),
    ("insert_struct", "prompt.random_insert_masked"),
    ("assemble", "prompt.assemble_protein_prompt"),
    ("esm3_gen", "esm3.generate"),
    ("fold_seq", "esmfold2.fold"),
    ("align_3gb1", "structure.pairwise_align"),
    ("align_pw", "structure.pairwise_align"),
    ("tm_3gb1", "structure.batch_tm_score"),
    ("tm_esm3", "structure.batch_tm_score"),
    ("merge_tm", "scoring.merge"),
    ("rank", "selection.weighted_rank"),
    ("top3", "selection.top_k"),
    ("mpnn_0", "proteinmpnn.design"),
    ("final_fold", "esmfold2.fold"),
    ("export_final", "export.structure"),
)
CANONICAL_NODE_ORDER = tuple(
    node_id for node_id, _ in CANONICAL_MODULE_CONTRACT
)
CANONICAL_MODULE_IDS = dict(CANONICAL_MODULE_CONTRACT)
CANONICAL_EFFECTIVE_SEEDS = {
    "fixed_0": 4242,
    "insert_seq": 4242,
    "insert_ss": 4242,
    "insert_struct": 4242,
    "mask_seq": 4242,
    "mask_struct": 4242,
    "esm3_gen": 1603,
    "mpnn_0": 4242,
}
RUN_PROVIDER_CALL_COUNTS = Counter({
    ("local_open", "generate(track=sequence)"): 10,
    ("local_open", "generate(track=structure)"): 10,
    ("biohub", "fold"): 25,
    ("local-proteinmpnn", "design_sequences"): 3,
    ("mkdssp", "secondary_structure"): 1,
})
WEIGHTED_METRICS = [
    {"score": "tm_vs_3gb1", "weight": 0.7},
    {"score": "tm_vs_esm3", "weight": 0.3},
]


class ArtifactAPI(Protocol):
    """The run-scoped artifact retrieval part of the backend client."""

    def artifact(
        self,
        project_id: str,
        run_id: str,
        reference: str,
    ) -> DownloadedArtifact:
        """Retrieve one manifest-bound artifact by public reference."""


@dataclass(frozen=True)
class FreshRemoteContract:
    """Validated public facts needed before artifact retrieval."""

    project_id: str
    run_id: str
    source_revision: str
    workflow_sha256: str
    final_candidate_ids: tuple[str, ...]
    artifacts: tuple[dict[str, Any], ...]
    provider_call_counts: Counter[tuple[str, str]]


@dataclass(frozen=True)
class SealedFreshRemoteEvidence:
    """Paths and identity of one sealed evidence bundle."""

    run_id: str
    manifest_path: Path
    checksum_path: Path
    artifact_paths: tuple[Path, ...]


def public_workflow_sha256(workflow: dict[str, Any]) -> str:
    """Independently hash the public Workflow representation."""
    nodes = workflow.get("nodes")
    edges = workflow.get("edges")
    if not isinstance(nodes, list) or not isinstance(edges, list):
        raise AssertionError("canonical Workflow payload is malformed")
    payload = {
        "nodes": sorted(
            (
                {
                    "node_id": node["node_id"],
                    "module_id": node["module_id"],
                    "module_version": node.get("module_version", "1.0.0"),
                    "parameters": node.get("parameters", {}),
                }
                for node in nodes
            ),
            key=lambda item: item["node_id"],
        ),
        "edges": sorted(
            (
                {
                    "source_node_id": edge["source_node_id"],
                    "source_port": edge["source_port"],
                    "target_node_id": edge["target_node_id"],
                    "target_port": edge["target_port"],
                }
                for edge in edges
            ),
            key=lambda item: (
                item["source_node_id"],
                item["source_port"],
                item["target_node_id"],
                item["target_port"],
            ),
        ),
    }
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def canonical_module_inventory(
    workflow: dict[str, Any],
    module_definitions: list[dict[str, Any]],
) -> dict[str, tuple[str, str]]:
    """Bind each canonical Node to the public ModuleDefinition version."""
    nodes = workflow.get("nodes")
    if not isinstance(nodes, list):
        raise AssertionError("canonical Workflow Nodes are malformed")
    workflow_modules = {
        str(node.get("node_id")): str(node.get("module_id"))
        for node in nodes
        if isinstance(node, dict)
    }
    if workflow_modules != CANONICAL_MODULE_IDS:
        raise AssertionError("canonical Workflow Module identities changed")
    versions = {
        str(definition.get("module_id")): str(definition.get("version"))
        for definition in module_definitions
        if (
            isinstance(definition, dict)
            and definition.get("module_id")
            and definition.get("version")
        )
    }
    missing = sorted(set(CANONICAL_MODULE_IDS.values()) - versions.keys())
    if missing:
        raise AssertionError(
            "public ModuleDefinition versions are missing: "
            + ", ".join(missing)
        )
    return {
        node_id: (module_id, versions[module_id])
        for node_id, module_id in CANONICAL_MODULE_IDS.items()
    }


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


def _score_entries(
    manifest: dict[str, Any],
    node_id: str,
    score_id: str,
) -> list[dict[str, Any]]:
    return [
        score
        for score in manifest["scores"]
        if score["node_id"] == node_id
        and score["score_id"] == score_id
    ]


def _require_distinct(items: list[str], expected: int, label: str) -> None:
    if len(items) != expected or len(set(items)) != expected:
        raise AssertionError(
            f"{label} must contain exactly {expected} distinct Candidates"
        )


def _require_finite_scores(
    entries: list[dict[str, Any]],
    expected_subjects: list[str],
    label: str,
    *,
    bounded: bool,
) -> None:
    if len(entries) != len(expected_subjects):
        raise AssertionError(f"{label} score coverage is incomplete")
    subjects = [entry.get("subjects") for entry in entries]
    if subjects != [[subject] for subject in expected_subjects]:
        raise AssertionError(f"{label} scores do not bind the expected Candidates")
    for entry in entries:
        value = entry.get("value")
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(float(value))
            or bounded
            and not 0.0 <= float(value) <= 1.0
        ):
            raise AssertionError(f"{label} contains an invalid score")


def validate_fresh_remote_contract(
    *,
    manifest: dict[str, Any],
    outputs: dict[str, Any],
    events: list[dict[str, Any]],
    expected_revision: str,
    expected_workflow_sha256: str,
    expected_modules: dict[str, tuple[str, str]],
) -> FreshRemoteContract:
    """Validate one completed canonical run without reading backend files."""
    project_id = manifest.get("project_id")
    run_id = manifest.get("run_id")
    if project_id != PROJECT_ID or not isinstance(run_id, str) or not run_id:
        raise AssertionError("run manifest is not scoped to canonical-3gb1")
    if manifest.get("status") != "completed":
        raise AssertionError("fresh canonical run did not complete")
    if manifest.get("failures") or manifest.get("blocking_reasons"):
        raise AssertionError("fresh canonical run contains terminal failures")
    if manifest.get("source") != {
        "revision": expected_revision,
        "dirty": False,
    }:
        raise AssertionError("run manifest is not bound to the clean source revision")
    if manifest.get("workflow") != {"sha256": expected_workflow_sha256}:
        raise AssertionError("run manifest Workflow hash changed")
    if not isinstance(manifest.get("environment"), dict) or not {
        "python",
        "implementation",
        "platform",
    }.issubset(manifest["environment"]):
        raise AssertionError("run manifest environment is incomplete")
    manifest_modules = manifest.get("modules")
    if not isinstance(manifest_modules, list):
        raise AssertionError("run manifest ModuleDefinition inventory is incomplete")
    observed_modules = {
        str(item.get("node_id")): (
            str(item.get("module_id")),
            str(item.get("version")),
        )
        for item in manifest_modules
        if isinstance(item, dict)
    }
    if (
        len(observed_modules) != len(manifest_modules)
        or observed_modules != expected_modules
    ):
        raise AssertionError("run manifest ModuleDefinition identity changed")
    if manifest.get("effective_seeds") != CANONICAL_EFFECTIVE_SEEDS:
        raise AssertionError("run manifest effective seeds changed")

    if not events:
        raise AssertionError("run-scoped WebSocket produced no events")
    if [event.get("sequence") for event in events] != list(
        range(1, len(events) + 1)
    ):
        raise AssertionError("run-scoped WebSocket sequence is not monotonic")
    if {
        (event.get("project_id"), event.get("run_id"))
        for event in events
    } != {(PROJECT_ID, run_id)}:
        raise AssertionError("run-scoped WebSocket leaked another scope")
    if (
        events[0].get("type") != "run_started"
        or events[-1].get("type") != "run_completed"
        or tuple(events[0].get("node_order", ())) != CANONICAL_NODE_ORDER
    ):
        raise AssertionError("run-scoped WebSocket terminal contract changed")
    event_counts = Counter(event.get("type") for event in events)
    if event_counts != Counter({
        "run_started": 1,
        "node_state": 48,
        "node_completed": 24,
        "run_completed": 1,
    }):
        raise AssertionError("run-scoped WebSocket Node outcomes are incomplete")
    if Counter(
        event.get("state")
        for event in events
        if event.get("type") == "node_state"
    ) != Counter({"queued": 24, "running": 24}):
        raise AssertionError("run-scoped WebSocket Node state coverage is incomplete")
    queued_nodes = [
        event.get("node_id")
        for event in events
        if event.get("type") == "node_state"
        and event.get("state") == "queued"
    ]
    running_nodes = [
        event.get("node_id")
        for event in events
        if event.get("type") == "node_state"
        and event.get("state") == "running"
    ]
    completed_nodes = [
        event.get("node_id")
        for event in events
        if event.get("type") == "node_completed"
    ]
    if (
        tuple(queued_nodes) != CANONICAL_NODE_ORDER
        or tuple(running_nodes) != CANONICAL_NODE_ORDER
        or tuple(completed_nodes) != CANONICAL_NODE_ORDER
    ):
        raise AssertionError(
            "run-scoped WebSocket Node outcomes are not canonical"
        )
    event_positions = {
        (
            event.get("node_id"),
            (
                event.get("state")
                if event.get("type") == "node_state"
                else "completed"
            ),
        ): index
        for index, event in enumerate(events)
        if event.get("type") in {"node_state", "node_completed"}
    }
    if any(
        not (
            event_positions[(node_id, "queued")]
            < event_positions[(node_id, "running")]
            < event_positions[(node_id, "completed")]
        )
        for node_id in CANONICAL_NODE_ORDER
    ):
        raise AssertionError(
            "run-scoped WebSocket Node state transition order changed"
        )

    node_states = manifest.get("node_states")
    if not isinstance(node_states, list) or [
        event.get("sequence") for event in node_states
    ] != list(range(1, len(node_states) + 1)):
        raise AssertionError("run manifest Node outcomes are not ordered")
    final_states: dict[str, str] = {}
    for event in node_states:
        final_states[str(event.get("node_id"))] = str(event.get("state"))
    if final_states != {
        node_id: "completed" for node_id in CANONICAL_NODE_ORDER
    }:
        raise AssertionError("run manifest Node outcomes are incomplete")

    cache = manifest.get("cache")
    if (
        not isinstance(cache, list)
        or len(cache) != len(CANONICAL_NODE_ORDER)
        or Counter(entry.get("node_id") for entry in cache)
        != Counter(CANONICAL_NODE_ORDER)
        or any(
            entry.get("outcome") != "bypass"
            or not isinstance(entry.get("published"), bool)
            or entry.get("consumer") != {
                "project_id": PROJECT_ID,
                "run_id": run_id,
                "node_id": entry.get("node_id"),
            }
            for entry in cache
        )
    ):
        raise AssertionError(
            "fresh acceptance cannot use historical Cache entries"
        )

    sequence_ids = _lineage_ids(
        manifest,
        "esm3_gen",
        "sequence_candidates",
    )
    sampled_ids = _lineage_ids(
        manifest,
        "esm3_gen",
        "structure_candidates",
    )
    initial_ids = _lineage_ids(manifest, "fold_seq", "candidates")
    selected_ids = _lineage_ids(manifest, "top3", "candidates")
    mpnn_ids = _lineage_ids(manifest, "mpnn_0", "candidates")
    final_ids = _lineage_ids(manifest, "final_fold", "candidates")
    for items, expected, label in (
        (sequence_ids, 10, "ESM3 sequence"),
        (sampled_ids, 10, "ESM3 structure"),
        (initial_ids, 10, "initial fold"),
        (selected_ids, 3, "selected parent"),
        (mpnn_ids, 15, "ProteinMPNN child"),
        (final_ids, 15, "final fold"),
    ):
        _require_distinct(items, expected, label)

    lineage = manifest["candidate_lineage"]
    parent_by_node_and_candidate = {
        (entry["node_id"], entry["candidate_id"]): entry["parent_ids"]
        for entry in lineage
    }
    targeted_lineage = [
        entry
        for entry in lineage
        if entry.get("node_id") in {
            "esm3_gen",
            "fold_seq",
            "top3",
            "mpnn_0",
            "final_fold",
        }
        and entry.get("output_port") in {
            "sequence_candidates",
            "structure_candidates",
            "candidates",
        }
    ]
    targeted_keys = [
        (entry["node_id"], entry["candidate_id"])
        for entry in targeted_lineage
    ]
    if len(set(targeted_keys)) != len(targeted_keys):
        raise AssertionError("Candidate lineage contains duplicate Node bindings")
    if [
        parent_by_node_and_candidate[("esm3_gen", sequence_id)]
        for sequence_id in sequence_ids
    ] != [["esm3_gen"] for _ in sequence_ids]:
        raise AssertionError("ESM3 sequence Candidate lineage is incomplete")
    if [
        parent_by_node_and_candidate[("esm3_gen", sampled_id)]
        for sampled_id in sampled_ids
    ] != [[sequence_id] for sequence_id in sequence_ids]:
        raise AssertionError("paired ESM3 Candidate lineage is incomplete")
    if [
        parent_by_node_and_candidate[("fold_seq", initial_id)]
        for initial_id in initial_ids
    ] != [[sequence_id] for sequence_id in sequence_ids]:
        raise AssertionError("initial fold lineage is incomplete")
    mpnn_parents = [
        parent_by_node_and_candidate[("mpnn_0", child_id)]
        for child_id in mpnn_ids
    ]
    if (
        any(len(parent_ids) != 1 for parent_ids in mpnn_parents)
        or Counter(parent_ids[0] for parent_ids in mpnn_parents)
        != Counter({parent_id: 5 for parent_id in selected_ids})
    ):
        raise AssertionError("ProteinMPNN must produce five children per parent")
    if [
        parent_by_node_and_candidate[("final_fold", final_id)]
        for final_id in final_ids
    ] != [[child_id] for child_id in mpnn_ids]:
        raise AssertionError("final fold lineage is incomplete")

    tm_3gb1 = _score_entries(manifest, "tm_3gb1", "tm_vs_3gb1")
    tm_esm3 = _score_entries(manifest, "tm_esm3", "tm_vs_esm3")
    weighted = _score_entries(manifest, "rank", "weighted_rank")
    mpnn_scores = _score_entries(
        manifest,
        "mpnn_0",
        "proteinmpnn_score",
    )
    _require_finite_scores(
        tm_3gb1,
        initial_ids,
        "TM versus 3GB1",
        bounded=True,
    )
    _require_finite_scores(
        tm_esm3,
        initial_ids,
        "TM versus paired ESM3",
        bounded=True,
    )
    _require_finite_scores(
        mpnn_scores,
        mpnn_ids,
        "ProteinMPNN",
        bounded=False,
    )
    if (
        len(weighted) != len(initial_ids)
        or any(
            not isinstance(score.get("subjects"), list)
            or len(score["subjects"]) != 1
            for score in weighted
        )
    ):
        raise AssertionError("weighted rank Candidate coverage is incomplete")
    if {score["subjects"][0] for score in weighted} != set(initial_ids):
        raise AssertionError("weighted rank Candidate coverage is incomplete")
    tm_3gb1_by_subject = {
        score["subjects"][0]: float(score["value"]) for score in tm_3gb1
    }
    tm_esm3_by_subject = {
        score["subjects"][0]: float(score["value"]) for score in tm_esm3
    }
    for score in weighted:
        subject = score["subjects"][0]
        expected_weighted = (
            0.7 * tm_3gb1_by_subject[subject]
            + 0.3 * tm_esm3_by_subject[subject]
        )
        if not math.isclose(
            float(score["value"]),
            expected_weighted,
            rel_tol=1e-12,
            abs_tol=1e-12,
        ):
            raise AssertionError(
                "weighted rank does not match its objective scores"
            )
    weighted_order = [
        (-float(score["value"]), score["subjects"][0])
        for score in weighted
    ]
    if weighted_order != sorted(weighted_order):
        raise AssertionError("weighted rank is not ordered highest first")
    if any(
        score.get("details", {}).get("metrics") != WEIGHTED_METRICS
        for score in weighted
    ):
        raise AssertionError("weighted rank objective contract changed")
    if [score["subjects"][0] for score in weighted[:3]] != selected_ids:
        raise AssertionError("top-three selection does not match weighted rank")

    artifacts = outputs.get("artifacts")
    if (
        not isinstance(artifacts, list)
        or artifacts != manifest.get("artifacts")
        or len(artifacts) != 15
        or [artifact.get("candidate_id") for artifact in artifacts] != final_ids
        or [
            artifact.get("reference") for artifact in artifacts
        ] != [f"final/{candidate_id}.pdb" for candidate_id in final_ids]
        or any(
            artifact.get("node_id") != "export_final"
            or artifact.get("output_port") != "file_paths"
            or not isinstance(artifact.get("size"), int)
            or artifact["size"] <= 0
            or not isinstance(artifact.get("sha256"), str)
            or len(artifact["sha256"]) != 64
            for artifact in artifacts
        )
    ):
        raise AssertionError("final PDB manifest is incomplete")

    calls = manifest.get("providers", {}).get("calls")
    if not isinstance(calls, list):
        raise AssertionError("run manifest provider calls are missing")
    provider_call_counts = Counter(
        (str(call.get("provider")), str(call.get("operation")))
        for call in calls
    )
    if provider_call_counts != RUN_PROVIDER_CALL_COUNTS:
        raise AssertionError("run manifest provider call attempts are incomplete")
    if any(
        not call.get("model")
        or not isinstance(call.get("details"), dict)
        or call["details"].get("node_id") not in CANONICAL_NODE_ORDER
        for call in calls
    ):
        raise AssertionError("run manifest provider call identity is incomplete")

    return FreshRemoteContract(
        project_id=PROJECT_ID,
        run_id=run_id,
        source_revision=expected_revision,
        workflow_sha256=expected_workflow_sha256,
        final_candidate_ids=tuple(final_ids),
        artifacts=tuple(artifacts),
        provider_call_counts=provider_call_counts,
    )


def _write_once(path: Path, payload: bytes, *, mode: int = 0o400) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags, 0o600)
    try:
        with os.fdopen(descriptor, "wb", closefd=False) as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        os.close(descriptor)
    path.chmod(mode)


def seal_fresh_remote_evidence(
    *,
    evidence_root: Path,
    client: ArtifactAPI,
    contract: FreshRemoteContract,
    manifest: dict[str, Any],
    events: list[dict[str, Any]],
    provider_events: list[dict[str, Any]],
) -> SealedFreshRemoteEvidence:
    """Retrieve all run artifacts once and seal source-bound evidence."""
    if evidence_root.is_symlink():
        raise AssertionError("evidence root must not be a symlink")
    evidence_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    evidence_root.chmod(0o700)
    artifact_root = evidence_root / "artifacts"
    artifact_root.mkdir(mode=0o700)

    retained_artifacts: list[dict[str, Any]] = []
    artifact_paths: list[Path] = []
    checksum_lines: list[str] = []
    for artifact in contract.artifacts:
        reference = str(artifact["reference"])
        downloaded = client.artifact(
            contract.project_id,
            contract.run_id,
            reference,
        )
        if (
            not downloaded.payload
            or not any(
                line.startswith(b"ATOM  ")
                for line in downloaded.payload.splitlines()
            )
            or len(downloaded.payload) != artifact["size"]
            or downloaded.sha256 != artifact["sha256"]
        ):
            raise AssertionError(
                f"downloaded PDB does not match manifest: {reference}"
            )
        filename = Path(reference).name
        if (
            reference != f"final/{artifact['candidate_id']}.pdb"
            or filename != f"{artifact['candidate_id']}.pdb"
        ):
            raise AssertionError("artifact reference is not canonical")
        destination = artifact_root / filename
        _write_once(destination, downloaded.payload)
        artifact_paths.append(destination)
        relative = destination.relative_to(evidence_root).as_posix()
        checksum_lines.append(f"{downloaded.sha256}  {relative}\n")
        retained_artifacts.append({
            "candidate_id": artifact["candidate_id"],
            "reference": reference,
            "size": len(downloaded.payload),
            "sha256": downloaded.sha256,
            "retained_path": relative,
        })

    if len(artifact_paths) != 15:
        raise AssertionError("exactly fifteen PDB artifacts must be retained")
    checksum_path = evidence_root / "artifact-checksums.sha256"
    _write_once(checksum_path, "".join(checksum_lines).encode())
    sealed_manifest = {
        "schema_version": 1,
        "fresh_run": True,
        "historical_cache_allowed": False,
        "secrets_retained": False,
        "project_id": contract.project_id,
        "run_id": contract.run_id,
        "source": {
            "revision": contract.source_revision,
            "dirty": False,
        },
        "workflow": {"sha256": contract.workflow_sha256},
        "modules": manifest["modules"],
        "environment": manifest["environment"],
        "providers": {
            "run_call_attempts": manifest["providers"]["calls"],
            "validated_real_events": provider_events,
        },
        "effective_seeds": manifest["effective_seeds"],
        "cache": manifest["cache"],
        "ordered_node_outcomes": manifest["node_states"],
        "websocket_events": events,
        "candidate_lineage": manifest["candidate_lineage"],
        "scores": manifest["scores"],
        "artifacts": retained_artifacts,
        "backend_manifest": manifest,
        "backend_manifest_sha256": hashlib.sha256(
            json.dumps(
                manifest,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            ).encode()
        ).hexdigest(),
    }
    manifest_path = evidence_root / "sealed-manifest.json"
    _write_once(
        manifest_path,
        (
            json.dumps(sealed_manifest, indent=2, sort_keys=True) + "\n"
        ).encode(),
    )
    if stat.S_IMODE(manifest_path.stat().st_mode) != 0o400:
        raise AssertionError("sealed manifest is not read-only")
    return SealedFreshRemoteEvidence(
        run_id=contract.run_id,
        manifest_path=manifest_path,
        checksum_path=checksum_path,
        artifact_paths=tuple(artifact_paths),
    )
