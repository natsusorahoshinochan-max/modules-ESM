#!/usr/bin/env python3
"""Generate and validate one source-bound installed remote 3GB1 evidence bundle."""

from __future__ import annotations

from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import time
from typing import Any


SCHEMA_NAMESPACE = "protein-workbench-fresh-remote-3gb1/v2"
PROJECT_ID = "canonical-3gb1"
VERSION = "2.1.0"
REMOTE_CONTRACT_VERSION = "3.0.0"
PROTEINMPNN_BINDING_VERSION = "4.0.0"
PROTEINMPNN_METHOD_VERSION = "3.0.0"
PROTEINMPNN_BINDING_ID = "proteinmpnn.design.local"
PROTEINMPNN_METHOD_ID = "proteinmpnn.design.v_48_020_8907e667"
CANONICAL_PROVIDER_PROMPT_CONTENT_DIGEST = (
    "sha256:dc2653e01ea98a529664fab883f1deb4b02d47ef029e9923724050bb59fce419"
)
CANONICAL_SEQUENCE_TRACK = (
    "____Y_KL__N_GKT___G__TT__AVDA_T_E_KV_KQ_Y_A_D_N_GVD_G__W_YD_____TF_V_TE"
)
CANONICAL_SECONDARY_STRUCTURE_TRACK = (
    "EEEEEEEEEEEEEEEEEEE___HHHHHHHH____EEEEEEEEEEEEEEEEEEEEEE_______________"
)
CANONICAL_STRUCTURE_VISIBILITY_TRACK = (
    "10101011111011110111011111111111101111101011101011101101111111101111011"
)
REMOTE_BINDINGS = {
    "esm3.generate_paired.biohub_medium": {
        "method": "esm3.generate_paired.esm3_medium_2024_08",
        "adapter": "esm3.biohub/adapter",
        "model": "esm3-medium-2024-08",
        "source": "Biohub",
    },
    "folding.fold.esmfold2_remote": {
        "method": "folding.fold.esmfold2_fast_biohub_2026_05",
        "adapter": "folding.esmfold2_remote/adapter",
        "model": "esmfold2-fast-2026-05",
        "source": "Biohub",
    },
}
REQUIRED_FILES = {
    "source-receipt.json",
    "public-protocol.json",
    "catalog-snapshot.json",
    "workflow-snapshot.json",
    "compile-receipt.json",
    "run-index.json",
    "candidate-lineage.json",
    "invocation-proof.json",
    "artifact-index.json",
    "verification.json",
}
_DIGEST_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
_PROVIDER_UNCONTROLLED = {
    "effective_randomness": {
        "control": "provider_uncontrolled",
    }
}


def _sha256(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _json_bytes(value: Any) -> bytes:
    return (
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode()
        + b"\n"
    )


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.write_bytes(_json_bytes(value))
    path.chmod(0o600)


def _load_json(path: Path) -> Any:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"evidence file is not regular: {path.name}")
    return json.loads(path.read_bytes())


def _contract(
    catalog: dict[str, Any],
    kind: str,
    contract_id: str,
    contract_version: str,
) -> dict[str, Any]:
    matches = [
        item
        for item in catalog["contracts"]
        if item["reference"]["contract_kind"] == kind
        and item["reference"]["contract_id"] == contract_id
        and item["reference"]["contract_version"] == contract_version
    ]
    if len(matches) != 1:
        raise ValueError(
            f"missing exact {kind} contract: {contract_id}@{contract_version}"
        )
    return matches[0]


def _require_catalog_snapshot_matches_current(
    catalog: dict[str, Any],
    *,
    expected_catalog: Any,
    protocol_digest: str,
) -> None:
    """Bind a retained Catalog snapshot to the active public generation."""
    from protein_workbench_public import PUBLIC_PROTOCOL_NAMESPACE

    if (
        catalog.get("schema_namespace") != PUBLIC_PROTOCOL_NAMESPACE
        or catalog.get("protocol_digest") != protocol_digest
    ):
        raise ValueError(
            "installed Catalog snapshot uses the wrong protocol generation"
        )
    if catalog.get("catalog_contract_digest") != expected_catalog.contract_digest:
        raise ValueError("installed FrozenCatalog does not match clean source")
    if (
        catalog.get("contracts")
        != expected_catalog.catalog_descriptor()["contracts"]
    ):
        raise ValueError(
            "installed Catalog snapshot stable contracts do not match clean source"
        )


def _require_run_matches_compile(
    run: dict[str, Any],
    workflow_snapshot: dict[str, Any],
    compile_receipt: dict[str, Any],
) -> None:
    """Bind one retained Run projection to one exact Workflow compilation."""
    expected = (
        workflow_snapshot.get("workflow_revision"),
        workflow_snapshot.get("workflow_digest"),
        compile_receipt.get("compile_id"),
    )
    if (
        expected
        != (
            compile_receipt.get("workflow_revision"),
            compile_receipt.get("workflow_digest"),
            compile_receipt.get("compile_id"),
        )
        or expected
        != (
            run.get("workflow_revision"),
            run.get("workflow_digest"),
            run.get("compile_id"),
        )
    ):
        raise ValueError(
            "Run projection crossed Workflow/compile identity"
        )


