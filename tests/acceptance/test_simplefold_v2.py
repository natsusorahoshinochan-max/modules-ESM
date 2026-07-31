"""Required source-bound heavy acceptance for the v2 SimpleFold Binding."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from core import (
    EnvironmentConfiguration,
    ProjectManager,
    V2RunService,
    WorkflowAuthoringService,
    WorkflowDocument,
    WorkflowNodeInstance,
    build_frozen_catalog,
    parse_workflow_document,
)
from core.workflow_v2 import WorkflowEdge
from modules.folding.adapter import _pdb_sequence
from tests.acceptance.conftest import require_ready


@pytest.mark.acceptance
@pytest.mark.local_provider
@pytest.mark.slow
def test_simplefold_v2_folds_3gb1_through_exact_binding(
    readiness: dict[str, bool],
    pdb_3gb1: object,
    tmp_path: Path,
) -> None:
    """Execute the exact v2 Binding; skips are forbidden by its full gate."""
    require_ready("simplefold", readiness)
    from modules.folding.package import MODULE_PACKAGE as FOLDING_PACKAGE
    from modules.folding.simplefold_adapter import (
        SIMPLEFOLD_DEVICE,
        configured_runtime_fingerprint,
        provider_identity,
    )
    from tests.fixtures.folding_sources.package import (
        MODULE_PACKAGE as SOURCE_PACKAGE,
    )

    sequence = _pdb_sequence(pdb_3gb1.pdb_string)
    source = WorkflowNodeInstance(
        node_id="source",
        node_type_id="contract_test.folding_sequence_source",
        node_type_version="2.1.0",
        binding_id="contract_test.folding_sequence_source.direct",
        binding_version="2.1.0",
        node_parameters={"sequence": sequence},
        binding_parameters={},
    )
    fold = WorkflowNodeInstance(
        node_id="fold",
        node_type_id="folding.fold",
        node_type_version="2.1.0",
        binding_id="folding.fold.simplefold_local",
        binding_version="2.1.0",
        node_parameters={"effective_seed": 1603, "num_samples": 1},
        binding_parameters={"num_steps": 10},
    )
    catalog = build_frozen_catalog((FOLDING_PACKAGE, SOURCE_PACKAGE))
    projects = ProjectManager(
        tmp_path / "projects",
        cache_root=tmp_path / "cache",
        output_root=tmp_path / "outputs",
        run_root=tmp_path / "runs",
    )
    project = projects.create("SimpleFold v2 3GB1")
    authoring = WorkflowAuthoringService(projects, catalog)
    workflow = WorkflowDocument(
        schema_version="2.1.0",
        workflow_id=project.id,
        nodes=(source, fold),
        edges=(
            WorkflowEdge(
                "source",
                "sequence_candidates",
                "fold",
                "sequence_candidates",
            ),
        ),
        contract_lock=(),
    )
    saved = authoring.save(
        project.id,
        expected_workflow_revision=0,
        workflow=workflow,
    )
    relocked = authoring.relock(
        project.id,
        workflow_revision=saved["workflow_revision"],
    )
    compiled = authoring.compile(
        project.id,
        workflow_revision=relocked["workflow_revision"],
        workflow=parse_workflow_document(relocked["workflow"]),
    )
    fingerprint = configured_runtime_fingerprint()
    environment = EnvironmentConfiguration({
        ("folding.fold.simplefold_local", "2.1.0"): {
            "values": {
                "model_root": Path(
                    os.environ["PROTEIN_WORKBENCH_SIMPLEFOLD_MODEL_ROOT"]
                ),
                "esm2_source_root": Path(
                    os.environ["PROTEIN_WORKBENCH_SIMPLEFOLD_ESM2_ROOT"]
                ),
                "esm2_model_root": Path(
                    os.environ[
                        "PROTEIN_WORKBENCH_SIMPLEFOLD_ESM2_MODEL_ROOT"
                    ]
                ),
                "device": SIMPLEFOLD_DEVICE,
                "resolved_runtime_fingerprint": fingerprint,
            },
            "safe_fingerprint": fingerprint,
            "invalidation_token": fingerprint,
        }
    })
    service = V2RunService(projects, catalog, authoring, environment)
    try:
        receipt = service.start_background(
            project.id,
            workflow_revision=relocked["workflow_revision"],
            compile_id=compiled.public_receipt()["compile_id"],
            client_request_id="simplefold-v2-heavy",
        )
        service.shutdown()
        projection = service.projection(project.id, receipt["run_id"])
        events = service.public_events(project.id, receipt["run_id"])
    finally:
        service.shutdown()

    assert projection["status"] == "succeeded", json.dumps(events, indent=2)
    outputs = {
        output["output_port"]: output
        for output in projection["outputs"]
        if output["node_id"] == "fold"
    }
    assert {
        "structure_candidates",
        "confidence_observations",
        "pae_observations",
    } == set(outputs)
    binding = catalog.require_contract(
        "binding",
        "folding.fold.simplefold_local",
        "2.1.0",
    )
    assert binding.descriptor["method"]["contract_id"] == (
        "folding.fold.simplefold_100m_c7a5570"
    )
    identity = provider_identity()
    prerequisites = binding.descriptor["readiness_declaration"][
        "prerequisites"
    ]
    assert prerequisites["simplefold_models"]["artifact_sha256"] == (
        identity["artifact_sha256"]
    )
    assert prerequisites["esm2_models"]["artifact_sha256"] == (
        identity["esm2_artifact_sha256"]
    )
    public_evidence = json.dumps(
        {"projection": projection, "events": events}
    )
    assert all(
        fragment not in public_evidence
        for fragment in (
            os.environ["PROTEIN_WORKBENCH_SIMPLEFOLD_MODEL_ROOT"],
            os.environ["PROTEIN_WORKBENCH_SIMPLEFOLD_ESM2_ROOT"],
            os.environ["PROTEIN_WORKBENCH_SIMPLEFOLD_ESM2_MODEL_ROOT"],
        )
    )
    invocations = [
        event["event"]
        for event in events
        if event["event"]["type"] == "engine_invocation_terminal"
        and any(
            started["event"]["type"] == "engine_invocation_started"
            and started["event"]["invocation_id"]
            == event["event"]["invocation_id"]
            and started["event"]["engine_identity"].startswith(
                "folding.simplefold_local."
            )
            for started in events
        )
    ]
    assert len(invocations) == 1
    assert invocations[0]["status"] == "succeeded"
    readiness_index = next(
        index
        for index, event in enumerate(events)
        if event["event"]["type"] == "readiness_attested"
        and event["event"]["binding"]["contract_id"]
        == "folding.fold.simplefold_local"
        and event["event"]["binding"]["contract_version"] == "2.1.0"
        and event["event"]["conclusion"] == "passing"
    )
    invocation_index = next(
        index
        for index, event in enumerate(events)
        if event["event"]["type"] == "engine_invocation_started"
        and event["event"]["invocation_id"] == invocations[0]["invocation_id"]
    )
    assert readiness_index < invocation_index
    assert [
        event["event"]["status"]
        for event in events
        if event["event"]["type"] == "run_terminal"
    ] == ["succeeded"]
