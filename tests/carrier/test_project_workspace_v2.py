"""Current Project authoring, history, copy, and lifecycle contracts."""

from __future__ import annotations

from pathlib import Path
from dataclasses import replace
from typing import Any, Mapping

import pytest
from fastapi.testclient import TestClient

import core.workflow.authoring as authoring_module
from core.catalog.builder import build_frozen_catalog
from core.project.manager import ProjectManager, ProjectStateError
from core.workflow.authoring import WorkflowAuthoringError, WorkflowAuthoringService
from core.workflow.document import WorkflowDocument, WorkflowEdge, WorkflowNodeInstance
from modules.protein_io.package import MODULE_PACKAGE as PROTEIN_IO_PACKAGE
from tests.support.application import create_application
from tests.support.protocol import validate_response


def _draft(project_id: str, *, input_ref: str = "input-used") -> WorkflowDocument:
    return WorkflowDocument(
        "2.1.0", project_id,
        (WorkflowNodeInstance(
            "import", "protein_io.import_sequence", "protein_io.import_sequence.direct",
            {"project_input_ref": input_ref}, {},
        ),), (), (), (),
    )


def _authoring(root: Path) -> tuple[ProjectManager, WorkflowAuthoringService]:
    projects = ProjectManager(root)
    return projects, WorkflowAuthoringService(
        projects, build_frozen_catalog((PROTEIN_IO_PACKAGE,)),
    )


def test_named_incomplete_draft_fork_and_return_preserve_exact_ui_after_restart(
    tmp_path: Path,
) -> None:
    projects, authoring = _authoring(tmp_path)
    project = projects.create("history")
    original = _draft(project.id)
    incomplete = WorkflowDocument(
        original.schema_version, original.workflow_id, original.nodes,
        (WorkflowEdge("missing", "sequence", "import", "missing"),), (), (),
    )
    first = authoring.save_workspace(project.id, workflow=incomplete).draft
    named_workspace = authoring.save_workspace(
        project.id, ui_state={"positions": {"import": {"x": 30, "y": 70}}},
    )
    version = authoring.name_version(project.id, name="Unfinished proposal")
    assert version.draft_revision == first.draft_revision
    authoring.save_workspace(project.id, workflow=original)
    prior_work = authoring.save_workspace(project.id, ui_state={"positions": {"import": {"x": 90, "y": 50}}})

    _, restarted = _authoring(tmp_path)
    viewed = restarted.load_workspace(project.id, revision=version.workspace_revision)
    assert viewed == named_workspace
    assert restarted.load_workspace(project.id) == prior_work
    fork = restarted.fork_version(
        project.id, version_id=version.version_id,
        return_workspace_revision=prior_work.workspace_revision,
        workflow=incomplete, ui_state={"positions": {"import": {"x": 200, "y": 20}}},
    )
    assert fork.draft is not None
    assert fork.draft.draft_revision > prior_work.draft.draft_revision
    assert fork.source_version_id == version.version_id
    assert fork.return_workspace_revision == prior_work.workspace_revision
    returned = restarted.return_workspace(
        project.id, workspace_revision=fork.return_workspace_revision,
    )
    assert returned.draft == prior_work.draft
    assert returned.ui_state == prior_work.ui_state
    assert restarted.load_workspace(project.id, revision=fork.workspace_revision) == fork
    assert restarted.load_version(project.id, version.version_id) == version
    assert restarted.load_draft(project.id) == prior_work.draft