def require_remote_engine_contracts(
    catalog: dict[str, Any],
    workflow: dict[str, Any],
    invocation_proof: dict[str, Any],
) -> None:
    """Reject readiness-only, direct-ESMC, fixture, or wrong-provider proof."""
    nodes = {node["node_id"]: node for node in workflow["nodes"]}
    if nodes["generate-paired"]["binding_id"] != (
        "esm3.generate_paired.biohub_medium"
    ) or nodes["generate-paired"]["binding_version"] != (
        REMOTE_CONTRACT_VERSION
    ):
        raise ValueError("canonical proof does not select remote ESM-3")
    if {
        (
            nodes[node_id]["binding_id"],
            nodes[node_id]["binding_version"],
        )
        for node_id in ("fold-sequences", "fold-final")
    } != {
        ("folding.fold.esmfold2_remote", REMOTE_CONTRACT_VERSION)
    }:
        raise ValueError("canonical proof does not select remote ESMFold2")

    proof_by_binding = {
        item["binding_id"]: item
        for item in invocation_proof.get("remote_bindings", [])
    }
    if set(proof_by_binding) != set(REMOTE_BINDINGS):
        raise ValueError("required remote invocation proof is incomplete")
    for binding_id, expected in REMOTE_BINDINGS.items():
        binding = _contract(
            catalog,
            "binding",
            binding_id,
            REMOTE_CONTRACT_VERSION,
        )
        method = _contract(
            catalog,
            "method",
            expected["method"],
            REMOTE_CONTRACT_VERSION,
        )
        descriptor = binding["descriptor"]
        implementation = descriptor["implementation_identity"]
        method_descriptor = method["descriptor"]
        method_digest = method["reference"]["contract_digest"]
        proof = proof_by_binding[binding_id]
        if set(proof["request_roles"]) != {
            item["engine_role"] for item in proof["invocations"]
        }:
            raise ValueError(
                f"request-role inventory is incomplete for {binding_id}"
            )
        if (
            descriptor["method"] != method["reference"]
            or descriptor["route_behavior"]["behavior_id"]
            != expected["adapter"]
            or implementation.get("model") != expected["model"]
            or method_descriptor["model_identity"]["source"]
            != expected["source"]
            or method_descriptor["source_identity"]["service"]
            != expected["source"]
            or proof["method_id"] != expected["method"]
            or proof["method_version"] != REMOTE_CONTRACT_VERSION
            or proof["binding_version"] != REMOTE_CONTRACT_VERSION
            or proof["adapter_id"] != expected["adapter"]
            or proof["adapter_version"] != REMOTE_CONTRACT_VERSION
            or proof["model"] != expected["model"]
            or proof["source"] != expected["source"]
            or not proof["invocations"]
        ):
            raise ValueError(f"wrong remote engine proof for {binding_id}")
        if any(
            invocation.get("engine_identity") != method_digest
            for invocation in proof["invocations"]
        ):
            raise ValueError(
                f"wrong exact Method Engine proof for {binding_id}"
            )
        if any(
            invocation.get("invocation_provenance")
            != _PROVIDER_UNCONTROLLED
            for invocation in proof["invocations"]
        ):
            raise ValueError(
                f"remote provider randomness proof is incomplete for {binding_id}"
            )
        forbidden = json.dumps(proof, sort_keys=True).lower()
        if (
            "esmc-600m" in forbidden
            or "fixture" in forbidden
            or "mock" in forbidden
        ):
            raise ValueError("direct ESMC or fixture evidence cannot prove ESM-3")

    esm3_invocations = proof_by_binding[
        "esm3.generate_paired.biohub_medium"
    ]["invocations"]
    sequence_parents = {
        item["invocation_id"]
        for item in esm3_invocations
        if item["engine_role"] == "sequence_parent"
        and item["terminal"]["status"] == "succeeded"
    }
    structure_children = [
        item
        for item in esm3_invocations
        if item["engine_role"] == "structure_child"
        and item["terminal"]["status"] == "succeeded"
        and item.get("parent_invocation_id") in sequence_parents
    ]
    if (
        len(sequence_parents) != 10
        or len(structure_children) != 10
        or Counter(
            item["parent_invocation_id"] for item in structure_children
        )
        != Counter({invocation_id: 1 for invocation_id in sequence_parents})
    ):
        raise ValueError(
            "ESM-3 paired request-role or parent-child proof is incomplete"
        )

    folds = proof_by_binding[
        "folding.fold.esmfold2_remote"
    ]["invocations"]
    folds_by_node = Counter(item["node_id"] for item in folds)
    expected_fold_roles = Counter({
        **{
            ("fold-sequences", f"fold_parent_{index}_sample_0"): 1
            for index in range(10)
        },
        **{
            ("fold-final", f"fold_parent_{index}_sample_0"): 1
            for index in range(15)
        },
    })
    if (
        folds_by_node != {"fold-sequences": 10, "fold-final": 15}
        or Counter(
            (item["node_id"], item["engine_role"]) for item in folds
        )
        != expected_fold_roles
        or any(
            item["terminal"]["status"] != "succeeded"
            or item.get("parent_invocation_id") is not None
            for item in folds
        )
    ):
        raise ValueError("ESMFold2 request-role or exact Engine proof is incomplete")

    proteinmpnn_node = nodes["design-children"]
    if (
        proteinmpnn_node["binding_id"] != PROTEINMPNN_BINDING_ID
        or proteinmpnn_node["binding_version"]
        != PROTEINMPNN_BINDING_VERSION
    ):
        raise ValueError("canonical proof does not select exact ProteinMPNN")
    proteinmpnn_binding = _contract(
        catalog,
        "binding",
        PROTEINMPNN_BINDING_ID,
        PROTEINMPNN_BINDING_VERSION,
    )
    proteinmpnn_method = _contract(
        catalog,
        "method",
        PROTEINMPNN_METHOD_ID,
        PROTEINMPNN_METHOD_VERSION,
    )
    proteinmpnn_descriptor = proteinmpnn_binding["descriptor"]
    proteinmpnn_method_descriptor = proteinmpnn_method["descriptor"]
    proteinmpnn_method_digest = proteinmpnn_method["reference"][
        "contract_digest"
    ]
    proteinmpnn = invocation_proof.get("proteinmpnn", {})
    proteinmpnn_invocations = proteinmpnn.get("invocations", [])

    def exact_proteinmpnn_invocation(item: dict[str, Any]) -> bool:
        provenance = item.get("invocation_provenance", {})
        randomness = provenance.get("effective_randomness", {})
        return (
            item.get("engine_identity") == proteinmpnn_method_digest
            and randomness.get("control") == "exact_seed"
            and type(randomness.get("effective_seed")) is int
            and "provider_residue_projection" in provenance
            and item["terminal"]["status"] == "succeeded"
            and item.get("parent_invocation_id") is None
        )

    if (
        proteinmpnn_descriptor["method"]
        != proteinmpnn_method["reference"]
        or proteinmpnn.get("binding_id") != PROTEINMPNN_BINDING_ID
        or proteinmpnn.get("binding_version")
        != PROTEINMPNN_BINDING_VERSION
        or proteinmpnn.get("method_id") != PROTEINMPNN_METHOD_ID
        or proteinmpnn.get("method_version")
        != PROTEINMPNN_METHOD_VERSION
        or proteinmpnn.get("adapter_id")
        != proteinmpnn_descriptor["route_behavior"]["behavior_id"]
        or proteinmpnn.get("adapter_version")
        != proteinmpnn_descriptor["route_behavior"]["behavior_version"]
        or proteinmpnn.get("source")
        != proteinmpnn_method_descriptor["model_identity"]["source"]
        or Counter(
            item["engine_role"] for item in proteinmpnn_invocations
        )
        != {
            "design_parent_0": 1,
            "design_parent_1": 1,
            "design_parent_2": 1,
        }
        or any(
            not exact_proteinmpnn_invocation(item)
            for item in proteinmpnn_invocations
        )
    ):
        raise ValueError("ProteinMPNN 3 x 5 Engine proof is incomplete")


