"""Shared real-service helpers for prompt-authoring v2 acceptance."""

from __future__ import annotations

import json
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
    parse_workflow_document,
)
from core.port_types import canonical_json_bytes
from core.workflow_v2 import WorkflowEdge
from datatypes import ResidueLayout
from modules.prompt_authoring.package import MODULE_PACKAGE
from tests.fixtures.prompt_authoring_sources.package import (
    MODULE_PACKAGE as SOURCE_PACKAGE,
)


VERSION = "2.0.0"
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
    encoded = build_frozen_catalog((MODULE_PACKAGE,)).require_port_type(
        type_id,
        VERSION,
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
    catalog = build_frozen_catalog((MODULE_PACKAGE, SOURCE_PACKAGE))
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
        node_type_version=VERSION,
        binding_id="contract_test.prompt_authoring_values.direct",
        binding_version=VERSION,
        node_parameters={"fixture": source_fixture},
        binding_parameters={},
    )
    binding_id = f"prompt_authoring.{operation}.direct"
    workflow = WorkflowDocument(
        schema_version=VERSION,
        workflow_id=project.id,
        nodes=(
            *((source,) if source_edges else ()),
            WorkflowNodeInstance(
                node_id="author",
                node_type_id=f"prompt_authoring.{operation}",
                node_type_version=VERSION,
                binding_id=binding_id,
                binding_version=VERSION,
                node_parameters=node_parameters,
                binding_parameters={},
            ),
        ),
        edges=source_edges,
        contract_lock=(),
    )
    authoring = WorkflowAuthoringService(projects, catalog)
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
    service = V2RunService(
        projects,
        catalog,
        authoring,
        EnvironmentConfiguration(
            {
                (binding_id, VERSION): {
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
    receipt = service.start_background(
        project.id,
        workflow_revision=relocked["workflow_revision"],
        compile_id=compiled.public_receipt()["compile_id"],
        client_request_id=(
            f"prompt-authoring-{operation}-{environment_label}"
        ),
    )
    service.shutdown()
    projection = service.projection(project.id, receipt["run_id"])
    events = service.public_events(project.id, receipt["run_id"])
    return catalog, projection, events