def test_failed_workspace_publication_keeps_the_previous_current_draft(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    projects, authoring = _authoring(tmp_path)
    project = projects.create("atomic head")
    original = authoring.save_workspace(project.id, workflow=_draft(project.id)).draft
    real_write = authoring_module.write_new_file

    def fail_workspace(root, parts, payload):
        if parts[0] == "workspaces":
            raise OSError("workspace publication interrupted")
        return real_write(root, parts, payload)

    with monkeypatch.context() as scoped:
        scoped.setattr(authoring_module, "write_new_file", fail_workspace)
        with pytest.raises(OSError, match="publication interrupted"):
            authoring.save_workspace(project.id, workflow=_draft(project.id, input_ref="different"))
    _, restarted = _authoring(tmp_path)
    assert restarted.load_draft(project.id) == original
    saved = restarted.save_workspace(project.id, workflow=_draft(project.id, input_ref="next")).draft
    assert saved.draft_revision == 3


def test_complete_edit_publishes_workflow_and_ui_once_and_ui_only_reuses_draft(
    tmp_path: Path,
) -> None:
    projects, authoring = _authoring(tmp_path)
    project = projects.create("coherent edit")
    first = authoring.save_workspace(
        project.id, workflow=_draft(project.id), ui_state={"zoom": 1},
    )
    assert first.draft is not None
    saved = authoring.save_workspace(
        project.id, workflow=_draft(project.id, input_ref="edited"),
        ui_state={"zoom": 2}, expected_draft_revision=first.draft.draft_revision,
    )
    assert saved.draft is not None
    assert saved.workspace_revision == first.workspace_revision + 1
    assert saved.draft.draft_revision == first.draft.draft_revision + 1
    assert saved.ui_state_revision == first.ui_state_revision + 1
    assert saved.draft.workflow.nodes[0].node_parameters["project_input_ref"] == "edited"
    assert saved.ui_state == {"zoom": 2}
    layout = authoring.save_workspace(project.id, ui_state={"zoom": 3})
    assert layout.draft == saved.draft
    assert layout.workspace_revision == saved.workspace_revision + 1
    assert authoring.load_draft(project.id) == saved.draft


@pytest.mark.parametrize("failed_collection", ["ui-states", "workspaces"])
def test_complete_edit_failure_before_publication_preserves_head_and_written_content(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failed_collection: str,
) -> None:
    projects, authoring = _authoring(tmp_path)
    project = projects.create("coherent edit failure")
    previous = authoring.save_workspace(project.id, workflow=_draft(project.id), ui_state={"zoom": 1})
    write_record = authoring._write_record

    def interrupted(project_id: str, collection: str, revision: int, payload: Mapping[str, Any]) -> None:
        if collection == failed_collection:
            raise OSError("publication interrupted")
        write_record(project_id, collection, revision, payload)

    with monkeypatch.context() as scoped:
        scoped.setattr(authoring, "_write_record", interrupted)
        with pytest.raises(OSError, match="publication interrupted"):
            authoring.save_workspace(project.id, workflow=_draft(project.id, input_ref="failed"), ui_state={"zoom": 2})
    _, restarted = _authoring(tmp_path)
    assert restarted.load_workspace(project.id) == previous
    saved = restarted.save_workspace(project.id, workflow=_draft(project.id, input_ref="retry"), ui_state={"zoom": 3})
    assert saved.draft is not None
    assert saved.draft.draft_revision == 3
    assert saved.ui_state_revision == (2 if failed_collection == "ui-states" else 3)
    assert saved.workspace_revision == previous.workspace_revision + 1


def test_touch_failure_after_publication_keeps_complete_current_workspace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    projects, authoring = _authoring(tmp_path)
    project = projects.create("published edit")
    previous = authoring.save_workspace(project.id, workflow=_draft(project.id), ui_state={"zoom": 1})

    def fail_touch(_project_id: str) -> None:
        raise OSError("metadata touch interrupted")

    with monkeypatch.context() as scoped:
        scoped.setattr(projects, "touch", fail_touch)
        with pytest.raises(OSError, match="metadata touch interrupted"):
            authoring.save_workspace(project.id, workflow=_draft(project.id, input_ref="published"), ui_state={"zoom": 2})
    _, restarted = _authoring(tmp_path)
    saved = restarted.load_workspace(project.id)
    assert saved.workspace_revision == previous.workspace_revision + 1
    assert saved.draft is not None
    assert saved.draft.workflow.nodes[0].node_parameters["project_input_ref"] == "published"
    assert saved.ui_state == {"zoom": 2}


@pytest.mark.parametrize(
    ("operation", "failed_collection", "next_ui_revision"),
    [("ui", "workspaces", 3), ("fork", "ui-states", 2), ("fork", "workspaces", 3)],
)
def test_interrupted_workspace_edit_keeps_head_and_never_reuses_written_revisions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    operation: str, failed_collection: str, next_ui_revision: int,
) -> None:
    projects, authoring = _authoring(tmp_path)
    project = projects.create("interrupted edit")
    authoring.save_workspace(project.id, workflow=_draft(project.id))
    previous = authoring.save_workspace(project.id, ui_state={"zoom": 1})
    version = authoring.name_version(project.id, name="Original")
    write_record = authoring._write_record

    def interrupted_write(
        project_id: str, collection: str, revision: int, payload: Mapping[str, Any],
    ) -> None:
        if collection == failed_collection:
            raise OSError("edit interrupted")
        write_record(project_id, collection, revision, payload)

    with monkeypatch.context() as scoped:
        scoped.setattr(authoring, "_write_record", interrupted_write)
        with pytest.raises(OSError, match="edit interrupted"):
            if operation == "ui":
                authoring.save_workspace(project.id, ui_state={"zoom": 2})
            else:
                authoring.fork_version(
                    project.id, version_id=version.version_id,
                    return_workspace_revision=previous.workspace_revision,
                    workflow=_draft(project.id, input_ref="interrupted"), ui_state={"zoom": 2},
                )

    _, restarted = _authoring(tmp_path)
    assert restarted.load_workspace(project.id) == previous
    if operation == "ui":
        saved = restarted.save_workspace(project.id, ui_state={"zoom": 3})
        assert saved.draft == previous.draft
    else:
        saved = restarted.fork_version(
            project.id, version_id=version.version_id,
            return_workspace_revision=previous.workspace_revision,
            workflow=_draft(project.id, input_ref="completed"), ui_state={"zoom": 3},
        )
        assert saved.draft is not None
        assert saved.draft.draft_revision == 3
    assert saved.ui_state_revision == next_ui_revision
    assert saved.ui_state == {"zoom": 3}
    assert restarted.load_workspace(project.id) == saved