def _event_payloads(
    run: dict[str, Any],
    messages: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not messages or any(
        message.get("project_id") != run.get("project_id")
        or message.get("run_id") != run.get("run_id")
        for message in messages
    ):
        raise ValueError("Run event envelope crossed Project/Run scope")
    return [
        message["event"]
        for message in messages
        if message["event"]["type"]
        not in {"replay_started", "replay_complete"}
    ]


def _validate_replay_boundary(
    run: dict[str, Any],
    messages: list[dict[str, Any]],
) -> None:
    """Require one full, terminal, scope-bound replay and exact final cursor."""
    _event_payloads(run, messages)
    if (
        len(messages) < 3
        or messages[0]["event"]["type"] != "replay_started"
        or messages[-1]["event"]["type"] != "replay_complete"
        or any(
            message["event"]["type"]
            in {"replay_started", "replay_complete"}
            for message in messages[1:-1]
        )
        or messages[0]["sequence"] != 0
        or "after_sequence" in messages[0]["event"]
    ):
        raise ValueError("Run evidence is not one complete replay")

    terminal_message = messages[-2]
    terminal_cursor = terminal_message["cursor"]
    terminal_sequence = terminal_message["sequence"]
    if (
        messages[0]["event"]["replay_through_cursor"]
        != terminal_cursor
        or messages[-1]["event"]["live_from_cursor"]
        != terminal_cursor
        or messages[-1]["cursor"] != terminal_cursor
        or messages[-1]["sequence"] != terminal_sequence
        or run.get("ledger_cursor") != terminal_cursor
        or run.get("terminal_sequence") != terminal_sequence
    ):
        raise ValueError("Run replay cursor does not close at the projection")


def _validate_run_admission(
    run: dict[str, Any],
    messages: list[dict[str, Any]],
    compile_receipt: dict[str, Any],
) -> None:
    """Bind the public Ledger admission to the retained exact compile."""
    _event_payloads(run, messages)
    events = tuple(
        (message["sequence"], message["event"])
        for message in messages
        if message["event"]["type"]
        not in {"replay_started", "replay_complete"}
    )
    admissions = tuple(
        (sequence, event)
        for sequence, event in events
        if event["type"] == "run_admitted"
    )
    starts = tuple(
        (sequence, event)
        for sequence, event in events
        if event["type"] == "run_started"
    )
    attempts = tuple(
        sequence
        for sequence, event in events
        if event["type"]
        in {
            "node_attempt_started",
            "operation_attempt_started",
            "engine_invocation_started",
        }
    )
    expected_identity = (
        run.get("workflow_revision"),
        run.get("compile_id"),
    )
    if (
        len(admissions) != 1
        or len(starts) != 1
        or (
            admissions[0][1].get("workflow_revision"),
            admissions[0][1].get("compile_id"),
        )
        != expected_identity
        or (
            compile_receipt.get("workflow_revision"),
            compile_receipt.get("compile_id"),
        )
        != expected_identity
        or admissions[0][0] >= starts[0][0]
        or any(sequence <= starts[0][0] for sequence in attempts)
    ):
        raise ValueError(
            "Run admission does not match the retained compile or event order"
        )


def _validate_run_closure(
    run: dict[str, Any],
    messages: list[dict[str, Any]],
    compile_receipt: dict[str, Any],
) -> None:
    _validate_replay_boundary(run, messages)
    _validate_run_admission(run, messages, compile_receipt)
    events = _event_payloads(run, messages)
    if not events or events[-1] != {
        "type": "run_terminal",
        "status": run["status"],
    }:
        raise ValueError("Run event replay and terminal projection disagree")
    sequence_values = [
        message["sequence"]
        for message in messages
        if message["event"]["type"]
        not in {"replay_started", "replay_complete"}
    ]
    if sequence_values != sorted(sequence_values) or len(
        sequence_values
    ) != len(set(sequence_values)):
        raise ValueError("Run replay sequence is not strictly ordered")

    starts_and_terminals = (
        ("node_attempt_started", "node_attempt_terminal", "node_attempt_id"),
        (
            "operation_attempt_started",
            "operation_attempt_terminal",
            "operation_attempt_id",
        ),
        (
            "engine_invocation_started",
            "engine_invocation_terminal",
            "invocation_id",
        ),
    )
    for start_type, terminal_type, identity in starts_and_terminals:
        starts = Counter(
            event[identity] for event in events if event["type"] == start_type
        )
        terminals = Counter(
            event[identity]
            for event in events
            if event["type"] == terminal_type
        )
        if starts != terminals or set(starts.values()) - {1}:
            raise ValueError(f"{start_type} does not have exact terminal closure")

    dispositions = {
        event["disposition"]["node_id"]: event["disposition"]
        for event in events
        if event["type"] == "node_disposition"
    }
    projected = {
        item["node_id"]: item for item in run["node_dispositions"]
    }
    if dispositions != projected:
        raise ValueError("Run dispositions do not agree with public replay")

    readiness_sequences = [
        message["sequence"]
        for message in messages
        if message["event"]["type"] == "readiness_attested"
    ]
    attempt_sequences = [
        message["sequence"]
        for message in messages
        if message["event"]["type"] == "node_attempt_started"
    ]
    if (
        not readiness_sequences
        or not attempt_sequences
        or max(readiness_sequences) >= min(attempt_sequences)
    ):
        raise ValueError("Readiness was not completed before Cache/attempt decisions")


def _verify_checksums(root: Path) -> None:
    checksum_path = root / "checksums.sha256"
    if checksum_path.is_symlink() or not checksum_path.is_file():
        raise ValueError("evidence bundle has no regular checksum inventory")
    recorded: dict[str, str] = {}
    for line in checksum_path.read_text(encoding="utf-8").splitlines():
        digest, separator, relative = line.partition("  ")
        if (
            separator != "  "
            or not re.fullmatch(r"[0-9a-f]{64}", digest)
            or relative in recorded
        ):
            raise ValueError("checksum inventory is malformed")
        recorded[relative] = digest
    actual_paths = {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file() and path != checksum_path
    }
    if set(recorded) != actual_paths:
        raise ValueError("checksum inventory does not cover the exact bundle")
    for relative, expected in recorded.items():
        path = root / relative
        if path.is_symlink() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError(f"evidence checksum mismatch: {relative}")


def write_checksums(root: Path) -> None:
    """Write an exact checksum inventory after every other bundle file."""
    lines = []
    checksum_path = root / "checksums.sha256"
    checksum_path.unlink(missing_ok=True)
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ValueError("evidence bundle cannot contain symbolic links")
        if path.is_file():
            lines.append(
                f"{hashlib.sha256(path.read_bytes()).hexdigest()}  "
                f"{path.relative_to(root).as_posix()}\n"
            )
            path.chmod(0o600)
    checksum_path.write_text("".join(lines), encoding="utf-8")
    checksum_path.chmod(0o600)


def validate_evidence_bundle(root: Path) -> dict[str, Any]:
    """Validate a complete public, source-bound, fresh remote evidence bundle."""
    if root.is_symlink() or not root.is_dir():
        raise ValueError("evidence bundle root is not a regular directory")
    available = {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file()
    }
    if not REQUIRED_FILES <= available:
        raise ValueError("evidence bundle is missing required public receipts")
    _verify_checksums(root)

    source = _load_json(root / "source-receipt.json")
    if (
        source.get("schema_namespace") != SCHEMA_NAMESPACE
        or source.get("source_dirty") is not False
        or not re.fullmatch(r"[0-9a-f]{40}", source.get("source_revision", ""))
        or source.get("installed_imports_outside_source") is not True
    ):
        raise ValueError("source or installed artifact receipt is not clean")
    for artifact in source.get("installed_artifacts", []):
        if (
            not _DIGEST_PATTERN.fullmatch(artifact.get("content_digest", ""))
            or type(artifact.get("size")) is not int
            or artifact["size"] <= 0
        ):
            raise ValueError("installed artifact identity is incomplete")
    if {item.get("kind") for item in source["installed_artifacts"]} != {
        "wheel",
        "sdist",
    }:
        raise ValueError("installed artifact receipt lacks wheel or sdist")

    from core import (
        build_discovered_frozen_catalog,
        compile_workflow,
        parse_workflow_document,
    )
    from protein_workbench_public import (
        bundle_bytes,
        bundle_digest,
        validate_event,
    )

    protocol = (root / "public-protocol.json").read_bytes()
    if protocol != bundle_bytes() or source["protocol_digest"] != bundle_digest():
        raise ValueError("installed public protocol does not match clean source")
    catalog = _load_json(root / "catalog-snapshot.json")
    expected_catalog = build_discovered_frozen_catalog()
    _require_catalog_snapshot_matches_current(
        catalog,
        expected_catalog=expected_catalog,
        protocol_digest=bundle_digest(),
    )
    if source["catalog_contract_digest"] != expected_catalog.contract_digest:
        raise ValueError("installed FrozenCatalog does not match clean source")

    snapshot = _load_json(root / "workflow-snapshot.json")
    workflow = snapshot["workflow"]
    expected_workflow_path = (
        Path(__file__).resolve().parent.parent
        / "examples"
        / "v2"
        / "canonical-3gb1.workflow.json"
    )
    expected_workflow = json.loads(expected_workflow_path.read_bytes())
    compile_receipt = _load_json(root / "compile-receipt.json")
    parsed_workflow = parse_workflow_document(workflow)
    expected_compile_receipt = compile_workflow(
        parsed_workflow,
        workflow_revision=snapshot["workflow_revision"],
        catalog=expected_catalog,
    ).public_receipt()
    if (
        workflow["schema_version"] != VERSION
        or workflow["workflow_id"] != PROJECT_ID
        or workflow != expected_workflow
        or source["workflow_content_digest"]
        != _sha256(expected_workflow_path.read_bytes())
        or not workflow["contract_lock"]
        or snapshot["workflow_digest"] != parsed_workflow.digest
        or compile_receipt != expected_compile_receipt
    ):
        raise ValueError("Workflow or compile receipt is not exact and accepted")

    run_index = _load_json(root / "run-index.json")
    run_ids = run_index.get("run_ids", [])
    if (
        not run_ids
        or run_index.get("successful_run_id") != run_ids[-1]
        or len(run_ids) != len(set(run_ids))
    ):
        raise ValueError("fresh Run and retry identity chain is incomplete")
    runs: list[dict[str, Any]] = []
    event_sets: list[list[dict[str, Any]]] = []
    for index, run_id in enumerate(run_ids):
        run = _load_json(root / "runs" / run_id / "projection.json")
        messages = _load_json(root / "runs" / run_id / "events.json")
        for message in messages:
            validate_event(message)
        if run["run_id"] != run_id or run["project_id"] != PROJECT_ID:
            raise ValueError("Run projection crossed Project/Run scope")
        _require_run_matches_compile(run, snapshot, compile_receipt)
        if index == 0:
            if "derived_from_run_id" in run:
                raise ValueError("fresh Run cannot claim a historical parent")
        elif run.get("derived_from_run_id") != run_ids[index - 1]:
            raise ValueError("provider retry is not a newly derived Run")
        _validate_run_closure(run, messages, compile_receipt)
        runs.append(run)
        event_sets.append(messages)
    if runs[-1]["status"] != "succeeded":
        raise ValueError("fresh remote canonical Run did not succeed")
    if any(run["status"] == "succeeded" for run in runs[:-1]):
        raise ValueError("a successful Run was retried without a provider failure")

    final = runs[-1]
    expected_nodes = {node["node_id"] for node in workflow["nodes"]}
    if (
        len(final["node_dispositions"]) != len(expected_nodes)
        or {item["node_id"] for item in final["node_dispositions"]}
        != expected_nodes
        or any(
            item["outcome"] != "succeeded"
            for item in final["node_dispositions"]
        )
    ):
        raise ValueError("not every canonical Plan Node has a success disposition")
    final_events = _event_payloads(final, event_sets[-1])
    passing = {
        event["binding"]["contract_id"]
        for event in final_events
        if event["type"] == "readiness_attested"
        and event["conclusion"] == "passing"
    }
    if not set(REMOTE_BINDINGS) <= passing:
        raise ValueError("current remote Binding readiness is not passing")

    proof = _load_json(root / "invocation-proof.json")
    require_invocation_proof_matches_ledger(
        proof,
        catalog,
        workflow,
        list(zip(runs, event_sets, strict=True)),
    )
    require_remote_engine_contracts(catalog, workflow, proof)
    lineage = _load_json(root / "candidate-lineage.json")
    if (
        lineage.get("paired_sequence_count") != 10
        or lineage.get("paired_structure_count") != 10
        or lineage.get("counterpart_count") != 10
        or lineage.get("selected_parent_count") != 3
        or lineage.get("children_per_parent") != [5, 5, 5]
        or lineage.get("final_fold_count") != 15
        or lineage.get("fixed_reference_count") != 1
        or lineage.get("paired_reference_count") != 10
        or lineage.get("fixed_subject_count") != 10
        or lineage.get("paired_subject_count") != 10
        or lineage.get("paired_lineage_complete") is not True
        or lineage.get("scope_isolated") is not True
        or lineage.get("weighted_objectives") != {
            "fixed-3gb1": 0.7,
            "paired-esm3": 0.3,
        }
        or lineage.get("track_fidelity") != {
            "residue_count": 71,
            "masked_sequence_positions": 35,
            "secondary_structure_symbols": 71,
            "visible_backbones": 46,
            "protein_prompt_content_digest": (
                CANONICAL_PROVIDER_PROMPT_CONTENT_DIGEST
            ),
            "sequence_track": CANONICAL_SEQUENCE_TRACK,
            "secondary_structure_track": (
                CANONICAL_SECONDARY_STRUCTURE_TRACK
            ),
            "structure_visibility_track": (
                CANONICAL_STRUCTURE_VISIBILITY_TRACK
            ),
        }
    ):
        raise ValueError("canonical scientific lineage assertions are incomplete")

    artifacts = _load_json(root / "artifact-index.json")
    if len(artifacts) != 15:
        raise ValueError("canonical run must retain fifteen final PDB artifacts")
    projected_artifacts = {
        item["artifact_reference"]: item
        for item in final["artifact_index"]
    }
    public_artifact_fields = {
        "artifact_reference",
        "artifact_kind",
        "candidate_id",
        "node_id",
        "output_port",
        "media_type",
        "size",
        "content_digest",
    }
    for artifact in artifacts:
        path = root / artifact["bundle_path"]
        payload = path.read_bytes()
        public_descriptor = {
            key: artifact[key]
            for key in public_artifact_fields
            if key in artifact
        }
        if (
            path.is_symlink()
            or artifact["project_id"] != PROJECT_ID
            or artifact["run_id"] != final["run_id"]
            or projected_artifacts.get(artifact["artifact_reference"])
            != public_descriptor
            or artifact["artifact_kind"] != "candidate"
            or artifact["node_id"] != "export-final"
            or artifact["output_port"] != "candidate_artifacts"
            or artifact["media_type"] not in {
                "chemical/x-pdb",
                "text/plain",
            }
            or artifact["size"] != len(payload)
            or artifact["content_digest"] != _sha256(payload)
            or not artifact["candidate_id"]
            or not artifact["output_port"]
            or artifact["candidate_id"]
            not in set(lineage["final_fold_candidate_ids"])
            or artifact["retrieved_headers"]["content-length"]
            != str(artifact["size"])
            or artifact["retrieved_headers"]["content-type"]
            != artifact["media_type"]
            or artifact["retrieved_headers"]["digest"]
            != artifact["content_digest"]
        ):
            raise ValueError("artifact scope, association, media, size, or bytes fail")
    if {item["candidate_id"] for item in artifacts} != set(
        lineage["final_fold_candidate_ids"]
    ):
        raise ValueError("artifact Candidate association is not one-to-one")
    verification = _load_json(root / "verification.json")
    if (
        verification.get("schema_namespace") != SCHEMA_NAMESPACE
        or verification.get("passed") is not True
        or verification.get("historical_v1_allowed") is not False
        or verification.get("mock_or_fixture_allowed") is not False
        or verification.get("skip_allowed") is not False
        or verification.get("readiness_only_allowed") is not False
        or verification.get("cache_only_allowed") is not False
        or verification.get("direct_esmc_substitutes_for_esm3") is not False
    ):
        raise ValueError("verification result permits a forbidden substitute")
    return {
        "source_revision": source["source_revision"],
        "successful_run_id": final["run_id"],
        "run_count": len(runs),
        "artifact_count": len(artifacts),
    }


def _decode_output(
    catalog: Any,
    projection: dict[str, Any],
    node_id: str,
    output_port: str,
) -> Any:
    values = _decode_output_values(
        catalog,
        projection,
        node_id,
        output_port,
    )
    if len(values) != 1:
        raise ValueError(
            f"{node_id}.{output_port} must contain exactly one value"
        )
    return values[0]


def _decode_output_values(
    catalog: Any,
    projection: dict[str, Any],
    node_id: str,
    output_port: str,
) -> tuple[Any, ...]:
    from core.port_types import PORT_VALUE_NAMESPACE, canonical_json_bytes

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
    values = output.get("values")
    if not isinstance(values, list) or not values:
        raise ValueError(f"{node_id}.{output_port} has no public values")
    return tuple(
        codec.decode(
            canonical_json_bytes({
                "schema_namespace": PORT_VALUE_NAMESPACE,
                "port_type_id": reference["contract_id"],
                "port_type_version": reference["contract_version"],
                "value": value,
            })
        )
        for value in values
    )


def _collect_events(client: Any, run_id: str) -> list[dict[str, Any]]:
    from starlette.websockets import WebSocketDisconnect

    messages: list[dict[str, Any]] = []
    with client.websocket_connect(
        f"/api/v2/projects/{PROJECT_ID}/runs/{run_id}/events"
    ) as websocket:
        try:
            while True:
                messages.append(websocket.receive_json())
        except WebSocketDisconnect as closed:
            if closed.code != 1000:
                raise
    return messages


def _wait_terminal(
    client: Any,
    run_id: str,
    *,
    timeout_seconds: float,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        response = client.get(
            f"/api/v2/projects/{PROJECT_ID}/runs/{run_id}"
        )
        response.raise_for_status()
        projection = response.json()
        if projection["status"] in {
            "succeeded",
            "failed",
            "cancelled",
            "interrupted",
        }:
            return projection
        time.sleep(0.2)
    raise TimeoutError("fresh remote canonical Run did not reach terminal state")


def _invocation_proof(
    catalog_snapshot: dict[str, Any],
    workflow: dict[str, Any],
    run_records: list[tuple[dict[str, Any], list[dict[str, Any]]]],
) -> dict[str, Any]:
    workflow_nodes = {node["node_id"]: node for node in workflow["nodes"]}
    required_live_nodes = {
        "generate-paired",
        "fold-sequences",
        "fold-final",
        "design-children",
    }
    selected_events: dict[str, tuple[str, list[dict[str, Any]]]] = {}
    for projection, messages in reversed(run_records):
        dispositions = {
            item["node_id"]: item for item in projection["node_dispositions"]
        }
        events = _event_payloads(projection, messages)
        for node_id in sorted(required_live_nodes - set(selected_events)):
            disposition = dispositions.get(node_id)
            if (
                disposition is not None
                and disposition["outcome"] == "succeeded"
                and disposition.get("resolution") == "executed"
            ):
                selected_events[node_id] = (projection["run_id"], events)
    if set(selected_events) != required_live_nodes:
        raise ValueError("Cache replay cannot replace required live Engine proof")

    invocation_records: list[dict[str, Any]] = []
    for selected_node in sorted(selected_events):
        run_id, events = selected_events[selected_node]
        node_by_attempt = {
            event["node_attempt_id"]: event["node_id"]
            for event in events
            if event["type"] == "node_attempt_started"
        }
        node_by_operation = {
            event["operation_attempt_id"]: node_by_attempt[
                event["node_attempt_id"]
            ]
            for event in events
            if event["type"] == "operation_attempt_started"
        }
        terminal_by_invocation = {
            event["invocation_id"]: event
            for event in events
            if event["type"] == "engine_invocation_terminal"
        }
        invocation_records.extend(
            {
                **event,
                "node_id": selected_node,
                "run_id": run_id,
                "terminal": terminal_by_invocation[event["invocation_id"]],
            }
            for event in events
            if event["type"] == "engine_invocation_started"
            and node_by_operation[event["operation_attempt_id"]]
            == selected_node
        )

    result: list[dict[str, Any]] = []
    for binding_id, expected in REMOTE_BINDINGS.items():
        binding_nodes = {
            node_id
            for node_id, node in workflow_nodes.items()
            if node["binding_id"] == binding_id
        }
        invocations = [
            event
            for event in invocation_records
            if event["node_id"] in binding_nodes
        ]
        result.append({
            "binding_id": binding_id,
            "binding_version": REMOTE_CONTRACT_VERSION,
            "method_id": expected["method"],
            "method_version": REMOTE_CONTRACT_VERSION,
            "adapter_id": expected["adapter"],
            "adapter_version": REMOTE_CONTRACT_VERSION,
            "model": expected["model"],
            "source": expected["source"],
            "request_roles": sorted({
                invocation["engine_role"] for invocation in invocations
            }),
            "invocations": invocations,
        })
    proteinmpnn_invocations = [
        event
        for event in invocation_records
        if event["node_id"] == "design-children"
    ]
    proteinmpnn_binding = _contract(
        catalog_snapshot,
        "binding",
        PROTEINMPNN_BINDING_ID,
        PROTEINMPNN_BINDING_VERSION,
    )
    proteinmpnn_method = _contract(
        catalog_snapshot,
        "method",
        PROTEINMPNN_METHOD_ID,
        PROTEINMPNN_METHOD_VERSION,
    )
    return {
        "schema_namespace": SCHEMA_NAMESPACE,
        "catalog_contract_digest": catalog_snapshot[
            "catalog_contract_digest"
        ],
        "remote_bindings": result,
        "proteinmpnn": {
            "binding_id": PROTEINMPNN_BINDING_ID,
            "binding_version": PROTEINMPNN_BINDING_VERSION,
            "method_id": PROTEINMPNN_METHOD_ID,
            "method_version": PROTEINMPNN_METHOD_VERSION,
            "adapter_id": proteinmpnn_binding["descriptor"][
                "route_behavior"
            ]["behavior_id"],
            "adapter_version": proteinmpnn_binding["descriptor"][
                "route_behavior"
            ]["behavior_version"],
            "source": proteinmpnn_method["descriptor"]["model_identity"][
                "source"
            ],
            "invocations": proteinmpnn_invocations,
        },
    }


def require_invocation_proof_matches_ledger(
    proof: dict[str, Any],
    catalog_snapshot: dict[str, Any],
    workflow: dict[str, Any],
    run_records: list[tuple[dict[str, Any], list[dict[str, Any]]]],
) -> None:
    reconstructed = _invocation_proof(
        catalog_snapshot,
        workflow,
        run_records,
    )
    if proof != reconstructed:
        raise ValueError("Invocation proof does not match retained Run Ledger")


def _candidate_lineage(catalog: Any, projection: dict[str, Any]) -> dict[str, Any]:
    from collections import Counter as RuntimeCounter
    import torch

    paired_sequences = _decode_output(
        catalog, projection, "generate-paired", "sequence_candidates"
    )
    paired_structures = _decode_output(
        catalog, projection, "generate-paired", "structure_candidates"
    )
    counterparts = _decode_output(
        catalog, projection, "generate-paired", "counterpart_pairs"
    )
    prompt = _decode_output(
        catalog,
        projection,
        "override-secondary-structure",
        "protein_prompt",
    )
    fixed_alignments = _decode_output_values(
        catalog, projection, "align-fixed", "alignments"
    )
    paired_alignments = _decode_output_values(
        catalog, projection, "align-paired", "alignments"
    )
    ranked = _decode_output(
        catalog, projection, "rank-candidates", "candidates"
    )
    selected = _decode_output(
        catalog, projection, "take-top-three", "candidates"
    )
    children = _decode_output(
        catalog, projection, "design-children", "sequence_candidates"
    )
    final_folds = _decode_output(
        catalog, projection, "fold-final", "structure_candidates"
    )
    selection = projection["selection_results"][0]
    prompt_output = next(
        item
        for item in projection["outputs"]
        if item["node_id"] == "override-secondary-structure"
        and item["output_port"] == "protein_prompt"
    )
    child_counts = RuntimeCounter(
        child.parent_ids[0] for child in children.items
    )
    selected_ids = {
        candidate.candidate_id for candidate in selected.items
    }
    if child_counts != RuntimeCounter({
        candidate_id: 5 for candidate_id in selected_ids
    }):
        raise ValueError(
            "ProteinMPNN children are not exactly five per selected parent"
        )
    fixed_references = {
        alignment.reference.candidate_id
        for alignment in fixed_alignments
    }
    paired_references = {
        alignment.reference.candidate_id
        for alignment in paired_alignments
    }
    paired_subjects = {
        alignment.subject.candidate_id
        for alignment in paired_alignments
    }
    fixed_subjects = {
        alignment.subject.candidate_id
        for alignment in fixed_alignments
    }
    pairing_pairs = {
        (entry.subject_candidate_id, entry.reference_candidate_id)
        for entry in counterparts.entries
    }
    structure_values = prompt.structure_track.values
    visible = prompt.structure_visibility_track.values
    visible_backbones = sum(
        bool(is_visible)
        and value is not None
        and all(
            atom in value
            and all(
                isinstance(coordinate, (int, float))
                and torch.isfinite(torch.tensor(coordinate))
                for coordinate in value[atom]
            )
            for atom in ("N", "CA", "C")
        )
        for value, is_visible in zip(structure_values, visible, strict=True)
    )
    if selected.items != ranked.items[:3]:
        raise ValueError("weighted selection did not feed the top three")
    if [
        folded.parent_ids for folded in final_folds.items
    ] != [(child.candidate_id,) for child in children.items]:
        raise ValueError("final fold lineage is incomplete")
    return {
        "schema_namespace": SCHEMA_NAMESPACE,
        "paired_sequence_count": len(paired_sequences.items),
        "paired_structure_count": len(paired_structures.items),
        "counterpart_count": len(counterparts.entries),
        "paired_candidate_ids": [
            {
                "sequence_candidate_id": sequence.candidate_id,
                "structure_candidate_id": structure.candidate_id,
                "structure_parent_ids": structure.parent_ids,
            }
            for sequence, structure in zip(
                paired_sequences.items,
                paired_structures.items,
                strict=True,
            )
        ],
        "fixed_reference_count": len(fixed_references),
        "paired_reference_count": len(paired_references),
        "fixed_subject_count": len(fixed_subjects),
        "paired_subject_count": len(paired_subjects),
        "paired_lineage_complete": pairing_pairs == {
            (sequence.candidate_id, structure.candidate_id)
            for sequence, structure in zip(
                paired_sequences.items,
                paired_structures.items,
                strict=True,
            )
        },
        "scope_isolated": fixed_references.isdisjoint(paired_references),
        "ranked_candidate_ids": [
            candidate.candidate_id for candidate in ranked.items
        ],
        "selected_candidate_ids": [
            candidate.candidate_id for candidate in selected.items
        ],
        "selected_parent_count": len(selected.items),
        "children_per_parent": sorted(child_counts.values()),
        "child_lineage": [
            {
                "candidate_id": child.candidate_id,
                "parent_ids": child.parent_ids,
            }
            for child in children.items
        ],
        "final_fold_count": len(final_folds.items),
        "final_fold_candidate_ids": [
            folded.candidate_id for folded in final_folds.items
        ],
        "final_fold_lineage": [
            {
                "candidate_id": folded.candidate_id,
                "parent_ids": folded.parent_ids,
            }
            for folded in final_folds.items
        ],
        "weighted_objectives": {
            item["objective_id"]: item["declared_weight"]
            for item in selection["objectives"]
        },
        "track_fidelity": {
            "residue_count": prompt.num_residues,
            "masked_sequence_positions": sum(
                value is None for value in prompt.sequence_track.values
            ),
            "secondary_structure_symbols": len(
                prompt.secondary_structure_track.values
            ),
            "visible_backbones": visible_backbones,
            "protein_prompt_content_digest": prompt_output[
                "content_digest"
            ],
            "sequence_track": "".join(
                value if value is not None else "_"
                for value in prompt.sequence_track.values
            ),
            "secondary_structure_track": "".join(
                value if value is not None else "_"
                for value in prompt.secondary_structure_track.values
            ),
            "structure_visibility_track": "".join(
                "1" if value else "0"
                for value in prompt.structure_visibility_track.values
            ),
        },
    }


def _verification_receipt(
    *,
    passed: bool,
    public_projection_run_id: str | None = None,
) -> dict[str, Any]:
    receipt: dict[str, Any] = {
        "schema_namespace": SCHEMA_NAMESPACE,
        "passed": passed,
        "historical_v1_allowed": False,
        "mock_or_fixture_allowed": False,
        "skip_allowed": False,
        "readiness_only_allowed": False,
        "cache_only_allowed": False,
        "direct_esmc_substitutes_for_esm3": False,
    }
    if public_projection_run_id is not None:
        receipt["public_projection_run_id"] = public_projection_run_id
    return receipt


def _assert_bundle_redacted(root: Path, forbidden: tuple[bytes, ...]) -> None:
    for path in root.rglob("*"):
        if path.is_symlink():
            raise ValueError("evidence bundle cannot contain symbolic links")
        if path.is_file():
            payload = path.read_bytes()
            if any(value and value in payload for value in forbidden):
                raise ValueError("private credential or runtime path reached evidence")


def _retrieve_artifacts(
    client: Any,
    root: Path,
    projection: dict[str, Any],
) -> list[dict[str, Any]]:
    from protein_workbench_public import validate_artifact_response

    artifacts: list[dict[str, Any]] = []
    for artifact in projection["artifact_index"]:
        response = client.get(
            f"/api/v2/projects/{PROJECT_ID}/runs/"
            f"{projection['run_id']}/artifacts/"
            f"{artifact['artifact_reference']}"
        )
        response.raise_for_status()
        validate_artifact_response(
            {
                "artifact": artifact,
                "content_disposition": response.headers[
                    "content-disposition"
                ],
            },
            response.headers,
            response.content,
        )
        bundle_path = (
            Path("artifacts") / f"{artifact['artifact_reference']}.pdb"
        )
        output = root / bundle_path
        output.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        output.write_bytes(response.content)
        output.chmod(0o600)
        artifacts.append({
            **artifact,
            "project_id": PROJECT_ID,
            "run_id": projection["run_id"],
            "bundle_path": bundle_path.as_posix(),
            "retrieved_headers": {
                "content-disposition": response.headers[
                    "content-disposition"
                ],
                "content-length": response.headers["content-length"],
                "content-type": response.headers["content-type"],
                "digest": response.headers["digest"],
            },
        })
    return artifacts


def installed_main() -> int:
    """Run the installed backend and write only safe public evidence."""
    from fastapi.testclient import TestClient
    from core import build_discovered_frozen_catalog
    from core.server import create_app
    from esm.sdk.forge import (
        ESM3ForgeInferenceClient,
        SequenceStructureForgeInferenceClient,
    )
    from modules.folding.adapter import REMOTE_ESMFOLD2_MODEL
    from modules.provider_contract import read_biohub_token
    from modules.proteinmpnn.adapter import (
        configured_runtime_fingerprint,
    )
    from protein_workbench_public import bundle_bytes, bundle_digest

    root = Path(os.environ["PROTEIN_WORKBENCH_FRESH_EVIDENCE_STAGING"])
    source_root = Path(os.environ["PW_SOURCE_ROOT"]).resolve()
    for package_name in (
        "core",
        "datatypes",
        "examples",
        "modules",
        "pdbs",
        "protein_workbench_public",
    ):
        package = sys.modules.get(package_name) or __import__(package_name)
        if Path(package.__file__).resolve().is_relative_to(source_root):
            raise RuntimeError("installed backend imported from source checkout")

    token = read_biohub_token()

    def esm3_factory(
        *,
        model_name: str,
        endpoint_id: str,
        credential_handle: str,
    ) -> Any:
        if endpoint_id != "biohub" or credential_handle != token:
            raise RuntimeError("remote ESM-3 environment identity changed")
        return ESM3ForgeInferenceClient(
            model=model_name,
            token=credential_handle,
            request_timeout=180,
            max_retry_attempts=1,
        )

    def folding_factory(
        *,
        model_name: str,
        endpoint_id: str,
        credential_handle: str,
    ) -> Any:
        if (
            endpoint_id != "biohub"
            or credential_handle != token
            or model_name != REMOTE_ESMFOLD2_MODEL
        ):
            raise RuntimeError("remote ESMFold2 environment identity changed")
        return SequenceStructureForgeInferenceClient(
            model=model_name,
            token=credential_handle,
            request_timeout=240,
            max_retry_attempts=1,
        )

    proteinmpnn_root = Path(
        os.environ["PROTEIN_WORKBENCH_PROTEINMPNN_ROOT"]
    ).resolve()
    proteinmpnn_fingerprint = configured_runtime_fingerprint()
    environment = {
        (
            "esm3.generate_paired.biohub_medium",
            REMOTE_CONTRACT_VERSION,
        ): {
            "values": {
                "endpoint_id": "biohub",
                "credential_handle": token,
                "client_factory": esm3_factory,
            },
            "safe_fingerprint": "biohub-esm3-medium-2024-08",
            "invalidation_token": "biohub-esm3-medium-2024-08",
        },
        ("folding.fold.esmfold2_remote", REMOTE_CONTRACT_VERSION): {
            "values": {
                "endpoint_id": "biohub",
                "credential_handle": token,
                "client_factory": folding_factory,
            },
            "safe_fingerprint": "biohub-esmfold2-fast-2026-05",
            "invalidation_token": "biohub-esmfold2-fast-2026-05",
        },
        ("proteinmpnn.design.local", PROTEINMPNN_BINDING_VERSION): {
            "values": {
                "device": "cpu",
                "provider_root": proteinmpnn_root,
                "resolved_runtime_fingerprint": proteinmpnn_fingerprint,
            },
            "safe_fingerprint": proteinmpnn_fingerprint,
            "invalidation_token": proteinmpnn_fingerprint,
        },
    }
    catalog = build_discovered_frozen_catalog()
    app = create_app(v2_environment_configuration=environment)

    with TestClient(app) as client:
        protocol_response = client.get("/api/v2/protocol")
        protocol_response.raise_for_status()
        if (
            protocol_response.content != bundle_bytes()
            or protocol_response.headers["Digest"] != bundle_digest()
        ):
            raise RuntimeError("installed protocol bytes are not exact")
        (root / "public-protocol.json").write_bytes(
            protocol_response.content
        )
        (root / "public-protocol.json").chmod(0o600)

        catalog_response = client.get("/api/v2/catalog")
        catalog_response.raise_for_status()
        catalog_snapshot = catalog_response.json()
        _write_json(root / "catalog-snapshot.json", catalog_snapshot)
        workflow_response = client.get(
            f"/api/v2/projects/{PROJECT_ID}/workflow"
        )
        workflow_response.raise_for_status()
        workflow_snapshot = workflow_response.json()
        _write_json(root / "workflow-snapshot.json", workflow_snapshot)
        compile_response = client.post(
            f"/api/v2/projects/{PROJECT_ID}/workflow:compile",
            json={
                "workflow_revision": workflow_snapshot[
                    "workflow_revision"
                ],
                "workflow": workflow_snapshot["workflow"],
            },
        )
        compile_response.raise_for_status()
        compile_receipt = compile_response.json()
        _write_json(root / "compile-receipt.json", compile_receipt)
        if not compile_receipt["accepted"]:
            raise RuntimeError("canonical v2 Workflow did not compile")

        run_ids: list[str] = []
        projections: list[dict[str, Any]] = []
        events_by_run: list[list[dict[str, Any]]] = []
        started = client.post(
            f"/api/v2/projects/{PROJECT_ID}/runs",
            json={
                "workflow_revision": workflow_snapshot[
                    "workflow_revision"
                ],
                "compile_id": compile_receipt["compile_id"],
                "client_request_id": "fresh-remote-3gb1-0",
            },
        )
        started.raise_for_status()
        run_id = started.json()["run_id"]
        for retry_index in range(4):
            projection = _wait_terminal(
                client,
                run_id,
                timeout_seconds=75 * 60,
            )
            events = _collect_events(client, run_id)
            run_ids.append(run_id)
            projections.append(projection)
            events_by_run.append(events)
            _write_json(
                root / "runs" / run_id / "projection.json",
                projection,
            )
            _write_json(root / "runs" / run_id / "events.json", events)
            if projection["status"] == "succeeded":
                break
            failed_nodes = [
                disposition["node_id"]
                for disposition in projection["node_dispositions"]
                if disposition["outcome"] == "failed"
            ]
            if not failed_nodes or retry_index == 3:
                break
            time.sleep(5 * (retry_index + 1))
            derived = client.post(
                f"/api/v2/projects/{PROJECT_ID}/runs:derive",
                json={
                    "source_run_id": run_id,
                    "compile_id": compile_receipt["compile_id"],
                    "policy": "retry_failed",
                    "node_ids": failed_nodes,
                    "client_request_id": (
                        f"fresh-remote-3gb1-derived-{retry_index + 1}"
                    ),
                },
            )
            derived.raise_for_status()
            run_id = derived.json()["run_id"]

        successful = projections[-1]
        _write_json(root / "run-index.json", {
            "schema_namespace": SCHEMA_NAMESPACE,
            "run_ids": run_ids,
            "successful_run_id": (
                successful["run_id"]
                if successful["status"] == "succeeded"
                else None
            ),
            "retry_policy": "new-derived-run-retry_failed",
            "sdk_hidden_retry_attempts": 1,
        })
        if successful["status"] != "succeeded":
            _write_json(
                root / "verification.json",
                _verification_receipt(passed=False),
            )
            _assert_bundle_redacted(
                root,
                (
                    token.encode(),
                    str(source_root).encode(),
                    str(proteinmpnn_root).encode(),
                ),
            )
            write_checksums(root)
            return 1

        lineage = _candidate_lineage(catalog, successful)
        _write_json(root / "candidate-lineage.json", lineage)
        invocation_proof = _invocation_proof(
            catalog_snapshot,
            workflow_snapshot["workflow"],
            list(zip(projections, events_by_run, strict=True)),
        )
        _write_json(root / "invocation-proof.json", invocation_proof)

        artifacts = _retrieve_artifacts(client, root, successful)
        _write_json(root / "artifact-index.json", artifacts)
        _write_json(
            root / "verification.json",
            _verification_receipt(
                passed=True,
                public_projection_run_id=successful["run_id"],
            ),
        )
        _assert_bundle_redacted(
            root,
            (
                token.encode(),
                str(source_root).encode(),
                str(proteinmpnn_root).encode(),
            ),
        )
        write_checksums(root)
    return 0


if __name__ == "__main__":
    raise SystemExit(installed_main())
