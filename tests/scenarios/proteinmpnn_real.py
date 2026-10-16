"""Explicit real ProteinMPNN scenario assembly using the configured Provider root."""

from __future__ import annotations

from tests.support.ledger import public_run_events, public_run_projection
import os
from pathlib import Path
from typing import Any
from core.project.manager import ProjectManager
from core.catalog.builder import build_frozen_catalog
from core.execution.environment import admit_environment_configuration
from core.execution.node_attempt import NodeAttemptFactory
from core.execution.runtime import V2RunService
from tests.support.result_store import result_store
from core.workflow.authoring import WorkflowAuthoringService
from core.workflow.document import WorkflowDocument, WorkflowNodeInstance
from core.workflow.document import WorkflowEdge


def _environment(
    binding_id: str,
) -> dict[str, dict[str, object]]:
    return {
        binding_id: {
            "provider_root": Path(
                os.environ["PROTEIN_WORKBENCH_PROTEINMPNN_ROOT"]
            ).resolve(),
        }
    }


def _run(
    tmp_path: Path,
    *,
    nodes: tuple[WorkflowNodeInstance, ...],
    edges: tuple[WorkflowEdge, ...],
    binding_id: str,
) -> tuple[Any, V2RunService, dict[str, Any], tuple[dict[str, Any], ...]]:
    from modules.proteinmpnn.package import (
        MODULE_PACKAGE as PROTEINMPNN_PACKAGE,
    )
    from modules.structure_transform.package import (
        MODULE_PACKAGE as STRUCTURE_TRANSFORM_PACKAGE,
    )
    from tests.fixtures.proteinmpnn_model_sources.package import (
        MODULE_PACKAGE as SOURCE_PACKAGE,
    )

    catalog = build_frozen_catalog(
        (
            PROTEINMPNN_PACKAGE,
            SOURCE_PACKAGE,
            STRUCTURE_TRANSFORM_PACKAGE,
        )
    )
    projects = ProjectManager(
        tmp_path / "projects",
        cache_root=tmp_path / "cache",
        output_root=tmp_path / "outputs",
        run_root=tmp_path / "runs",
    )
    project = projects.create("ProteinMPNN v2 real-model gate")
    authoring = WorkflowAuthoringService(projects, catalog)
    committed = authoring.commit(
        project.id,
        workflow=WorkflowDocument(
            schema_version="2.1.0",
            workflow_id=project.id,
            nodes=nodes,
            edges=edges),
    )
    service = V2RunService(
        projects,
        catalog,
        authoring,
        NodeAttemptFactory(
            projects,
            admit_environment_configuration(
                catalog,
                _environment(binding_id),
            ),
            result_store(projects),
        ),
        result_store(projects),
    )
    receipt = service.start_background(
        project.id,
        workflow_commit_id=committed.workflow_commit_id,
        client_request_id=f"proteinmpnn-v2-{binding_id}",
    )
    service.shutdown()
    return (
        catalog,
        service,
        public_run_projection(service, project.id, receipt["run_id"]),
        public_run_events(service, project.id, receipt["run_id"]),
    )


def _decode(
    catalog: Any,
    service: V2RunService,
    projection: dict[str, Any],
    output: dict[str, Any],
) -> object:
    from tests.support.runtime_results import decode_service_typed_output_value

    return decode_service_typed_output_value(
        service,
        catalog,
        projection,
        output,
    )


def _axis_resolver() -> WorkflowNodeInstance:
    return WorkflowNodeInstance(
        node_id="resolve-axes",
        node_type_id=(
            "structure_transform.resolve_candidate_residue_axes"
        ),
        binding_id=(
            "structure_transform.resolve_candidate_residue_axes.direct"
        ),
        node_parameters={},
        binding_parameters={},
    )
