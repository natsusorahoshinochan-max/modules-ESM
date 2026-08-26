"""Behavioral tests for the deep Workflow Commit authoring seam."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

import core.workflow.authoring as workflow_authoring
from core.project.manager import ProjectManager
from core.catalog.builder import (
    build_frozen_catalog,
)
from core.catalog.builtins import (
    builtin_frozen_catalog,
)
from core.catalog.declarations import (
    ReadinessDeclaration,
    ScientificOperationFactory,
)
from core.catalog.model import (
    CatalogContract,
    FrozenCatalog,
)
from core.catalog.port_contract import (
    BehaviorReference,
)
from core.operation import ReadinessResult
from core.workflow.authoring import (
    WorkflowAuthoringError,
    WorkflowAuthoringService,
)
from core.workflow.document import (
    WorkflowDocument,
    WorkflowNodeInstance,
)
from protein_workbench_public.workflow_codec import (
    decode_workflow_document,
    encode_workflow_commit_receipt,
    encode_workflow_document,
    encode_workflow_draft,
)
from core.project.manager import CANONICAL_3GB1_PROJECT_ID
from tests.support.application import create_application
from core.workflow.authoring import (
    WorkflowCommit,
    WorkflowDraft,
)
from core.workflow.document import workflow_document_from_canonical
from tests.support.catalog import (
    binding_availability,
    catalog_contract,
    install_runtime,
)
from tests.support.protocol import validate_error
from tests.fixtures.zero_core_packages.synthetic_echo.package import (
    MODULE_PACKAGE as SYNTHETIC_ECHO_PACKAGE,
)
from tests.fixtures.zero_core_packages.synthetic_echo.tests.cases import (
    EXECUTION_CASE as SYNTHETIC_ECHO_EXECUTION_CASE,
)


def _contract(
    contract_kind: str,
    contract_id: str,
    descriptor: dict,
) -> CatalogContract:
    return catalog_contract(
        contract_kind,
        contract_id,
        {
            "schema_namespace": "protein-workbench-contract/v2",
            "contract_kind": contract_kind,
            "contract_id": contract_id,
            **descriptor,
        },
    )


def _catalog(method_name: str = "source") -> FrozenCatalog:
    builtin = builtin_frozen_catalog()
    text = builtin.require_port_type("text")
    method = _contract(
        "method",
        "test.source.method",
        {"algorithm_identity": {"name": method_name}},
    )
    node = _contract(
        "node_type",
        "test.source",
        {
            "inputs": [],
            "outputs": [
                {
                    "name": "text",
                    "port_type": text.reference(),
                    "required": True,
                    "multiplicity": "one",
                    "scientific_meaning": "Synthetic source text",
                }
            ],
            "node_parameters": {},
        },
    )
    binding = _contract(
        "binding",
        "test.source.direct",
        {
            "node_type": node.reference(),
            "method": method.reference(),
            "execution_route": "direct",
            "deterministic": True,
            "cacheable": True,
            "binding_parameters": {},
            "produced_observations": [],
        },
    )
    factory = ScientificOperationFactory(
        behavior=BehaviorReference("test.source/factory", {}),
        build=lambda _context: object(),
    )
    readiness = ReadinessDeclaration(
        behavior=BehaviorReference("test.source/readiness", {}),
        prerequisites={},
        check=lambda _input: ReadinessResult(True),
    )
    observed_at = datetime(2026, 8, 3, tzinfo=timezone.utc)
    return FrozenCatalog(
        builtin.port_types,
        contracts=install_runtime(
            (method, node, binding),
            factories={binding.contract_id: factory},
            readiness={binding.contract_id: readiness},
        ),
        availability=(binding_availability(binding, observed_at),),
        availability_observed_at=observed_at,
    )


def _workflow(
    project_id: str,
    *,
    invalid_edge: bool = False,
    node_id: str = "source",
):
    return decode_workflow_document(
        {
            "schema_version": "2.1.0",
            "workflow_id": project_id,
            "nodes": [
                {
                    "node_id": node_id,
                    "node_type_id": "test.source",
                    "binding_id": "test.source.direct",
                    "node_parameters": {},
                    "binding_parameters": {},
                }
            ],
            "edges": (
                [
                    {
                        "source_node_id": "source",
                        "source_port": "text",
                        "target_node_id": "source",
                        "target_port": "missing",
                    }
                ]
                if invalid_edge
                else []
            ),
        }
    )


def test_invalid_draft_can_be_saved_and_loaded(tmp_path) -> None:
    projects = ProjectManager(tmp_path / "projects")
    project = projects.create("invalid draft")
    authoring = WorkflowAuthoringService(projects, _catalog())
    workflow = _workflow(project.id, invalid_edge=True)

    saved = authoring.save_draft(
        project.id,
        workflow=workflow,
    )

    assert encode_workflow_draft(saved) == {
        "project_id": project.id,
        "draft_revision": 1,
        "workflow": encode_workflow_document(workflow),
    }
    assert authoring.load_draft(project.id) == saved


def test_commit_compiles_and_activates_one_draft(tmp_path) -> None:
    projects = ProjectManager(tmp_path / "projects")
    project = projects.create("commit draft")
    catalog = _catalog()
    authoring = WorkflowAuthoringService(projects, catalog)
    workflow = _workflow(project.id)

    committed = authoring.commit(
        project.id,
        workflow=workflow,
    )

    draft = authoring.load_draft(project.id)
    assert committed == authoring.load_active_commit(project.id)
    assert committed.source_draft_revision == 1
    assert committed.workflow == draft.workflow
    assert committed.workflow_commit_id.startswith("workflow-commit-")
    assert committed.scientific_definitions
    definition_keys = [
        (definition["contract_kind"], definition["contract_id"])
        for definition in committed.scientific_definitions
    ]
    assert definition_keys == sorted(set(definition_keys))
    assert all(
        "node_id" not in definition
        for definition in committed.scientific_definitions
    )
    receipt = encode_workflow_commit_receipt(committed)
    assert receipt["issues"] == []
    assert "compile_id" not in receipt

    compiled = authoring.require_verified_commit(
        project.id,
        workflow_commit_id=committed.workflow_commit_id,
    )
    assert compiled.commit == committed
    assert compiled.execution_plan.workflow_id == project.id
    assert compiled.execution_plan.scientific_definitions == (
        committed.scientific_definitions
    )


def test_public_synthetic_scorer_commit_requires_candidate_input(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    monkeypatch.setenv("PROTEIN_WORKBENCH_DATA_ROOT", str(tmp_path))
    catalog = build_frozen_catalog((SYNTHETIC_ECHO_PACKAGE,))
    case = SYNTHETIC_ECHO_EXECUTION_CASE
    app = create_application(frozen_catalog_override=catalog)

    with TestClient(app) as client:
        project_id = client.post(
            "/api/v2/projects",
            json={"name": "synthetic scorer requires Candidate input"},
        ).json()["id"]
        workflow = WorkflowDocument(
            schema_version="2.1.0",
            workflow_id=project_id,
            nodes=(
                WorkflowNodeInstance(
                    node_id="scorer",
                    node_type_id=case.node_type_id,
                    binding_id=case.binding_id,
                    node_parameters=dict(case.node_parameters),
                    binding_parameters=dict(case.binding_parameters),
                ),
            ),
            edges=(),
        )
        response = client.post(
            f"/api/v2/projects/{project_id}/workflow:commit",
            json={
                "workflow": encode_workflow_document(workflow),
            },
        )

    assert response.status_code == 422
    payload = response.json()
    validate_error(payload, status=422)
    assert payload["error"]["code"] == "compile_rejected"
    assert payload["error"]["details"]["issues"][0] == {
        "code": "required_input_missing",
        "message": "Required input Port 'candidate_input' is not connected",
        "node_id": "scorer",
        "field_path": ["nodes", 0],
        "severity": "error",
    }


def test_sequential_commits_keep_draft_lineage_and_distinct_ids(tmp_path) -> None:
    projects = ProjectManager(tmp_path / "projects")
    project = projects.create("idempotent commit")
    authoring = WorkflowAuthoringService(projects, _catalog())
    workflow = _workflow(project.id)

    first = authoring.commit(
        project.id,
        workflow=workflow,
    )
    second = authoring.commit(
        project.id,
        workflow=workflow,
    )

    assert first.source_draft_revision == 1
    assert second.source_draft_revision == 2
    assert first.workflow_commit_id != second.workflow_commit_id


def test_restart_hydrates_the_active_commit_plan(tmp_path) -> None:
    project_root = tmp_path / "projects"
    projects = ProjectManager(project_root)
    project = projects.create("restart hydration")
    catalog = _catalog()
    authoring = WorkflowAuthoringService(projects, catalog)
    committed = authoring.commit(
        project.id,
        workflow=_workflow(project.id),
    )

    restarted = WorkflowAuthoringService(
        ProjectManager(project_root),
        catalog,
    )
    compiled = restarted.require_verified_commit(
        project.id,
        workflow_commit_id=committed.workflow_commit_id,
    )

    assert compiled.commit == committed
    assert compiled.execution_plan.workflow_id == project.id
    assert compiled.execution_plan.scientific_definitions == (
        committed.scientific_definitions
    )


def test_restart_rejects_commit_from_changed_scientific_definition(
    tmp_path,
) -> None:
    project_root = tmp_path / "projects"
    projects = ProjectManager(project_root)
    project = projects.create("changed scientific definition")
    committed = WorkflowAuthoringService(
        projects,
        _catalog("original-science"),
    ).commit(
        project.id,
        workflow=_workflow(project.id),
    )

    restarted = WorkflowAuthoringService(
        ProjectManager(project_root),
        _catalog("changed-science"),
    )
    with pytest.raises(WorkflowAuthoringError) as raised:
        restarted.require_verified_commit(
            project.id,
            workflow_commit_id=committed.workflow_commit_id,
        )

    assert raised.value.code == "workflow_commit_identity_mismatch"
    assert raised.value.details == {
        "workflow_commit_id": committed.workflow_commit_id,
    }


def test_draft_preserves_uncompiled_values_and_commit_rejects_unknown_parameters(
    tmp_path,
) -> None:
    projects = ProjectManager(tmp_path / "projects")
    project = projects.create("uncompiled draft")
    authoring = WorkflowAuthoringService(projects, _catalog())
    payload = encode_workflow_document(_workflow(project.id))
    payload["nodes"][0]["node_parameters"] = {"undeclared": 1}

    workflow = decode_workflow_document(payload)
    draft = authoring.save_draft(project.id, workflow=workflow)

    assert draft.workflow == workflow
    with pytest.raises(WorkflowAuthoringError) as captured:
        authoring.commit(project.id, workflow=workflow)

    assert captured.value.code == "compile_rejected"
    assert captured.value.details["issues"][0]["code"] == "unknown_parameter"


def test_new_invalid_draft_and_failed_commit_keep_active_plan(tmp_path) -> None:
    projects = ProjectManager(tmp_path / "projects")
    project = projects.create("retained active commit")
    authoring = WorkflowAuthoringService(projects, _catalog())
    active = authoring.commit(
        project.id,
        workflow=_workflow(project.id),
    )

    retained_before_failure = authoring.require_verified_commit(
        project.id,
        workflow_commit_id=active.workflow_commit_id,
    )
    invalid_workflow = _workflow(project.id, invalid_edge=True)
    with pytest.raises(WorkflowAuthoringError) as captured:
        authoring.commit(
            project.id,
            workflow=invalid_workflow,
        )

    assert captured.value.code == "compile_rejected"
    assert authoring.load_active_commit(project.id) == active
    retained_after_failure = authoring.require_verified_commit(
        project.id,
        workflow_commit_id=active.workflow_commit_id,
    )
    assert retained_after_failure is retained_before_failure
    failed_draft = authoring.load_draft(project.id)
    assert failed_draft.draft_revision == 2
    assert failed_draft.workflow == invalid_workflow


def test_deep_commit_submits_draft_and_returns_frozen_typed_values(
    tmp_path,
) -> None:
    projects = ProjectManager(tmp_path / "projects")
    project = projects.create("single deep commit")
    authoring = WorkflowAuthoringService(projects, _catalog())
    workflow = _workflow(project.id)

    committed = authoring.commit(
        project.id,
        workflow=workflow,
    )

    draft = authoring.load_draft(project.id)
    assert isinstance(draft, WorkflowDraft)
    assert draft.draft_revision == 1
    assert draft.workflow == workflow
    assert isinstance(committed, WorkflowCommit)
    assert committed.source_draft_revision == draft.draft_revision
    assert committed.workflow == draft.workflow
    assert committed.scientific_definitions
    with pytest.raises(FrozenInstanceError):
        draft.draft_revision = 2
    with pytest.raises(FrozenInstanceError):
        committed.source_draft_revision = 2


def test_commit_publish_failure_keeps_old_active_and_saved_submission(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    projects = ProjectManager(tmp_path / "projects")
    project = projects.create("durable publish failure")
    authoring = WorkflowAuthoringService(projects, _catalog())
    active = authoring.commit(
        project.id,
        workflow=_workflow(project.id),
    )
    submitted = _workflow(project.id, node_id="replacement-source")
    real_write = workflow_authoring.write_new_file

    def fail_commit_record(root, relative_parts, payload):
        if relative_parts[0] == "commits":
            raise OSError("simulated durable publish failure")
        return real_write(
            root,
            relative_parts,
            payload,
        )

    with monkeypatch.context() as scoped:
        scoped.setattr(
            workflow_authoring,
            "write_new_file",
            fail_commit_record,
        )
        with pytest.raises(OSError, match="durable publish failure"):
            authoring.commit(
                project.id,
                workflow=submitted,
            )

    assert authoring.load_active_commit(project.id) == active
    assert authoring.load_draft(project.id).workflow == submitted
    retained = authoring.require_verified_commit(
        project.id,
        workflow_commit_id=active.workflow_commit_id,
    )
    assert retained.commit == active
    assert retained.execution_plan.workflow_id == project.id


def test_durable_workflow_codec_round_trips_the_canonical_projection() -> None:
    workflow = _workflow("project-1")
    payload = workflow.canonical_projection()

    constructed = workflow_document_from_canonical(payload)

    assert constructed == workflow
    assert constructed.canonical_projection() == payload


def test_seed_install_uses_the_current_draft_and_commit_owners(
    tmp_path,
) -> None:
    project_root = tmp_path / "projects"
    projects = ProjectManager(project_root)
    catalog = _catalog()
    workflow = _workflow(CANONICAL_3GB1_PROJECT_ID)
    authoring = WorkflowAuthoringService(projects, catalog)

    committed = authoring.install_seed_commit(
        workflow=workflow,
        input_sources={},
    )
    assert committed is not None

    assert authoring.load_draft(CANONICAL_3GB1_PROJECT_ID).workflow == (
        workflow
    )
    assert authoring.load_active_commit(
        CANONICAL_3GB1_PROJECT_ID
    ) == committed
    restarted = WorkflowAuthoringService(
        ProjectManager(project_root),
        catalog,
    )
    assert restarted.install_seed_commit(
        workflow=workflow,
        input_sources={},
    ) == committed
    verified = restarted.require_verified_commit(
        CANONICAL_3GB1_PROJECT_ID,
        workflow_commit_id=committed.workflow_commit_id,
    )
    assert verified.commit == committed
    assert verified.execution_plan.workflow_id == CANONICAL_3GB1_PROJECT_ID
