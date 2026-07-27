"""One fresh canonical run against the required real providers."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from tests.deterministic_acceptance.backend_client import (
    BackendAcceptanceClient,
)
from tests.fresh_remote_acceptance.operator import (
    CANONICAL_NODE_ORDER,
    PROJECT_ID,
    canonical_module_inventory,
    public_workflow_sha256,
    seal_fresh_remote_evidence,
    validate_fresh_remote_contract,
)


pytestmark = [
    pytest.mark.acceptance,
    pytest.mark.fresh_remote_real,
    pytest.mark.live_provider,
    pytest.mark.local_provider,
    pytest.mark.slow,
]


def test_fresh_remote_real_canonical_3gb1(
    real_backend_client: BackendAcceptanceClient,
) -> None:
    """REST, run WebSocket, manifest, and fifteen PDB downloads agree."""
    workflow = real_backend_client.get_workflow(PROJECT_ID)
    workflow_sha256 = public_workflow_sha256(workflow)
    expected_modules = canonical_module_inventory(
        workflow,
        real_backend_client.modules(),
    )
    expected_revision = os.environ[
        "PROTEIN_WORKBENCH_APPROVED_SOURCE_REVISION"
    ]
    accepted = real_backend_client.run_saved(
        PROJECT_ID,
        seed=4242,
        force_rerun_nodes=list(CANONICAL_NODE_ORDER),
    )
    assert accepted["valid"] is True
    assert accepted["errors"] == []
    run_id = accepted["run_id"]

    events = real_backend_client.receive_run_events(PROJECT_ID, run_id)
    manifest = real_backend_client.manifest(PROJECT_ID, run_id)
    outputs = real_backend_client.outputs(PROJECT_ID, run_id)
    contract = validate_fresh_remote_contract(
        manifest=manifest,
        outputs=outputs,
        events=events,
        expected_revision=expected_revision,
        expected_workflow_sha256=workflow_sha256,
        expected_modules=expected_modules,
    )

    provider_evidence_path = Path(
        os.environ["PROTEIN_WORKBENCH_PROVIDER_CALL_EVIDENCE"]
    )
    provider_events = [
        json.loads(line)
        for line in provider_evidence_path.read_text().splitlines()
        if line
    ]
    evidence_root = Path(
        os.environ["PROTEIN_WORKBENCH_ACCEPTANCE_EVIDENCE_ROOT"]
    )
    sealed = seal_fresh_remote_evidence(
        evidence_root=evidence_root,
        client=real_backend_client,
        contract=contract,
        manifest=manifest,
        events=events,
        provider_events=provider_events,
    )
    assert sealed.run_id == run_id
    assert len(sealed.artifact_paths) == 15