@pytest.mark.parametrize("operation", ["ui", "fork"])
def test_published_ui_is_deeply_immutable_and_detached_from_submitted_content(
    tmp_path: Path, operation: str,
) -> None:
    projects, authoring = _authoring(tmp_path)
    project = projects.create("immutable published UI")
    authoring.save_workspace(project.id, workflow=_draft(project.id))
    previous = authoring.load_workspace(project.id)
    version = authoring.name_version(project.id, name="Original")
    positions = {"x": 10}
    collapsed = ["import"]
    ui: dict[str, Any] = {"positions": {"import": positions}, "collapsed": collapsed}
    if operation == "ui":
        published = authoring.save_workspace(project.id, ui_state=ui)
    else:
        published = authoring.fork_version(
            project.id, version_id=version.version_id,
            return_workspace_revision=previous.workspace_revision,
            workflow=_draft(project.id), ui_state=ui,
        )

    with pytest.raises(TypeError):
        published.ui_state["positions"]["import"]["x"] = 20
    with pytest.raises(TypeError):
        published.ui_state["collapsed"][0] = "changed"
    positions["x"] = 30
    collapsed.append("another node")
    ui["new field"] = True
    assert published.ui_state["positions"]["import"]["x"] == 10
    assert published.ui_state["collapsed"] == ("import",)
    assert "new field" not in published.ui_state
    _, restarted = _authoring(tmp_path)
    assert restarted.load_workspace(project.id) == published


def test_expected_draft_revision_after_return_uses_current_head_not_largest_revision(
    tmp_path: Path,
) -> None:
    projects, authoring = _authoring(tmp_path)
    project = projects.create("return then edit")
    first = authoring.save_workspace(project.id, workflow=_draft(project.id)).draft
    retained = authoring.load_workspace(project.id)
    later = authoring.save_workspace(project.id, workflow=_draft(project.id, input_ref="later")).draft
    returned = authoring.return_workspace(project.id, workspace_revision=retained.workspace_revision)
    assert returned.draft == first

    with pytest.raises(WorkflowAuthoringError) as raised:
        authoring.save_workspace(
            project.id, workflow=_draft(project.id, input_ref="wrong revision"),
            expected_draft_revision=later.draft_revision,
        )
    assert raised.value.code == "malformed_request"
    assert raised.value.details == {"field_path": ["expected_draft_revision"]}
    assert authoring.load_workspace(project.id) == returned

    saved = authoring.save_workspace(
        project.id, workflow=_draft(project.id, input_ref="new edit"),
        expected_draft_revision=first.draft_revision,
    ).draft
    assert saved.draft_revision == later.draft_revision + 1
    assert authoring.load_draft(project.id) == saved


