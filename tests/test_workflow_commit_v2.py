"""Behavioral tests for the deep Workflow Commit authoring seam."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import datetime, timezone
import json

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

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
from core.operation import (
    OperationContext,
    ReadinessResult,
)
from core.parameters.contract import admit_declarations
from core.workflow.authoring import (
    WorkflowAuthoringError,
    WorkflowAuthoringService,
)
from core.workflow.compiler import (
    CompilationRequest,
    compile,
    lock_workflow,
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
from core.scoring.selection import ObservationSelector, SelectionInput
from core.project.manager import CANONICAL_3GB1_PROJECT_ID
from protein_workbench_public.bootstrap import create_application
from core.workflow.authoring import (
    WorkflowCommit,
    WorkflowDraft,
)
from core.workflow.document import (
    WorkflowEdge,
    workflow_document_from_canonical,
)
from datatypes.exact_reference import ExactContractReference
from datatypes.observation import IntrinsicObservationContext
from tests.support.catalog import (
    binding_availability,
    catalog_contract,
    install_runtime,
)
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
    return catalog_contract(
        contract_kind,
        contract_id,
        "2.1.0",
        {
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
            "execution_route": "direct",
            "deterministic": True,
            "cacheable": True,
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
    observed_at = datetime(2026, 8, 3, tzinfo=timezone.utc)
    return FrozenCatalog(
        builtin.port_types,
        contracts=install_runtime(
            (method, node, binding),
            factories={(binding.contract_id, "2.1.0"): factory},
            readiness={(binding.contract_id, "2.1.0"): readiness},
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
                node_type_version="5.0.0",
                binding_id="selection.filter.direct",
                binding_version="5.0.0",
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
                source_partition="default",
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
        workflow=workflow,
    )

    assert encode_workflow_draft(saved) == {
        "project_id": project.id,
        "draft_revision": 1,
        "draft_digest": workflow.digest,
        "workflow": encode_workflow_document(workflow),
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
        workflow=workflow,
    )

    draft = authoring.load_draft(project.id)
    assert committed == authoring.load_active_commit(project.id)
    assert committed.workflow_commit_revision == 1
    assert committed.source_draft_revision == 1
    assert committed.source_draft_digest == draft.draft_digest
    assert committed.workflow_commit_id.startswith("workflow-commit-")
    assert committed.catalog_contract_digest == catalog.contract_digest
    receipt = encode_workflow_commit_receipt(committed)
    assert receipt["issues"] == []
    assert "compile_id" not in receipt

    compiled = authoring.require_verified_commit(
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
        restarted.require_verified_commit(
            project.id,
            workflow_commit_id=committed.workflow_commit_id,
        ).execution_plan.execution_plan_digest
        == committed.execution_plan_digest
    )


def test_sequential_commits_publish_sequential_revisions(tmp_path) -> None:
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

    assert first.workflow_commit_revision == 1
    assert first.source_draft_revision == 1
    assert second.workflow_commit_revision == 2
    assert second.source_draft_revision == 2


def test_restart_hydrates_the_exact_active_commit_plan(tmp_path) -> None:
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


def test_draft_preserves_uncompiled_values_and_commit_rejects_unknown_parameters(
    tmp_path,
) -> None:
    projects = ProjectManager(tmp_path / "projects")
    project = projects.create("credential-free draft")
    authoring = WorkflowAuthoringService(projects, _catalog())
    payload = encode_workflow_document(_workflow(project.id))
    payload["nodes"][0]["node_parameters"] = {
        "credentials": {"api_key": "must-not-enter-workflow"},
    }

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
    compiled = authoring.require_verified_commit(
        project.id,
        workflow_commit_id=committed.workflow_commit_id,
    )
    assert (
        compiled.execution_plan.execution_plan_digest
        == committed.execution_plan_digest
    )


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
    assert authoring.require_verified_commit(
        project.id,
        workflow_commit_id=active.workflow_commit_id,
    ).execution_plan.execution_plan_digest == active.execution_plan_digest


def test_event_stream_rejects_duplicate_query_parameters(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    for name in ("PROJECT", "CACHE", "OUTPUT", "RUN"):
        monkeypatch.setenv(
            f"PROTEIN_WORKBENCH_{name}_ROOT",
            str(tmp_path / name.lower()),
        )
    app = create_application(frozen_catalog_override=_catalog())

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
    app = create_application(frozen_catalog_override=_catalog())

    with TestClient(app) as client:
        def fail_replay(*_args, **_kwargs):
            raise RuntimeError("private replay failure detail")

        monkeypatch.setattr(
            client.app.state.run_runtime,
            "replay",
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
        restarted.require_verified_commit(
            project.id,
            workflow_commit_id=committed.workflow_commit_id,
        )

    assert captured.value.code == "contract_digest_mismatch"
    assert commit_path.read_bytes() == original_bytes


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
    unlocked = _workflow(CANONICAL_3GB1_PROJECT_ID)
    locked = lock_workflow(unlocked, catalog)
    authoring = WorkflowAuthoringService(projects, catalog)

    committed = authoring.install_seed_commit(
        locked_workflow=locked,
        input_sources={},
    )
    assert committed is not None

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
    assert restarted.require_verified_commit(
        CANONICAL_3GB1_PROJECT_ID,
        workflow_commit_id=committed.workflow_commit_id,
    ).execution_plan.execution_plan_digest == committed.execution_plan_digest
