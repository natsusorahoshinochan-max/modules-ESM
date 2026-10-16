"""Folding scenario assembly with explicit tool clients and fixture model roots."""

from __future__ import annotations

from tests.support.ledger import public_run_events, public_run_projection
from contextlib import ExitStack
from pathlib import Path
from typing import Any
from unittest.mock import patch
import pytest
from core.project.manager import ProjectManager
from core.catalog.builder import build_frozen_catalog
from core.execution.environment import admit_environment_configuration
from core.execution.node_attempt import NodeAttemptFactory
from core.execution.runtime import V2RunService
from tests.support.result_store import result_store
from core.workflow.authoring import WorkflowAuthoringService
from core.workflow.document import WorkflowDocument, WorkflowNodeInstance
from core.workflow.document import WorkflowEdge
from tests.support.runtime_results import decode_service_typed_output_value


def _decode_output(
    service: Any,
    catalog: Any,
    projection: dict[str, Any],
    output: dict[str, Any],
) -> Any:
    return decode_service_typed_output_value(
        service,
        catalog,
        projection,
        output,
    )


def _run_fold(
    tmp_path: Path,
    *,
    route: str,
    client: Any,
    environment_overrides: dict[str, Any] | None = None,
    source_sequence: str = "AG",
    num_samples: int = 1,
) -> tuple[Any, Any, dict[str, Any], tuple[dict[str, Any], ...]]:
    from modules.folding.package import MODULE_PACKAGE as FOLDING_PACKAGE
    from modules.structure_prediction.package import (
        MODULE_PACKAGE as STRUCTURE_PREDICTION_PACKAGE,
    )
    from modules.structure_transform.package import (
        MODULE_PACKAGE as STRUCTURE_TRANSFORM_PACKAGE,
    )
    from tests.fixtures.folding_sources.package import (
        MODULE_PACKAGE as SOURCE_PACKAGE,
    )

    source = WorkflowNodeInstance(
        node_id="source",
        node_type_id="contract_test.folding_sequence_source",
        binding_id="contract_test.folding_sequence_source.direct",
        node_parameters={"sequence": source_sequence},
        binding_parameters={},
    )
    fold = WorkflowNodeInstance(
        node_id="fold",
        node_type_id="folding.fold",
        binding_id=f"folding.fold.esmfold2_{route}",
        node_parameters={
            "effective_seed": 1603,
            "num_samples": num_samples,
        },
        binding_parameters={},
    )
    materialize = WorkflowNodeInstance(
        node_id="materialize-confidence",
        node_type_id="structure_prediction.materialize_confidence",
        binding_id="structure_prediction.materialize_confidence.direct",
        node_parameters={},
        binding_parameters={},
    )
    catalog = build_frozen_catalog(
        (
            FOLDING_PACKAGE,
            SOURCE_PACKAGE,
            STRUCTURE_PREDICTION_PACKAGE,
            STRUCTURE_TRANSFORM_PACKAGE,
        )
    )
    projects = ProjectManager(
        tmp_path / "projects",
        cache_root=tmp_path / "cache",
        output_root=tmp_path / "outputs",
        run_root=tmp_path / "runs",
    )
    project = projects.create(f"folding {route}")
    authoring = WorkflowAuthoringService(projects, catalog)
    workflow = WorkflowDocument(
        schema_version="2.1.0",
        workflow_id=project.id,
        nodes=(source, fold, materialize),
        edges=(
            WorkflowEdge(
                "source",
                "sequence_candidates",
                "fold",
                "sequence_candidates",
            ),
            WorkflowEdge(
                "fold",
                "structure_candidates",
                "materialize-confidence",
                "structure_candidates",
            ),
            WorkflowEdge(
                "fold",
                "confidence_facts",
                "materialize-confidence",
                "confidence_facts",
            ),
        ))
    committed = authoring.commit(
        project.id,
        workflow=workflow,
    )
    environment_values = (
        {
            "credential_handle": "must-never-publish",
        }
        if route == "remote" and client is not None
        else {}
    )
    environment_values.update(environment_overrides or {})
    environment = admit_environment_configuration(
        catalog,
        {
            f"folding.fold.esmfold2_{route}": environment_values,
        }
    )
    service = V2RunService(
        projects,
        catalog,
        authoring,
        NodeAttemptFactory(
            projects,
            environment,
            result_store(projects),
        ),
        result_store(projects),
    )
    with ExitStack() as stack:
        if client is not None:
            target = (
                "modules.folding.esmfold2_remote.build_remote_engine"
                if route == "remote"
                else "modules.folding.esmfold2_local.load_local_engine"
            )
            stack.enter_context(patch(target, return_value=client))
        try:
            receipt = service.start_background(
                project.id,
                workflow_commit_id=committed.workflow_commit_id,
                client_request_id=f"fold-{route}",
            )
            service.shutdown()
            projection = public_run_projection(
                service,
                project.id,
                receipt["run_id"],
            )
            events = public_run_events(service, project.id, receipt["run_id"])
        finally:
            service.shutdown()
    return service, catalog, projection, events


def _write_local_runtime_fixture(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> dict[str, Any]:
    import modules.folding.esmfold2_local as adapter

    fold_snapshot = tmp_path / "esmfold2"
    language_snapshot = tmp_path / "esmc"
    fold_snapshot.mkdir()
    language_snapshot.mkdir()
    for name in adapter.LOCAL_ESMFOLD2_MODEL_SNAPSHOT_FILES:
        (fold_snapshot / name).write_bytes(b"folding-model-fixture")
    for name in adapter.LOCAL_ESMFOLD2_LANGUAGE_MODEL_SNAPSHOT_FILES:
        (language_snapshot / name).write_bytes(b"language-model-fixture")
    return {
        "model_snapshot_path": fold_snapshot,
        "language_model_snapshot_path": language_snapshot,
    }
