"""Shared real-service helpers for prompt-authoring v2 acceptance."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from core import (
    EnvironmentConfiguration,
    ProjectManager,
    V2RunService,
    WorkflowAuthoringService,
    WorkflowDocument,
    WorkflowNodeInstance,
    build_frozen_catalog,
)
from core.port_types import canonical_json_bytes
from core.workflow_v2 import WorkflowEdge
from datatypes import ResidueLayout
from modules.prompt_authoring.package import MODULE_PACKAGE
from modules.structure_transform.package import (
    MODULE_PACKAGE as STRUCTURE_TRANSFORM_PACKAGE,
)
from tests.fixtures.public_v2 import wait_for_service_run_terminal_events
from tests.fixtures.prompt_authoring_sources.package import (
    MODULE_PACKAGE as SOURCE_PACKAGE,
)


WORKFLOW_SCHEMA_VERSION = "2.1.0"
VERSION = "3.0.0"
SOURCE_VERSION = "4.0.0"
SOURCE_LAYOUT = ResidueLayout(
    chain_id="A,B",
    length=3,
    residue_ids=["A:1", "A:2", "B:1"],
)
TARGET_LAYOUT = ResidueLayout(
    chain_id="A,B",
    length=3,
    residue_ids=["A:1", "A:new", "B:1"],
)


def wire_value(type_id: str, value: object) -> object:
    """Encode one expected value through its exact public Port codec."""
    port_version = {
        "function.annotations": "3.0.0",
        "protein.structure": "4.0.0",
        "structure_transform.resolved_residue_axis": "4.0.0",
    }.get(type_id, VERSION)
    encoded = build_frozen_catalog(
        (MODULE_PACKAGE, STRUCTURE_TRANSFORM_PACKAGE)
    ).require_port_type(
        type_id,
        port_version,
    ).encode(value)
    return json.loads(encoded)["value"]


def decoded_output(catalog: Any, output: dict[str, Any]) -> object:
    """Decode one Run Projection value through its published Port contract."""
    reference = output["port_type"]
    port_type = catalog.require_port_type(
        reference["contract_id"],
        reference["contract_version"],
    )
    return port_type.decode(
        canonical_json_bytes(
            {
                "schema_namespace": "protein-workbench-port-value/v2",
                "port_type_id": reference["contract_id"],
                "port_type_version": reference["contract_version"],
                "value": output["values"][0],
            }
        )
    )


@dataclass(frozen=True)
class PreparedPromptOperation:
    """One compiled prompt-authoring operation reusable across Runs."""

    catalog: Any
    service: V2RunService
    project_id: str
    workflow_commit_id: str

    def start(
        self,
        client_request_id: str,
    ) -> tuple[dict[str, Any], tuple[dict[str, Any], ...]]:
        receipt = self.service.start_background(
            self.project_id,
            workflow_commit_id=self.workflow_commit_id,
            client_request_id=client_request_id,
        )
        wait_for_service_run_terminal_events(
            self.service,
            self.project_id,
            receipt["run_id"],
        )
        projection = self.service.projection(
            self.project_id,
            receipt["run_id"],
        )
        events = self.service.public_events(
            self.project_id,
            receipt["run_id"],
        )
        return projection, events


def prepare_operation(
    tmp_path: Path,
    *,
    operation: str,
    node_parameters: dict[str, Any],
    source_edges: tuple[WorkflowEdge, ...] = (),
    source_fixture: str = "canonical",
    environment_label: str = "one",
) -> PreparedPromptOperation:
    """Compile one production Node through the real reusable v2 services."""
    catalog = build_frozen_catalog(
        (MODULE_PACKAGE, SOURCE_PACKAGE, STRUCTURE_TRANSFORM_PACKAGE)
    )
    projects = ProjectManager(
        tmp_path / "projects",
        cache_root=tmp_path / "cache",
        output_root=tmp_path / "outputs",
        run_root=tmp_path / "runs",
    )
    project = projects.create(f"prompt authoring {operation}")
    source = WorkflowNodeInstance(
        node_id="source",
        node_type_id="contract_test.prompt_authoring_values",
        node_type_version=SOURCE_VERSION,
        binding_id="contract_test.prompt_authoring_values.direct",
        binding_version=SOURCE_VERSION,
        node_parameters={"fixture": source_fixture},
        binding_parameters={},
    )
    binding_id = f"prompt_authoring.{operation}.direct"
    operation_version = "5.0.0" if operation == "prompt_from_structure" else VERSION
    workflow = WorkflowDocument(
        schema_version=WORKFLOW_SCHEMA_VERSION,
        workflow_id=project.id,
        nodes=(
            *((source,) if source_edges else ()),
            WorkflowNodeInstance(
                node_id="author",
                node_type_id=f"prompt_authoring.{operation}",
                node_type_version=operation_version,
                binding_id=binding_id,
                binding_version=operation_version,
                node_parameters=node_parameters,
                binding_parameters={},
            ),
        ),
        edges=source_edges,
        contract_lock=(),
    )
    authoring = WorkflowAuthoringService(projects, catalog)
    committed = authoring.commit(
        project.id,
        expected_draft_revision=0,
        workflow=workflow,
    )
    service = V2RunService(
        projects,
        catalog,
        authoring,
        EnvironmentConfiguration(
            {
                (binding_id, operation_version): {
                    "values": {
                        "credential": (
                            f"not-result-affecting-{environment_label}"
                        ),
                    },
                    "safe_fingerprint": f"environment-{environment_label}",
                    "invalidation_token": f"environment-{environment_label}",
                }
            }
        ),
    )
    return PreparedPromptOperation(
        catalog=catalog,
        service=service,
        project_id=project.id,
        workflow_commit_id=committed.workflow_commit_id,
    )


def run_operation(
    tmp_path: Path,
    *,
    operation: str,
    node_parameters: dict[str, Any],
    source_edges: tuple[WorkflowEdge, ...] = (),
    source_fixture: str = "canonical",
    environment_label: str = "one",
) -> tuple[Any, dict[str, Any], tuple[dict[str, Any], ...]]:
    """Compile and execute one production Node through the real v2 services."""
    prepared = prepare_operation(
        tmp_path,
        operation=operation,
        node_parameters=node_parameters,
        source_edges=source_edges,
        source_fixture=source_fixture,
        environment_label=environment_label,
    )
    try:
        projection, events = prepared.start(
            f"prompt-authoring-{operation}-{environment_label}"
        )
        return prepared.catalog, projection, events
    finally:
        prepared.service.shutdown()