def test_duplicate_copies_required_inputs_and_ui_without_versions_runs_or_cache(
    tmp_path: Path,
) -> None:
    projects, authoring = _authoring(tmp_path)
    source = projects.create("source")
    for ref in ("input-used", "input-unused"):
        projects.publish_input(source.id, ref, b">source\nACDE\n", filename=f"{ref}.fa")
    authoring.save_workspace(source.id, workflow=_draft(source.id))
    source_workspace = authoring.save_workspace(source.id, ui_state={"collapsed": ["import"]})
    authoring.name_version(source.id, name="source history")
    for root in (projects.run_storage_root(source.id), projects.result_cache_storage_root(source.id)):
        root.mkdir(parents=True)
        (root / "retained-evidence").write_text("source only")

    duplicate = authoring.duplicate_project(source.id, name="independent copy")
    assert duplicate.copied_from_project_id == source.id
    assert duplicate.reference_results_project_id is None
    copied = authoring.load_workspace(duplicate.id)
    assert copied.ui_state == source_workspace.ui_state
    assert copied.draft.workflow.workflow_id == duplicate.id
    assert projects.stored_input_references(duplicate.id) == ("input-used",)
    assert projects.read_input(duplicate.id, "input-used") == projects.read_input(source.id, "input-used")
    assert authoring.list_versions(duplicate.id) == ()
    assert projects.stored_run_ids(duplicate.id) == ()
    assert not projects.result_cache_storage_root(duplicate.id).exists()
    assert authoring.load_workspace(source.id) == source_workspace
    projects.trash(source.id)
    projects.permanently_delete(source.id)
    assert projects.read_input(duplicate.id, "input-used")[1] == b">source\nACDE\n"


def test_failed_duplicate_cleans_target_and_retry_preserves_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    projects, authoring = _authoring(tmp_path)
    source = projects.create("copy source")
    projects.publish_input(source.id, "input-used", b">source\nACDE\n", filename="source.fa")
    authoring.save_workspace(source.id, workflow=_draft(source.id))
    previous = authoring.save_workspace(source.id, ui_state={"zoom": 2})
    metadata = projects.require_meta(source.id)
    write_record = authoring._write_record
    targets: list[str] = []

    def fail_target_workspace(
        project_id: str, collection: str, revision: int, payload: Mapping[str, Any],
    ) -> None:
        if project_id != source.id and collection == "workspaces":
            targets.append(project_id)
            assert projects.load_meta(project_id) is None
            raise OSError("copy publication interrupted")
        write_record(project_id, collection, revision, payload)

    with monkeypatch.context() as scoped:
        scoped.setattr(authoring, "_write_record", fail_target_workspace)
        with pytest.raises(OSError, match="copy publication interrupted"):
            authoring.duplicate_project(source.id, name="interrupted copy")
    assert len(targets) == 1
    assert not (tmp_path / targets[0]).exists()
    assert projects.list_projects() == (metadata,)
    assert authoring.load_workspace(source.id) == previous
    assert projects.read_input(source.id, "input-used")[1] == b">source\nACDE\n"

    duplicate = authoring.duplicate_project(source.id, name="completed copy")
    copied = authoring.load_workspace(duplicate.id)
    assert copied.ui_state == previous.ui_state
    assert copied.draft is not None
    assert copied.draft.workflow.workflow_id == duplicate.id
    assert projects.read_input(duplicate.id, "input-used")[1] == b">source\nACDE\n"
    assert authoring.load_workspace(source.id) == previous
    assert projects.require_meta(source.id) == metadata


