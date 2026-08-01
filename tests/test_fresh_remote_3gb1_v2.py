"""Fresh installed remote canonical 3GB1 evidence through public v2 seams.

The pre-agreed seams are the source-bound verification tier, the installed
backend public protocol, and the retained evidence-bundle validator.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
from typing import Any

import pytest

from core import build_discovered_frozen_catalog
from modules.provider_contract import validate_biohub_token_file
from protein_workbench_public import bundle_digest
from scripts.fresh_remote_3gb1 import (
    PROJECT_ID,
    PROTEINMPNN_BINDING_ID,
    PROTEINMPNN_BINDING_VERSION,
    PROTEINMPNN_METHOD_ID,
    PROTEINMPNN_METHOD_VERSION,
    REMOTE_BINDINGS,
    REMOTE_CONTRACT_VERSION,
    SCHEMA_NAMESPACE,
    _decode_output,
    _decode_output_values,
    _event_payloads,
    _invocation_proof,
    _require_catalog_snapshot_matches_current,
    _require_run_matches_compile,
    _validate_run_admission,
    _validate_replay_boundary,
    require_invocation_proof_matches_ledger,
    require_remote_engine_contracts,
    validate_evidence_bundle,
)
from tests.test_installed_backend_v2 import (
    InstalledArtifact,
    installed_artifact,
)


PROJECT_ROOT = Path(__file__).resolve().parent.parent
WORKFLOW_PATH = (
    PROJECT_ROOT / "examples" / "v2" / "canonical-3gb1.workflow.json"
)


class _EchoPortType:
    def decode(self, payload: bytes) -> object:
        return json.loads(payload)["value"]


class _EchoCatalog:
    def require_port_type(
        self,
        contract_id: str,
        contract_version: str,
    ) -> _EchoPortType:
        assert contract_id == "structure_comparison.alignment"
        assert contract_version == "2.1.0"
        return _EchoPortType()


def test_decode_output_values_preserves_every_many_port_value() -> None:
    projection = {
        "outputs": [{
            "node_id": "align-fixed",
            "output_port": "alignments",
            "port_type": {
                "contract_id": "structure_comparison.alignment",
                "contract_version": "2.1.0",
            },
            "values": [{"alignment": 1}, {"alignment": 2}],
        }]
    }

    assert _decode_output_values(
        _EchoCatalog(),
        projection,
        "align-fixed",
        "alignments",
    ) == ({"alignment": 1}, {"alignment": 2})
    with pytest.raises(ValueError, match="exactly one value"):
        _decode_output(
            _EchoCatalog(),
            projection,
            "align-fixed",
            "alignments",
        )


def _digest(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _catalog_snapshot() -> dict[str, object]:
    return build_discovered_frozen_catalog().public_snapshot(
        protocol_digest=bundle_digest()
    )


def _method_digest(
    catalog: dict[str, object],
    method_id: str,
    method_version: str,
) -> str:
    method = next(
        item
        for item in catalog["contracts"]
        if item["reference"]["contract_kind"] == "method"
        and item["reference"]["contract_id"] == method_id
        and item["reference"]["contract_version"]
        == method_version
    )
    return method["reference"]["contract_digest"]


def _exact_invocation_proof() -> dict[str, object]:
    catalog = _catalog_snapshot()
    esm3_method_digest = _method_digest(
        catalog,
        "esm3.generate_paired.esm3_medium_2024_08",
        REMOTE_CONTRACT_VERSION,
    )
    folding_method_digest = _method_digest(
        catalog,
        "folding.fold.esmfold2_fast_biohub_2026_05",
        REMOTE_CONTRACT_VERSION,
    )
    proteinmpnn_method_digest = _method_digest(
        catalog,
        PROTEINMPNN_METHOD_ID,
        PROTEINMPNN_METHOD_VERSION,
    )
    provider_uncontrolled = {
        "effective_randomness": {
            "control": "provider_uncontrolled",
        }
    }
    sequence_invocations = [
        {
            "invocation_id": f"invocation-esm3-sequence-{index}",
            "engine_role": "sequence_parent",
            "engine_identity": esm3_method_digest,
            "invocation_provenance": provider_uncontrolled,
            "node_id": "generate-paired",
            "terminal": {"status": "succeeded"},
        }
        for index in range(10)
    ]
    structure_invocations = [
        {
            "invocation_id": f"invocation-esm3-structure-{index}",
            "parent_invocation_id": (
                f"invocation-esm3-sequence-{index}"
            ),
            "engine_role": "structure_child",
            "engine_identity": esm3_method_digest,
            "invocation_provenance": provider_uncontrolled,
            "node_id": "generate-paired",
            "terminal": {"status": "succeeded"},
        }
        for index in range(10)
    ]
    folding_invocations = [
        {
            "invocation_id": f"invocation-fold-{node_id}-{index}",
            "engine_role": f"fold_parent_{index}_sample_0",
            "engine_identity": folding_method_digest,
            "invocation_provenance": provider_uncontrolled,
            "node_id": node_id,
            "terminal": {"status": "succeeded"},
        }
        for node_id, count in (
            ("fold-sequences", 10),
            ("fold-final", 15),
        )
        for index in range(count)
    ]
    return {
        "schema_namespace": SCHEMA_NAMESPACE,
        "catalog_contract_digest": catalog["catalog_contract_digest"],
        "remote_bindings": [
            {
                "binding_id": binding_id,
                "binding_version": REMOTE_CONTRACT_VERSION,
                "method_id": expected["method"],
                "method_version": REMOTE_CONTRACT_VERSION,
                "adapter_id": expected["adapter"],
                "adapter_version": REMOTE_CONTRACT_VERSION,
                "model": expected["model"],
                "source": expected["source"],
                "request_roles": (
                    ["sequence_parent", "structure_child"]
                    if binding_id
                    == "esm3.generate_paired.biohub_medium"
                    else [
                        f"fold_parent_{item}_sample_0"
                        for item in range(15)
                    ]
                ),
                "invocations": (
                    sequence_invocations + structure_invocations
                    if binding_id
                    == "esm3.generate_paired.biohub_medium"
                    else folding_invocations
                ),
            }
            for binding_id, expected in REMOTE_BINDINGS.items()
        ],
        "proteinmpnn": {
            "binding_id": PROTEINMPNN_BINDING_ID,
            "binding_version": PROTEINMPNN_BINDING_VERSION,
            "method_id": PROTEINMPNN_METHOD_ID,
            "method_version": PROTEINMPNN_METHOD_VERSION,
            "adapter_id": "proteinmpnn.local/adapter",
            "adapter_version": PROTEINMPNN_BINDING_VERSION,
            "source": "dauparas/ProteinMPNN",
            "invocations": [
                {
                    "invocation_id": f"invocation-mpnn-{index}",
                    "engine_role": f"design_parent_{index}",
                    "engine_identity": proteinmpnn_method_digest,
                    "invocation_provenance": {
                        "effective_randomness": {
                            "control": "exact_seed",
                            "effective_seed": 17 + index,
                        },
                        "provider_residue_projection": {
                            "position_semantics": "one_based_chain_local",
                            "workbench_chain_order": ["A"],
                            "provider_chain_order": ["A"],
                            "entries": [
                                {
                                    "residue_id": "A:1",
                                    "provider_chain_id": "A",
                                    "provider_position": 1,
                                }
                            ],
                        },
                    },
                    "terminal": {"status": "succeeded"},
                }
                for index in range(3)
            ],
        },
    }


def test_remote_engine_contract_rejects_direct_esmc_as_esm3_proof() -> None:
    proof = _exact_invocation_proof()
    esm3 = next(
        item
        for item in proof["remote_bindings"]
        if item["binding_id"] == "esm3.generate_paired.biohub_medium"
    )
    esm3["model"] = "esmc-600m-2024-12"
    workflow = json.loads(WORKFLOW_PATH.read_text(encoding="utf-8"))

    with pytest.raises(ValueError, match="wrong remote engine proof"):
        require_remote_engine_contracts(
            _catalog_snapshot(),
            workflow,
            proof,
        )


def test_remote_engine_contract_accepts_only_exact_esm3_and_esmfold2() -> None:
    require_remote_engine_contracts(
        _catalog_snapshot(),
        json.loads(WORKFLOW_PATH.read_text(encoding="utf-8")),
        _exact_invocation_proof(),
    )


def test_remote_engine_contract_rejects_reused_esm3_parent_invocation() -> None:
    proof = _exact_invocation_proof()
    esm3 = next(
        item
        for item in proof["remote_bindings"]
        if item["binding_id"] == "esm3.generate_paired.biohub_medium"
    )
    first_parent = next(
        item["invocation_id"]
        for item in esm3["invocations"]
        if item["engine_role"] == "sequence_parent"
    )
    for invocation in esm3["invocations"]:
        if invocation["engine_role"] == "structure_child":
            invocation["parent_invocation_id"] = first_parent

    with pytest.raises(ValueError, match="parent-child proof"):
        require_remote_engine_contracts(
            _catalog_snapshot(),
            json.loads(WORKFLOW_PATH.read_text(encoding="utf-8")),
            proof,
        )


def test_remote_engine_contract_rejects_claimed_remote_seed_control() -> None:
    proof = _exact_invocation_proof()
    esm3 = next(
        item
        for item in proof["remote_bindings"]
        if item["binding_id"] == "esm3.generate_paired.biohub_medium"
    )
    esm3["invocations"][0]["invocation_provenance"] = {
        "effective_randomness": {
            "control": "exact_seed",
            "effective_seed": 7,
        }
    }

    with pytest.raises(ValueError, match="randomness proof"):
        require_remote_engine_contracts(
            _catalog_snapshot(),
            json.loads(WORKFLOW_PATH.read_text(encoding="utf-8")),
            proof,
        )


def test_remote_engine_contract_rejects_incomplete_proteinmpnn_evidence() -> None:
    proof = _exact_invocation_proof()
    proof["proteinmpnn"]["invocations"][0][
        "invocation_provenance"
    ].pop("effective_randomness")

    with pytest.raises(ValueError, match="ProteinMPNN 3 x 5 Engine proof"):
        require_remote_engine_contracts(
            _catalog_snapshot(),
            json.loads(WORKFLOW_PATH.read_text(encoding="utf-8")),
            proof,
        )


def test_catalog_snapshot_requires_current_protocol_and_exact_stable_contracts(
) -> None:
    expected = build_discovered_frozen_catalog()
    snapshot = _catalog_snapshot()

    _require_catalog_snapshot_matches_current(
        snapshot,
        expected_catalog=expected,
        protocol_digest=bundle_digest(),
    )

    wrong_protocol = json.loads(json.dumps(snapshot))
    wrong_protocol["protocol_digest"] = "sha256:" + "0" * 64
    with pytest.raises(ValueError, match="protocol generation"):
        _require_catalog_snapshot_matches_current(
            wrong_protocol,
            expected_catalog=expected,
            protocol_digest=bundle_digest(),
        )

    wrong_contracts = json.loads(json.dumps(snapshot))
    wrong_contracts["contracts"][0]["reference"]["contract_digest"] = (
        "sha256:" + "0" * 64
    )
    with pytest.raises(ValueError, match="stable contracts"):
        _require_catalog_snapshot_matches_current(
            wrong_contracts,
            expected_catalog=expected,
            protocol_digest=bundle_digest(),
        )


def test_run_projection_must_match_retained_workflow_and_compile() -> None:
    workflow_digest = "sha256:" + "1" * 64
    snapshot = {
        "workflow_revision": 3,
        "workflow_digest": workflow_digest,
    }
    compile_receipt = {
        "compile_id": "compile-exact",
        "workflow_revision": 3,
        "workflow_digest": workflow_digest,
    }
    run = {
        "compile_id": "compile-exact",
        "workflow_revision": 3,
        "workflow_digest": workflow_digest,
    }

    _require_run_matches_compile(run, snapshot, compile_receipt)

    for field, wrong_value in (
        ("compile_id", "compile-foreign"),
        ("workflow_revision", 4),
        ("workflow_digest", "sha256:" + "2" * 64),
    ):
        mismatched = {**run, field: wrong_value}
        with pytest.raises(ValueError, match="Workflow/compile identity"):
            _require_run_matches_compile(
                mismatched,
                snapshot,
                compile_receipt,
            )


def test_run_event_envelopes_and_replay_cursor_are_scope_bound() -> None:
    run = {
        "project_id": PROJECT_ID,
        "run_id": "run-1",
        "status": "succeeded",
        "ledger_cursor": "cursor-terminal",
        "terminal_sequence": 7,
    }
    messages = [
        {
            "project_id": PROJECT_ID,
            "run_id": "run-1",
            "sequence": 0,
            "cursor": "cursor-origin",
            "event": {
                "type": "replay_started",
                "replay_through_cursor": "cursor-terminal",
            },
        },
        {
            "project_id": PROJECT_ID,
            "run_id": "run-1",
            "sequence": 7,
            "cursor": "cursor-terminal",
            "event": {"type": "run_terminal", "status": "succeeded"},
        },
        {
            "project_id": PROJECT_ID,
            "run_id": "run-1",
            "sequence": 7,
            "cursor": "cursor-terminal",
            "event": {
                "type": "replay_complete",
                "live_from_cursor": "cursor-terminal",
            },
        },
    ]

    assert _event_payloads(run, messages) == [
        {"type": "run_terminal", "status": "succeeded"}
    ]
    _validate_replay_boundary(run, messages)

    foreign = json.loads(json.dumps(messages))
    foreign[1]["run_id"] = "run-foreign"
    with pytest.raises(ValueError, match="crossed Project/Run scope"):
        _event_payloads(run, foreign)

    stale_cursor = json.loads(json.dumps(messages))
    stale_cursor[-1]["cursor"] = "cursor-stale"
    with pytest.raises(ValueError, match="replay cursor"):
        _validate_replay_boundary(run, stale_cursor)


def test_run_admission_event_must_match_compile_and_precede_execution() -> None:
    run = {
        "project_id": PROJECT_ID,
        "run_id": "run-1",
        "workflow_revision": 3,
        "compile_id": "compile-exact",
    }
    compile_receipt = {
        "workflow_revision": 3,
        "compile_id": "compile-exact",
    }
    messages = [
        {
            "project_id": PROJECT_ID,
            "run_id": "run-1",
            "sequence": 5,
            "event": {
                "type": "run_admitted",
                "workflow_revision": 3,
                "compile_id": "compile-exact",
            },
        },
        {
            "project_id": PROJECT_ID,
            "run_id": "run-1",
            "sequence": 6,
            "event": {
                "type": "run_started",
                "started_at": "2026-08-01T00:00:00Z",
            },
        },
        {
            "project_id": PROJECT_ID,
            "run_id": "run-1",
            "sequence": 7,
            "event": {
                "type": "node_attempt_started",
                "node_attempt_id": "node-attempt-1",
                "node_id": "generate-paired",
            },
        },
    ]

    _validate_run_admission(run, messages, compile_receipt)

    foreign_compile = json.loads(json.dumps(messages))
    foreign_compile[0]["event"]["compile_id"] = "compile-foreign"
    with pytest.raises(ValueError, match="Run admission"):
        _validate_run_admission(run, foreign_compile, compile_receipt)

    out_of_order = json.loads(json.dumps(messages))
    out_of_order[0]["sequence"] = 8
    with pytest.raises(ValueError, match="Run admission"):
        _validate_run_admission(run, out_of_order, compile_receipt)


def test_invocation_proof_must_equal_retained_run_ledger() -> None:
    catalog = _catalog_snapshot()
    workflow = json.loads(WORKFLOW_PATH.read_text(encoding="utf-8"))
    method_by_node = {
        "generate-paired": _method_digest(
            catalog,
            "esm3.generate_paired.esm3_medium_2024_08",
            REMOTE_CONTRACT_VERSION,
        ),
        "fold-sequences": _method_digest(
            catalog,
            "folding.fold.esmfold2_fast_biohub_2026_05",
            REMOTE_CONTRACT_VERSION,
        ),
        "fold-final": _method_digest(
            catalog,
            "folding.fold.esmfold2_fast_biohub_2026_05",
            REMOTE_CONTRACT_VERSION,
        ),
        "design-children": _method_digest(
            catalog,
            PROTEINMPNN_METHOD_ID,
            PROTEINMPNN_METHOD_VERSION,
        ),
    }
    role_by_node = {
        "generate-paired": "sequence_parent",
        "fold-sequences": "fold_parent_0_sample_0",
        "fold-final": "fold_parent_0_sample_0",
        "design-children": "design_parent_0",
    }
    messages: list[dict[str, Any]] = []
    for node_id in sorted(method_by_node):
        node_attempt_id = f"node-attempt-{node_id}"
        operation_attempt_id = f"operation-attempt-{node_id}"
        invocation_id = f"invocation-{node_id}"
        messages.extend(
            (
                {
                    "event": {
                        "type": "node_attempt_started",
                        "node_attempt_id": node_attempt_id,
                        "node_id": node_id,
                    }
                },
                {
                    "event": {
                        "type": "operation_attempt_started",
                        "operation_attempt_id": operation_attempt_id,
                        "node_attempt_id": node_attempt_id,
                    }
                },
                {
                    "event": {
                        "type": "engine_invocation_started",
                        "invocation_id": invocation_id,
                        "operation_attempt_id": operation_attempt_id,
                        "engine_role": role_by_node[node_id],
                        "engine_identity": method_by_node[node_id],
                        "invocation_provenance": (
                            {
                                "effective_randomness": {
                                    "control": "exact_seed",
                                    "effective_seed": 17,
                                },
                                "provider_residue_projection": {
                                    "position_semantics": (
                                        "one_based_chain_local"
                                    ),
                                    "workbench_chain_order": ["A"],
                                    "provider_chain_order": ["A"],
                                    "entries": [
                                        {
                                            "residue_id": "A:1",
                                            "provider_chain_id": "A",
                                            "provider_position": 1,
                                        }
                                    ],
                                },
                            }
                            if node_id == "design-children"
                            else {
                                "effective_randomness": {
                                    "control": "provider_uncontrolled",
                                }
                            }
                        ),
                    }
                },
                {
                    "event": {
                        "type": "engine_invocation_terminal",
                        "invocation_id": invocation_id,
                        "status": "succeeded",
                    }
                },
            )
            )
    for sequence, message in enumerate(messages, start=1):
        message.update({
            "project_id": PROJECT_ID,
            "run_id": "run-1",
            "sequence": sequence,
        })
    projection = {
        "project_id": PROJECT_ID,
        "run_id": "run-1",
        "node_dispositions": [
            {
                "node_id": node_id,
                "outcome": "succeeded",
                "resolution": "executed",
            }
            for node_id in method_by_node
        ],
    }
    run_records = [(projection, messages)]
    proof = _invocation_proof(catalog, workflow, run_records)

    require_invocation_proof_matches_ledger(
        proof,
        catalog,
        workflow,
        run_records,
    )
    tampered = json.loads(json.dumps(proof))
    tampered["remote_bindings"][0]["invocations"][0][
        "engine_identity"
    ] = "sha256:" + "0" * 64
    with pytest.raises(ValueError, match="retained Run Ledger"):
        require_invocation_proof_matches_ledger(
            tampered,
            catalog,
            workflow,
            run_records,
        )


@pytest.mark.acceptance
@pytest.mark.live_provider
def test_fresh_remote_3gb1_installed_public_run_retains_auditable_bundle(
    installed_artifact: InstalledArtifact,
    tmp_path: Path,
) -> None:
    expected_revision = os.environ.get(
        "PROTEIN_WORKBENCH_FRESH_SOURCE_REVISION"
    )
    assert expected_revision is not None
    observed_revision = subprocess.run(
        ["/usr/bin/git", "rev-parse", "HEAD"],
        cwd=PROJECT_ROOT,
        check=True,
        text=True,
        capture_output=True,
    ).stdout.strip()
    assert observed_revision == expected_revision
    assert subprocess.run(
        ["/usr/bin/git", "status", "--porcelain"],
        cwd=PROJECT_ROOT,
        check=True,
        text=True,
        capture_output=True,
    ).stdout == ""

    evidence_root = Path(
        os.environ["PROTEIN_WORKBENCH_FRESH_EVIDENCE_STAGING"]
    )
    evidence_root.mkdir(mode=0o700)
    assert not any(evidence_root.iterdir())

    configured_token = os.environ.get(
        "PROTEIN_WORKBENCH_BIOHUB_TOKEN_FILE"
    )
    token_file = validate_biohub_token_file(
        configured_token or PROJECT_ROOT / "keys" / "esmkey.txt"
    )
    proteinmpnn_root = Path(
        os.environ.get(
            "PROTEIN_WORKBENCH_PROTEINMPNN_ROOT",
            (
                "/Users/sorachan/Documents/ESM-workflow/"
                "third_party/ProteinMPNN"
            ),
        )
    ).resolve()
    assert proteinmpnn_root.is_dir() and not proteinmpnn_root.is_symlink()

    source_receipt = {
        "schema_namespace": SCHEMA_NAMESPACE,
        "source_revision": observed_revision,
        "source_dirty": False,
        "installed_imports_outside_source": True,
        "protocol_digest": bundle_digest(),
        "catalog_contract_digest": (
            build_discovered_frozen_catalog().contract_digest
        ),
        "workflow_id": PROJECT_ID,
        "workflow_content_digest": _digest(WORKFLOW_PATH),
        "installed_artifacts": [
            {
                "kind": "wheel",
                "filename": installed_artifact.wheel.name,
                "size": installed_artifact.wheel.stat().st_size,
                "content_digest": _digest(installed_artifact.wheel),
            },
            {
                "kind": "sdist",
                "filename": installed_artifact.sdist.name,
                "size": installed_artifact.sdist.stat().st_size,
                "content_digest": _digest(installed_artifact.sdist),
            },
        ],
    }
    receipt_path = evidence_root / "source-receipt.json"
    receipt_path.write_text(
        json.dumps(
            source_receipt,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n",
        encoding="utf-8",
    )
    receipt_path.chmod(0o600)

    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    env["PW_SOURCE_ROOT"] = str(PROJECT_ROOT)
    env["PROTEIN_WORKBENCH_BIOHUB_TOKEN_FILE"] = str(token_file)
    env["PROTEIN_WORKBENCH_PROTEINMPNN_ROOT"] = str(proteinmpnn_root)
    for name in ("PROJECT", "CACHE", "OUTPUT", "RUN"):
        isolated = tmp_path / name.lower()
        isolated.mkdir(mode=0o700)
        env[f"PROTEIN_WORKBENCH_{name}_ROOT"] = str(isolated)
    completed = subprocess.run(
        [
            str(installed_artifact.python),
            "-I",
            str(PROJECT_ROOT / "scripts" / "fresh_remote_3gb1.py"),
        ],
        cwd=installed_artifact.run_root,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
        timeout=80 * 60,
    )
    assert completed.returncode == 0, completed.stdout
    assert "Bearer " not in completed.stdout
    summary = validate_evidence_bundle(evidence_root)
    assert summary["source_revision"] == observed_revision
    assert summary["artifact_count"] == 15
    assert summary["run_count"] >= 1
    assert stat.S_IMODE(evidence_root.stat().st_mode) & 0o077 == 0
