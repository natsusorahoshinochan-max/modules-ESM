"""Behavioral tests for the deep Workflow Commit authoring seam."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import FrozenInstanceError
from datetime import datetime, timezone
import json
from threading import Barrier, Event

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

import core.workflow_authoring_v2 as workflow_authoring_v2
from core import (
    BehaviorReference,
    CatalogContract,
    FrozenCatalog,
    ObservationSelector,
    OperationContext,
    ProjectManager,
    ReadinessDeclaration,
    ReadinessResult,
    ScientificOperationFactory,
    SelectionInput,
    WorkflowDocument,
    WorkflowNodeInstance,
    WorkflowAuthoringService,
    WorkflowAuthoringError,
    build_frozen_catalog,
    builtin_frozen_catalog,
    compile_workflow,
    parse_workflow_document,
    relock_workflow,
)
from core.project import CANONICAL_3GB1_PROJECT_ID
from core.server import create_app
from core.workflow_authoring_v2 import WorkflowCommit, WorkflowDraft
from core.workflow_v2 import WorkflowEdge, workflow_document_from_admitted_public
from datatypes import ExactContractReference, IntrinsicObservationContext
from modules.selection.package import MODULE_PACKAGE as SELECTION_PACKAGE
from protein_workbench_public import validate_error
from tests.fixtures.zero_core_packages.synthetic_echo.package import (
    MODULE_PACKAGE as SYNTHETIC_ECHO_PACKAGE,
)
from tests.fixtures.zero_core_packages.synthetic_echo.tests.cases import (
    EXECUTION_CASE as SYNTHETIC_ECHO_EXECUTION_CASE,
    SOURCE_EXECUTION_CASE as SYNTHETIC_SOURCE_EXECUTION_CASE,
)


def _contract(
    contract_kind: str,
    contract_id: str,
    descriptor: dict,
) -> CatalogContract:
    return CatalogContract(
        contract_kind=contract_kind,
        contract_id=contract_id,
        contract_version="2.1.0",
        descriptor={
            "schema_namespace": "protein-workbench-contract/v2",
            "contract_kind": contract_kind,
            "contract_id": contract_id,
            "contract_version": "2.1.0",
            **descriptor,
        },
    )


def _catalog(*, algorithm_name: str = "source") -> FrozenCatalog:
    builtin = builtin_frozen_catalog()
    text = builtin.require_port_type("text", "2.1.0")
    method = _contract(
        "method",
        "test.source.method",
        {"algorithm_identity": {"name": algorithm_name}},
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
            "binding_parameters": {},
            "produced_observations": [],
        },
    )
    factory = ScientificOperationFactory(
        behavior=BehaviorReference("test.source/factory", "2.1.0", {}),
        build=lambda _context: object(),
    )
    readiness = ReadinessDeclaration(
        behavior=BehaviorReference("test.source/readiness", "2.1.0", {}),
        prerequisites={},
        check=lambda _input: ReadinessResult(True),
    )
    return FrozenCatalog(
        builtin.port_types,
        contracts=(method, node, binding),
        availability=(
            {
                "binding": binding.reference(),
                "observed_at": "2026-08-03T00:00:00Z",
                "available": True,
            },
        ),
        availability_observed_at=datetime(
            2026,
            8,
            3,
            tzinfo=timezone.utc,
        ),
        factories={(binding.contract_id, "2.1.0"): factory},
        readiness_declarations={
            (binding.contract_id, "2.1.0"): readiness,
        },
    )


def _workflow(
    project_id: str,
    *,
    invalid_edge: bool = False,
    node_id: str = "source",
):
    return parse_workflow_document(
        {
            "schema_version": "2.1.0",
            "workflow_id": project_id,
            "nodes": [
                {
                    "node_id": node_id,
                    "node_type_id": "test.source",
                    "node_type_version": "2.1.0",
                    "binding_id": "test.source.direct",
                    "binding_version": "2.1.0",
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
            "contract_lock": [],
        }
    )


def _workflow_with_stale_nested_reference(
    project_id: str,
) -> tuple[FrozenCatalog, WorkflowDocument, ExactContractReference]:
    catalog = build_frozen_catalog(
        (SYNTHETIC_ECHO_PACKAGE, SELECTION_PACKAGE)
    )

    def reference(
        contract_kind: str,
        contract_id: str,
    ) -> ExactContractReference:
        return ExactContractReference(
            **catalog.require_contract(
                contract_kind,
                contract_id,
                "2.1.0",
            ).reference()
        )

    current_metric = reference(
        "metric",
        "contract_test.synthetic_identity",
    )
    stale_metric = ExactContractReference(
        contract_kind=current_metric.contract_kind,
        contract_id=current_metric.contract_id,
        contract_version=current_metric.contract_version,
        contract_digest="sha256:" + ("0" * 64),
    )
    workflow = WorkflowDocument(
        schema_version="2.1.0",
        workflow_id=project_id,
        nodes=(
            WorkflowNodeInstance(
                node_id="candidate-source",
                node_type_id=SYNTHETIC_SOURCE_EXECUTION_CASE.node_type_id,
                node_type_version=(
                    SYNTHETIC_SOURCE_EXECUTION_CASE.node_type_version
                ),
                binding_id=SYNTHETIC_SOURCE_EXECUTION_CASE.binding_id,
                binding_version=(
                    SYNTHETIC_SOURCE_EXECUTION_CASE.binding_version
                ),
                node_parameters={"message": "X"},
                binding_parameters={"repeat_count": 1},
            ),
            WorkflowNodeInstance(
                node_id="scorer",
                node_type_id=SYNTHETIC_ECHO_EXECUTION_CASE.node_type_id,
                node_type_version=(
                    SYNTHETIC_ECHO_EXECUTION_CASE.node_type_version
                ),
                binding_id=SYNTHETIC_ECHO_EXECUTION_CASE.binding_id,
                binding_version=SYNTHETIC_ECHO_EXECUTION_CASE.binding_version,
                node_parameters={"message": "X"},
                binding_parameters={"repeat_count": 1},
            ),
            WorkflowNodeInstance(
                node_id="select",
                node_type_id="selection.filter",
                node_type_version="4.0.0",
                binding_id="selection.filter.direct",
                binding_version="4.0.0",
                node_parameters={
                    "selector_id": "selector-1",
                    "operator": ">=",
                    "threshold": 0,
                },
                binding_parameters={},
            ),
        ),
        edges=(
            WorkflowEdge(
                "candidate-source",
                "candidates",
                "scorer",
                "candidate_input",
            ),
            WorkflowEdge(
                "candidate-source",
                "candidates",
                "select",
                "candidates",
            ),
            WorkflowEdge("scorer", "scores", "select", "scores"),
        ),
        contract_lock=(),
        observation_selectors=(
            ObservationSelector(
                selector_id="selector-1",
                candidate_input=SelectionInput(
                    "candidate-source", "candidates"
                ),
                score_collection_input=SelectionInput("scorer", "scores"),
                metric=stale_metric,
                method=reference(
                    "method",
                    "contract_test.synthetic_echo.method",
                ),
                context_selector=IntrinsicObservationContext(),
            ),
        ),
    )
    return catalog, workflow, current_metric


def test_invalid_unlocked_draft_can_be_saved_and_loaded(tmp_path) -> None:
    projects = ProjectManager(tmp_path / "projects")
    project = projects.create("invalid draft")
    authoring = WorkflowAuthoringService(projects, _catalog())
    workflow = _workflow(project.id, invalid_edge=True)

    saved = authoring.save_draft(
        project.id,
        expected_draft_revision=0,
        workflow=workflow,
    )

    assert saved.to_public() == {
        "project_id": project.id,
        "draft_revision": 1,
        "draft_digest": workflow.digest,
        "workflow": workflow.to_public(),
    }
    assert saved.workflow.contract_lock == ()
    assert authoring.load_draft(project.id) == saved


def test_commit_locks_compiles_and_activates_one_exact_draft(tmp_path) -> None:
    projects = ProjectManager(tmp_path / "projects")
    project = projects.create("commit draft")
    catalog = _catalog()
    authoring = WorkflowAuthoringService(projects, catalog)
    workflow = _workflow(project.id)

    committed = authoring.commit(
        project.id,
        expected_draft_revision=0,
        workflow=workflow,
    )

    draft = authoring.load_draft(project.id)
    assert committed == authoring.load_active_commit(project.id)
    assert committed.workflow_commit_revision == 1
    assert committed.source_draft_revision == 1
    assert committed.source_draft_digest == draft.draft_digest
    assert committed.workflow_commit_id.startswith("workflow-commit-")
    assert committed.catalog_contract_digest == catalog.contract_digest
    assert committed.to_public()["issues"] == []
    assert "compile_id" not in committed.to_public()

    compiled = authoring.require_compiled(
        project.id,
        workflow_commit_id=committed.workflow_commit_id,
    )
    assert compiled.execution_plan.workflow_commit_revision == 1
    assert compiled.execution_plan.workflow_digest == committed.workflow_digest
    assert (
        compiled.execution_plan.execution_plan_digest
        == committed.execution_plan_digest
    )
    assert compiled.execution_plan.resolved_contracts


def test_public_synthetic_scorer_commit_requires_candidate_input(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    for name in ("PROJECT", "CACHE", "OUTPUT", "RUN"):
        monkeypatch.setenv(
            f"PROTEIN_WORKBENCH_{name}_ROOT",
            str(tmp_path / name.lower()),
        )
    catalog = build_frozen_catalog((SYNTHETIC_ECHO_PACKAGE,))
    case = SYNTHETIC_ECHO_EXECUTION_CASE
    app = create_app(frozen_catalog_override=catalog)

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
                    node_type_version=case.node_type_version,
                    binding_id=case.binding_id,
                    binding_version=case.binding_version,
                    node_parameters=dict(case.node_parameters),
                    binding_parameters=dict(case.binding_parameters),
                ),
            ),
            edges=(),
            contract_lock=(),
        )
        response = client.post(
            f"/api/v2/projects/{project_id}/workflow:commit",
            json={
                "expected_draft_revision": 0,
                "workflow": workflow.to_public(),
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


def test_commit_relocks_nested_references_without_losing_draft_lineage(
    tmp_path,
) -> None:
    project_root = tmp_path / "projects"
    projects = ProjectManager(project_root)
    project = projects.create("nested reference relock")
    catalog, workflow, current_metric = _workflow_with_stale_nested_reference(
        project.id
    )
    authoring = WorkflowAuthoringService(projects, catalog)

    committed = authoring.commit(
        project.id,
        expected_draft_revision=0,
        workflow=workflow,
    )

    draft = authoring.load_draft(project.id)
    assert draft.workflow.observation_selectors[0].metric != current_metric
    assert committed.locked_workflow.observation_selectors[0].metric == (
        current_metric
    )
    assert authoring.load_active_commit(project.id) == committed
    restarted = WorkflowAuthoringService(
        ProjectManager(project_root),
        catalog,
    )
    assert restarted.load_active_commit(project.id) == committed
    assert (
        restarted.require_compiled(
            project.id,
            workflow_commit_id=committed.workflow_commit_id,
        ).execution_plan.execution_plan_digest
        == committed.execution_plan_digest
    )


def test_same_draft_and_catalog_commit_is_idempotent(tmp_path) -> None:
    projects = ProjectManager(tmp_path / "projects")
    project = projects.create("idempotent commit")
    authoring = WorkflowAuthoringService(projects, _catalog())
    workflow = _workflow(project.id)

    first = authoring.commit(
        project.id,
        expected_draft_revision=0,
        workflow=workflow,
    )
    second = authoring.commit(
        project.id,
        expected_draft_revision=0,
        workflow=workflow,
    )

    assert second == first
    assert second.workflow_commit_revision == 1


def test_concurrent_identical_commits_publish_once_and_share_identity(
    tmp_path,
) -> None:
    projects = ProjectManager(tmp_path / "projects")
    project = projects.create("concurrent commit")
    authoring = WorkflowAuthoringService(projects, _catalog())
    workflow = _workflow(project.id)
    ready = Barrier(2)

    def commit() -> WorkflowCommit:
        ready.wait()
        return authoring.commit(
            project.id,
            expected_draft_revision=0,
            workflow=workflow,
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _index: commit(), range(2)))

    assert results[0] == results[1]
    assert results[0].workflow_commit_revision == 1


def test_restart_hydrates_the_exact_active_commit_plan(tmp_path) -> None:
    project_root = tmp_path / "projects"
    projects = ProjectManager(project_root)
    project = projects.create("restart hydration")
    catalog = _catalog()
    authoring = WorkflowAuthoringService(projects, catalog)
    committed = authoring.commit(
        project.id,
        expected_draft_revision=0,
        workflow=_workflow(project.id),
    )

    restarted = WorkflowAuthoringService(
        ProjectManager(project_root),
        catalog,
    )
    compiled = restarted.require_compiled(
        project.id,
        workflow_commit_id=committed.workflow_commit_id,
    )

    assert (
        compiled.execution_plan.workflow_commit_revision
        == committed.workflow_commit_revision
    )
    assert compiled.execution_plan.workflow_digest == committed.workflow_digest
    assert (
        compiled.execution_plan.catalog_contract_digest
        == committed.catalog_contract_digest
    )
    assert (
        compiled.execution_plan.contract_lock_digest
        == committed.contract_lock_digest
    )
    assert (
        compiled.execution_plan.execution_plan_digest
        == committed.execution_plan_digest
    )


def test_draft_rejects_environment_configuration_fields(tmp_path) -> None:
    projects = ProjectManager(tmp_path / "projects")
    project = projects.create("credential-free draft")
    authoring = WorkflowAuthoringService(projects, _catalog())
    payload = _workflow(project.id).to_public()
    payload["nodes"][0]["node_parameters"] = {
        "credentials": {"api_key": "must-not-enter-workflow"},
    }

    with pytest.raises(WorkflowAuthoringError) as captured:
        authoring.save_draft(
            project.id,
            expected_draft_revision=0,
            workflow=parse_workflow_document(payload),
        )

    assert captured.value.code == "malformed_request"
    assert captured.value.details["field_path"] == [
        "workflow",
        "nodes",
        0,
        "node_parameters",
        "credentials",
    ]


def test_new_invalid_draft_and_failed_commit_keep_active_plan(tmp_path) -> None:
    projects = ProjectManager(tmp_path / "projects")
    project = projects.create("retained active commit")
    authoring = WorkflowAuthoringService(projects, _catalog())
    active = authoring.commit(
        project.id,
        expected_draft_revision=0,
        workflow=_workflow(project.id),
    )

    retained_before_failure = authoring.require_compiled(
        project.id,
        workflow_commit_id=active.workflow_commit_id,
    )
    invalid_workflow = _workflow(project.id, invalid_edge=True)
    with pytest.raises(WorkflowAuthoringError) as captured:
        authoring.commit(
            project.id,
            expected_draft_revision=1,
            workflow=invalid_workflow,
        )

    assert captured.value.code == "compile_rejected"
    assert authoring.load_active_commit(project.id) == active
    retained_after_failure = authoring.require_compiled(
        project.id,
        workflow_commit_id=active.workflow_commit_id,
    )
    assert retained_after_failure.execution_plan.execution_plan_digest == (
        retained_before_failure.execution_plan.execution_plan_digest
    )
    failed_draft = authoring.load_draft(project.id)
    assert failed_draft.draft_revision == 2
    assert failed_draft.workflow == invalid_workflow


def test_authoring_owner_has_no_shallow_transition_interface(tmp_path) -> None:
    projects = ProjectManager(tmp_path / "projects")
    authoring = WorkflowAuthoringService(projects, _catalog())

    assert not hasattr(authoring, "load")
    assert not hasattr(authoring, "save")
    assert not hasattr(authoring, "relock")
    assert not hasattr(authoring, "compile")


def test_concurrent_different_draft_saves_have_one_stable_conflict(
    tmp_path,
) -> None:
    projects = ProjectManager(tmp_path / "projects")
    project = projects.create("concurrent drafts")
    authoring = WorkflowAuthoringService(projects, _catalog())
    ready = Barrier(2)
    workflows = (
        _workflow(project.id),
        _workflow(project.id, invalid_edge=True),
    )

    def save(workflow) -> str:
        ready.wait()
        try:
            authoring.save_draft(
                project.id,
                expected_draft_revision=0,
                workflow=workflow,
            )
        except WorkflowAuthoringError as error:
            return error.code
        return "saved"

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(save, workflows))

    assert sorted(outcomes) == ["saved", "workflow_draft_revision_conflict"]
    assert authoring.load_draft(project.id).draft_revision == 1


def test_published_commit_and_plan_are_reused_without_catalog_resolution(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    projects = ProjectManager(tmp_path / "projects")
    project = projects.create("in-memory commit reuse")
    catalog = _catalog()
    authoring = WorkflowAuthoringService(projects, catalog)
    committed = authoring.commit(
        project.id,
        expected_draft_revision=0,
        workflow=_workflow(project.id),
    )

    def forbid_catalog_resolution(*_args, **_kwargs):
        raise AssertionError(
            "Published Workflow Commit execution must reuse its resolved Plan"
        )

    for method_name in (
        "get_contract",
        "require_contract",
        "require_port_type",
    ):
        monkeypatch.setattr(
            FrozenCatalog,
            method_name,
            forbid_catalog_resolution,
        )

    assert authoring.load_active_commit(project.id) == committed
    compiled = authoring.require_compiled(
        project.id,
        workflow_commit_id=committed.workflow_commit_id,
    )
    assert (
        compiled.execution_plan.execution_plan_digest
        == committed.execution_plan_digest
    )


def test_draft_read_and_publish_share_the_project_lock(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    projects = ProjectManager(tmp_path / "projects")
    project = projects.create("serialized draft read")
    authoring = WorkflowAuthoringService(projects, _catalog())
    first = authoring.save_draft(
        project.id,
        expected_draft_revision=0,
        workflow=_workflow(project.id),
    )
    read_entered = Event()
    release_read = Event()
    save_entered = Event()
    save_finished = Event()
    real_read_record = authoring._read_record

    def blocked_read_record(project_id, collection, revision):
        if collection == "drafts" and not read_entered.is_set():
            read_entered.set()
            assert release_read.wait(timeout=2)
        return real_read_record(project_id, collection, revision)

    monkeypatch.setattr(authoring, "_read_record", blocked_read_record)

    def save_replacement() -> WorkflowDraft:
        save_entered.set()
        try:
            return authoring.save_draft(
                project.id,
                expected_draft_revision=1,
                workflow=_workflow(project.id, node_id="replacement"),
            )
        finally:
            save_finished.set()

    with ThreadPoolExecutor(max_workers=2) as executor:
        read_future = executor.submit(authoring.load_draft, project.id)
        assert read_entered.wait(timeout=2)
        save_future = executor.submit(save_replacement)
        assert save_entered.wait(timeout=2)
        publish_overtook_read = save_finished.wait(timeout=0.1)
        release_read.set()

        assert not publish_overtook_read
        assert read_future.result(timeout=2) == first
        replacement = save_future.result(timeout=2)

    assert replacement.draft_revision == 2


def test_active_commit_read_and_publish_share_the_project_lock(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    projects = ProjectManager(tmp_path / "projects")
    project = projects.create("serialized commit read")
    authoring = WorkflowAuthoringService(projects, _catalog())
    first = authoring.commit(
        project.id,
        expected_draft_revision=0,
        workflow=_workflow(project.id),
    )
    read_entered = Event()
    release_read = Event()
    commit_entered = Event()
    commit_finished = Event()
    real_active_commit_locked = authoring._active_commit_locked

    def blocked_active_commit_locked(project_id):
        if not read_entered.is_set():
            read_entered.set()
            assert release_read.wait(timeout=2)
        return real_active_commit_locked(project_id)

    monkeypatch.setattr(
        authoring,
        "_active_commit_locked",
        blocked_active_commit_locked,
    )

    def commit_replacement() -> WorkflowCommit:
        commit_entered.set()
        try:
            return authoring.commit(
                project.id,
                expected_draft_revision=1,
                workflow=_workflow(project.id, node_id="replacement"),
            )
        finally:
            commit_finished.set()

    with ThreadPoolExecutor(max_workers=2) as executor:
        read_future = executor.submit(authoring.load_active_commit, project.id)
        assert read_entered.wait(timeout=2)
        commit_future = executor.submit(commit_replacement)
        assert commit_entered.wait(timeout=2)
        publish_overtook_read = commit_finished.wait(timeout=0.1)
        release_read.set()

        assert not publish_overtook_read
        assert read_future.result(timeout=2) == first
        replacement = commit_future.result(timeout=2)

    assert replacement.workflow_commit_revision == 2


def test_deep_commit_submits_draft_and_returns_frozen_typed_values(
    tmp_path,
) -> None:
    projects = ProjectManager(tmp_path / "projects")
    project = projects.create("single deep commit")
    authoring = WorkflowAuthoringService(projects, _catalog())
    workflow = _workflow(project.id)

    committed = authoring.commit(
        project.id,
        expected_draft_revision=0,
        workflow=workflow,
    )

    draft = authoring.load_draft(project.id)
    assert isinstance(draft, WorkflowDraft)
    assert draft.draft_revision == 1
    assert draft.workflow == workflow
    assert isinstance(committed, WorkflowCommit)
    assert committed.source_draft_revision == draft.draft_revision
    assert committed.source_draft_digest == draft.draft_digest
    assert committed.locked_workflow.contract_lock
    with pytest.raises(FrozenInstanceError):
        draft.draft_revision = 2
    with pytest.raises(FrozenInstanceError):
        committed.workflow_commit_revision = 2


def test_commit_publish_failure_keeps_old_active_and_saved_submission(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    projects = ProjectManager(tmp_path / "projects")
    project = projects.create("durable publish failure")
    authoring = WorkflowAuthoringService(projects, _catalog())
    active = authoring.commit(
        project.id,
        expected_draft_revision=0,
        workflow=_workflow(project.id),
    )
    submitted = _workflow(project.id, node_id="replacement-source")
    real_write = workflow_authoring_v2.write_new_file

    def fail_commit_record(root, relative_parts, payload):
        if relative_parts[1] == "commits":
            raise OSError("simulated durable publish failure")
        return real_write(
            root,
            relative_parts,
            payload,
        )

    with monkeypatch.context() as scoped:
        scoped.setattr(
            workflow_authoring_v2,
            "write_new_file",
            fail_commit_record,
        )
        with pytest.raises(OSError, match="durable publish failure"):
            authoring.commit(
                project.id,
                expected_draft_revision=1,
                workflow=submitted,
            )

    assert authoring.load_active_commit(project.id) == active
    assert authoring.load_draft(project.id).workflow == submitted
    assert authoring.require_compiled(
        project.id,
        workflow_commit_id=active.workflow_commit_id,
    ).execution_plan.execution_plan_digest == active.execution_plan_digest

    retried = authoring.commit(
        project.id,
        expected_draft_revision=1,
        workflow=submitted,
    )
    assert retried.workflow_commit_revision == 2
    assert retried.source_draft_revision == 2


def test_event_stream_rejects_duplicate_query_parameters(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    for name in ("PROJECT", "CACHE", "OUTPUT", "RUN"):
        monkeypatch.setenv(
            f"PROTEIN_WORKBENCH_{name}_ROOT",
            str(tmp_path / name.lower()),
        )
    app = create_app(frozen_catalog_override=_catalog())

    with TestClient(app) as client:
        with client.websocket_connect(
            "/api/v2/projects/project-1/runs/run-1/events"
            "?after_sequence=a&after_sequence=b"
        ) as websocket:
            payload = websocket.receive_json()
            with pytest.raises(WebSocketDisconnect) as closed:
                websocket.receive_json()

    assert payload["error"]["code"] == "malformed_request"
    assert payload["error"]["details"] == {
        "field_path": ["after_sequence"]
    }
    assert closed.value.code == 1008


def test_event_stream_maps_unexpected_failure_to_internal_error(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    for name in ("PROJECT", "CACHE", "OUTPUT", "RUN"):
        monkeypatch.setenv(
            f"PROTEIN_WORKBENCH_{name}_ROOT",
            str(tmp_path / name.lower()),
        )
    app = create_app(frozen_catalog_override=_catalog())

    with TestClient(app) as client:
        def fail_replay(*_args, **_kwargs):
            raise RuntimeError("private replay failure detail")

        monkeypatch.setattr(
            client.app.state.run_execution_v2,
            "replay_window",
            fail_replay,
        )
        with client.websocket_connect(
            "/api/v2/projects/project-1/runs/run-1/events"
        ) as websocket:
            payload = websocket.receive_json()
            with pytest.raises(WebSocketDisconnect) as closed:
                websocket.receive_json()

    validate_error(payload)
    assert payload["error"]["code"] == "internal_error"
    assert payload["error"]["message"] == "Internal server error"
    assert payload["error"]["details"]["incident_id"].startswith(
        "incident-"
    )
    assert "private replay failure detail" not in json.dumps(payload)
    assert closed.value.code == 1011


def test_restart_rejects_commit_from_a_different_catalog_generation(
    tmp_path,
) -> None:
    project_root = tmp_path / "projects"
    projects = ProjectManager(project_root)
    project = projects.create("catalog drift")
    committed = WorkflowAuthoringService(
        projects,
        _catalog(algorithm_name="generation-a"),
    ).commit(
        project.id,
        expected_draft_revision=0,
        workflow=_workflow(project.id),
    )
    commit_path = next(
        (project_root / project.id / "workflow-v2" / "commits").glob(
            "*.json"
        )
    )
    original_bytes = commit_path.read_bytes()

    restarted = WorkflowAuthoringService(
        ProjectManager(project_root),
        _catalog(algorithm_name="generation-b"),
    )
    with pytest.raises(WorkflowAuthoringError) as captured:
        restarted.require_compiled(
            project.id,
            workflow_commit_id=committed.workflow_commit_id,
        )

    assert captured.value.code == "contract_digest_mismatch"
    assert commit_path.read_bytes() == original_bytes


def test_admitted_workflow_constructor_matches_the_validating_parser() -> None:
    payload = _workflow("project-1").to_public()

    constructed = workflow_document_from_admitted_public(payload)

    assert constructed == parse_workflow_document(payload)
    assert constructed.to_public() == payload


def test_seed_install_uses_the_authoring_owner_and_no_legacy_workflow_file(
    tmp_path,
) -> None:
    project_root = tmp_path / "projects"
    projects = ProjectManager(project_root)
    catalog = _catalog()
    unlocked = _workflow(CANONICAL_3GB1_PROJECT_ID)
    locked = relock_workflow(unlocked, catalog)
    authoring = WorkflowAuthoringService(projects, catalog)

    committed = authoring.install_seed_commit(
        locked_workflow=locked,
        input_sources={},
    )
    assert committed is not None

    seed_dir = project_root / CANONICAL_3GB1_PROJECT_ID
    assert not (seed_dir / "workflow-v2.json").exists()
    assert authoring.load_draft(CANONICAL_3GB1_PROJECT_ID).workflow == (
        unlocked
    )
    assert authoring.load_active_commit(
        CANONICAL_3GB1_PROJECT_ID
    ) == committed
    restarted = WorkflowAuthoringService(
        ProjectManager(project_root),
        catalog,
    )
    assert restarted.install_seed_commit(
        locked_workflow=locked,
        input_sources={},
    ) == committed
    assert restarted.require_compiled(
        CANONICAL_3GB1_PROJECT_ID,
        workflow_commit_id=committed.workflow_commit_id,
    ).execution_plan.execution_plan_digest == committed.execution_plan_digest