def test_trash_restore_and_purge_cover_all_configured_project_scopes(tmp_path: Path) -> None:
    roots = {key: tmp_path / key for key in ("projects", "outputs", "runs", "cache")}
    projects = ProjectManager(
        roots["projects"], cache_root=roots["cache"],
        output_root=roots["outputs"], run_root=roots["runs"],
    )
    source = projects.create("old name")
    renamed = projects.rename(source.id, "new name")
    assert renamed.id == source.id
    for root in roots.values():
        own = root / source.id
        own.mkdir(parents=True, exist_ok=True)
        (own / "retained-content").write_text("science")
        other = root / "another-project"
        other.mkdir(parents=True)
        (other / "retained-content").write_text("unrelated")
    with pytest.raises(ProjectStateError, match="trashed"):
        projects.permanently_delete(source.id)
    deleted = projects.trash(source.id)
    assert deleted.deleted_at is not None
    assert projects.load_meta(source.id) is None
    assert projects.list_projects(deleted=True) == (deleted,)
    assert projects.list_projects() == ()
    restored = projects.restore(source.id)
    assert restored.id == source.id
    assert restored.name == "new name"
    assert restored.deleted_at is None
    assert all((root / source.id / "retained-content").read_text() == "science" for root in roots.values())
    projects.trash(source.id)
    projects.permanently_delete(source.id)
    assert all(not (root / source.id).exists() for root in roots.values())
    assert all((root / "another-project" / "retained-content").read_text() == "unrelated" for root in roots.values())


