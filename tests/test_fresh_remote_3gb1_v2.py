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

import pytest

from core import build_discovered_frozen_catalog
from modules.provider_contract import validate_biohub_token_file
from protein_workbench_public import bundle_digest
from scripts.fresh_remote_3gb1 import (
    PROJECT_ID,
    REMOTE_BINDINGS,
    SCHEMA_NAMESPACE,
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


def _digest(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _catalog_snapshot() -> dict[str, object]:
    return build_discovered_frozen_catalog().public_snapshot(
        protocol_digest=bundle_digest()
    )


def _exact_invocation_proof() -> dict[str, object]:
    sequence_invocations = [
        {
            "invocation_id": f"invocation-esm3-sequence-{index}",
            "engine_role": "sequence_parent",
            "engine_identity": (
                "esm3.biohub.esm3-medium-2024-08.generate_sequence"
            ),
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
            "engine_identity": (
                "esm3.biohub.esm3-medium-2024-08.generate_structure"
            ),
            "node_id": "generate-paired",
            "terminal": {"status": "succeeded"},
        }
        for index in range(10)
    ]
    folding_invocations = [
        {
            "invocation_id": f"invocation-fold-{node_id}-{index}",
            "engine_role": f"fold_parent_{index}_sample_0",
            "engine_identity": (
                "folding.esmfold2_remote."
                "folding.fold.esmfold2_fast_biohub_2026_05"
            ),
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
        "catalog_contract_digest": _catalog_snapshot()[
            "catalog_contract_digest"
        ],
        "remote_bindings": [
            {
                "binding_id": binding_id,
                "method_id": expected["method"],
                "adapter_id": expected["adapter"],
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
            for index, (binding_id, expected) in enumerate(
                REMOTE_BINDINGS.items()
            )
        ],
        "proteinmpnn": {
            "binding_id": "proteinmpnn.design.local",
            "method_id": "proteinmpnn.design.v_48_020_8907e667",
            "adapter_id": "proteinmpnn.v2/adapter",
            "source": "ProteinMPNN",
            "invocations": [
                {
                    "invocation_id": f"invocation-mpnn-{index}",
                    "engine_role": f"design_parent_{index}",
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