def test_public_workspace_history_and_idle_only_deletion(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PROTEIN_WORKBENCH_DATA_ROOT", str(tmp_path))
    app = create_application(frozen_catalog_override=build_frozen_catalog((PROTEIN_IO_PACKAGE,)))
    with TestClient(app) as http:
        project = http.post("/api/v2/projects", json={"name": "public workspace"}).json()
        prefix = f"/api/v2/projects/{project['id']}"
        first = http.get(f"{prefix}/workspace")
        validate_response("project_workspace", 200, first.json())
        assert first.json()["draft"] is None
        assert first.json()["ui_state_revision"] == 0
        draft = _draft(project["id"]).canonical_projection()
        layout = http.put(f"{prefix}/workspace", json={"workflow": draft, "ui_state": {"zoom": 1.2}})
        assert layout.status_code == 200
        named = http.post(f"{prefix}/versions", json={"name": "First"})
        validate_response("name_workflow_version", 201, named.json())
        version_id = named.json()["version_id"]
        before = http.get(f"{prefix}/workspace").json()
        viewed = http.get(f"{prefix}/versions/{version_id}")
        validate_response("workflow_version", 200, viewed.json())
        assert http.get(f"{prefix}/workspace").json() == before
        forked = http.post(f"{prefix}/versions/{version_id}:fork", json={
            "workflow": draft, "ui_state": {"zoom": 2},
            "return_workspace_revision": viewed.json()["return_workspace_revision"],
        })
        validate_response("fork_workflow_version", 200, forked.json())
        returned = http.post(f"{prefix}/workspace:return", json={
            "workspace_revision": forked.json()["return_workspace_revision"],
        })
        assert returned.json()["ui_state"] == {"zoom": 1.2}
        inputs = http.get(f"{prefix}/inputs")
        validate_response("list_project_inputs", 200, inputs.json())
        assert inputs.json()["inputs"] == []
        runtime = app.state.run_runtime
        runtime._reserve_project(project["id"])
        try:
            active_delete = http.post(f"{prefix}:trash")
            assert active_delete.status_code == 409
            assert active_delete.json()["error"]["code"] == "project_has_active_runs"
            assert http.get(f"{prefix}/workspace").status_code == 200
        finally:
            runtime._release_project(project["id"])
        deleted = http.post(f"{prefix}:trash")
        validate_response("trash_project", 200, deleted.json())
        assert http.get(f"{prefix}/workspace").status_code == 404
        assert http.get("/api/v2/projects/deleted").json()["projects"][0]["id"] == project["id"]
        assert http.post(f"{prefix}:restore").status_code == 200
        assert http.get(f"{prefix}/workspace").json()["ui_state"] == {"zoom": 1.2}
        assert http.post(f"{prefix}:trash").status_code == 200
        purged = http.delete(prefix)
        validate_response("delete_project", 200, purged.json())
        assert http.get("/api/v2/projects/deleted").json()["projects"] == []


def test_missing_retained_workspace_reports_its_identity(tmp_path: Path) -> None:
    projects, authoring = _authoring(tmp_path)
    project = projects.create("missing return point")
    with pytest.raises(WorkflowAuthoringError) as raised:
        authoring.return_workspace(project.id, workspace_revision=9)
    assert raised.value.code == "workspace_not_found"
    assert raised.value.details == {"resource_kind": "workspace", "resource_id": "9"}


def test_science_comparison_uses_immutable_input_content_instead_of_upload_identity(
    tmp_path: Path,
) -> None:
    projects, authoring = _authoring(tmp_path)
    project = projects.create("scientifically identical uploads")
    for reference in ("input-used", "another-upload"):
        projects.publish_input(project.id, reference, b">same\nACDE\n", filename=f"{reference}.fa")
    committed = authoring.commit(project.id, workflow=_draft(project.id))
    same_content = authoring.compare_commit_science(
        project.id, workflow_commit_id=committed.workflow_commit_id,
        workflow_project_id=project.id, workflow=_draft(project.id, input_ref="another-upload"),
    )
    assert same_content["status"] == "current"
    unavailable = authoring.compare_commit_science(
        project.id, workflow_commit_id=committed.workflow_commit_id,
        workflow_project_id=project.id, workflow=_draft(project.id, input_ref="missing-upload"),
    )
    assert unavailable["status"] == "unknown"
    assert unavailable["issues"][0]["code"] == "project_input_not_found"
    personal = projects.create("reference results in another Project")
    projects.publish_input(personal.id, "target-only", b">same\nACDE\n", filename="personal.fa")
    reference_comparison = authoring.compare_commit_science(
        project.id, workflow_commit_id=committed.workflow_commit_id,
        workflow_project_id=personal.id, workflow=_draft(personal.id, input_ref="target-only"),
    )
    assert reference_comparison["status"] == "current"
    assert reference_comparison["workflow_project_id"] == personal.id


def test_permanent_deletion_removes_terminal_run_from_current_runtime_queries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PROTEIN_WORKBENCH_DATA_ROOT", str(tmp_path))
    app = create_application(frozen_catalog_override=build_frozen_catalog((PROTEIN_IO_PACKAGE,)))
    with TestClient(app) as http:
        project = app.state.project_manager.create("published result deletion")
        app.state.project_manager.publish_input(project.id, "input-used", b">protein\nACDE\n", filename="input.fa")
        commit = app.state.workflow_authoring.commit(project.id, workflow=_draft(project.id))
        receipt = app.state.run_runtime.start(
            project.id, workflow_commit_id=commit.workflow_commit_id,
            client_request_id="delete-test-run",
        )
        prefix = f"/api/v2/projects/{project.id}"
        route = f"{prefix}/runs/{receipt['run_id']}"
        assert http.get(route).json()["status"] == "succeeded"
        assert http.post(f"{prefix}:trash").status_code == 200
        assert http.post(f"{prefix}:restore").status_code == 200
        assert http.get(route).json()["status"] == "succeeded"
        assert http.post(f"{prefix}:trash").status_code == 200
        assert http.delete(prefix).status_code == 200
        missing = http.get(route)
        assert missing.status_code == 404
        assert missing.json()["error"]["code"] == "run_not_found"


@pytest.mark.parametrize("operation", ["filter", "weighted_rank"])
def test_science_comparison_ignores_selector_and_objective_locator_renaming(
    tmp_path: Path, operation: str,
) -> None:
    from core.scoring.selection import ObservationSelector, SelectionInput, SelectionObjective
    from datatypes.exact_reference import ExactContractReference
    from datatypes.observation import IntrinsicObservationContext
    from modules.selection.package import MODULE_PACKAGE as SELECTION_PACKAGE
    from tests.fixtures.collection_ops_sources.package import MODULE_PACKAGE as SOURCE_PACKAGE

    catalog = build_frozen_catalog((SELECTION_PACKAGE, SOURCE_PACKAGE))
    projects = ProjectManager(tmp_path)
    project = projects.create("renamed selection locator")
    authoring = WorkflowAuthoringService(projects, catalog)
    selector = ObservationSelector(
        selector_id="original", candidate_input=SelectionInput("source", "candidates"),
        score_collection_input=SelectionInput("scorer", "scores"),
        source_partition="contract_test.partition.a",
        metric=ExactContractReference("metric", "contract_test.collection_ops_value"),
        method=ExactContractReference("method", "contract_test.collection_ops_scorer.method"),
        context_selector=IntrinsicObservationContext(), match_cardinality="exactly_one", missing_policy="error",
    )
    objective = SelectionObjective(
        objective_id="original", candidate_input=selector.candidate_input,
        score_collection_input=selector.score_collection_input,
        source_partition=selector.source_partition, metric=selector.metric, method=selector.method,
        context_selector=selector.context_selector,
        utility_transform=ExactContractReference("utility_transform", "contract_test.collection_ops_identity.a"),
        utility_parameters={}, weight=1, match_cardinality="exactly_one", missing_policy="error",
    )
    parameter = "selector_ids" if operation == "filter" else "objective_ids"
    parameters = (
        {parameter: ["original"], "out_of_scope_policy": "error", "expression": [{"selector_index": 0, "operator": ">=", "threshold": 0.25}]}
        if operation == "filter" else {parameter: ["original"], "tie_policy": "candidate_id_ascending"}
    )
    workflow = WorkflowDocument(
        "2.1.0", project.id,
        (
            WorkflowNodeInstance("source", "contract_test.collection_ops_source", "contract_test.collection_ops_source.a", {"candidate_count": 3}, {}),
            WorkflowNodeInstance("scorer", "contract_test.collection_ops_scorer", "contract_test.collection_ops_scorer.a", {}, {}),
            WorkflowNodeInstance("select", f"selection.{operation}", f"selection.{operation}.direct", parameters, {}),
        ),
        (
            WorkflowEdge("source", "candidates", "scorer", "candidates"),
            WorkflowEdge("source", "candidates", "select", "candidates"),
            WorkflowEdge("scorer", "scores", "select", "scores"),
        ),
        (selector,) if operation == "filter" else (),
        () if operation == "filter" else (objective,),
    )
    commit = authoring.commit(project.id, workflow=workflow)
    renamed = replace(
        workflow,
        nodes=(*workflow.nodes[:2], replace(workflow.nodes[2], node_parameters={**parameters, parameter: ["renamed"]})),
        observation_selectors=(replace(selector, selector_id="renamed"),) if operation == "filter" else (),
        selection_objectives=() if operation == "filter" else (replace(objective, objective_id="renamed"),),
    )
    assert authoring.compare_commit_science(
        project.id, workflow_commit_id=commit.workflow_commit_id,
        workflow_project_id=project.id, workflow=renamed,
    )["status"] == "current"


def test_workspace_revision_rejects_stale_save_after_layout_only_edit(tmp_path: Path) -> None:
    projects, authoring = _authoring(tmp_path)
    project = projects.create("layout conflict")
    first = authoring.save_workspace(
        project.id, workflow=_draft(project.id), ui_state={"zoom": 1},
    )
    updated = authoring.save_workspace(
        project.id, ui_state={"zoom": 2},
        expected_workspace_revision=first.workspace_revision,
    )
    assert updated.draft == first.draft
    with pytest.raises(WorkflowAuthoringError) as raised:
        authoring.save_workspace(
            project.id, workflow=_draft(project.id, input_ref="stale"),
            ui_state={"zoom": 1}, expected_workspace_revision=first.workspace_revision,
        )
    assert raised.value.details == {"field_path": ["expected_workspace_revision"]}
    assert authoring.load_workspace(project.id) == updated
