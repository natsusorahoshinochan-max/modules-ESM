"""Complete Project lifecycle operations through Run Runtime."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
import threading

import pytest

import core.project.manager as manager_module
from core.catalog.builder import build_frozen_catalog
from core.execution._run_runtime_evidence import plan_evidence
from core.execution._run_runtime_models import _RunRecord
from core.execution.ledger import Ledger, RunAdmitted, RunScopeBinding, V2RunError
from core.execution.runtime import V2RunService
from core.project.manager import (
    CANONICAL_3GB1_PROJECT_ID,
    WEBUI_3GB1_PROJECT_ID,
    ProjectManager,
    ProjectStateError,
    ProtectedProjectError,
)
from core.workflow.authoring import WorkflowAuthoringService
from core.workflow.document import WorkflowDocument, WorkflowNodeInstance
from modules.protein_io.package import MODULE_PACKAGE as PROTEIN_IO_PACKAGE
from tests.support.application import create_application


@dataclass(frozen=True)
class Lifecycle:
    root: Path
    projects: ProjectManager
    authoring: WorkflowAuthoringService
    runtime: V2RunService

    def scopes(self, project_id: str) -> tuple[Path, ...]:
        return tuple(self.root / name / project_id for name in ("cache", "outputs", "runs", "projects"))


@pytest.fixture
def lifecycle(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Lifecycle]:
    monkeypatch.setenv("PROTEIN_WORKBENCH_DATA_ROOT", str(tmp_path))
    app = create_application(frozen_catalog_override=build_frozen_catalog((PROTEIN_IO_PACKAGE,)))
    subject = Lifecycle(tmp_path, app.state.project_manager, app.state.workflow_authoring, app.state.run_runtime)
    yield subject
    subject.runtime.shutdown()


def _snapshot(root: Path) -> dict[Path, bytes]:
    return {path.relative_to(root): path.read_bytes() for path in root.rglob("*") if path.is_file()}


def _prepared_project(subject: Lifecycle, name: str) -> tuple[str, str]:
    project = subject.projects.create(name)
    subject.projects.publish_input(project.id, "input-used", b">protein\nACDE\n", filename="input.fa")
    workflow = WorkflowDocument(
        "2.1.0", project.id,
        (WorkflowNodeInstance(
            "import", "protein_io.import_sequence", "protein_io.import_sequence.direct",
            {"project_input_ref": "input-used"}, {},
        ),), (), (), (),
    )
    subject.authoring.save_draft(project.id, workflow=workflow)
    commit = subject.authoring.commit(project.id, workflow=workflow)
    subject.authoring.load_active_commit(project.id)
    subject.authoring.require_verified_commit(project.id, workflow_commit_id=commit.workflow_commit_id)
    return project.id, commit.workflow_commit_id


def _completed_run(subject: Lifecycle, project_id: str, commit_id: str) -> str:
    receipt = subject.runtime.start(
        project_id, workflow_commit_id=commit_id, client_request_id="lifecycle-test",
    )
    run_id = receipt["run_id"]
    assert subject.runtime.projection(project_id, run_id).status == "succeeded"
    return run_id


def _assert_admission_released(runtime: V2RunService, project_id: str) -> None:
    acquired = threading.Event()

    def reserve() -> None:
        runtime._reserve_project(project_id)
        try:
            acquired.set()
        finally:
            runtime._release_project(project_id)

    worker = threading.Thread(target=reserve, daemon=True)
    worker.start()
    assert acquired.wait(timeout=5), "Project admission remained locked after lifecycle operation"
    worker.join(timeout=5)
    assert not worker.is_alive()


@pytest.mark.parametrize("operation", ["trash_project", "permanently_delete_project"])
@pytest.mark.parametrize("busy", ["reserved", "nonterminal"])
def test_busy_project_rejects_lifecycle_without_storage_changes(
    lifecycle: Lifecycle, operation: str, busy: str,
) -> None:
    project_id, commit_id = _prepared_project(lifecycle, "busy")
    if operation == "permanently_delete_project":
        lifecycle.runtime.trash_project(project_id)
    if busy == "reserved":
        lifecycle.runtime._reserve_project(project_id)
    else:
        compiled = lifecycle.authoring._verified_commits[(project_id, commit_id)]
        ledger = Ledger(lifecycle.projects, project_id, "active-run", plan_evidence(compiled.execution_plan))
        ledger.record(RunScopeBinding(workflow_commit_id=commit_id))
        ledger.record(RunAdmitted(workflow_commit_id=commit_id))
        lifecycle.runtime._registry.register(project_id, "active-run", _RunRecord(compiled=compiled, ledger=ledger))
    before = _snapshot(lifecycle.root)
    try:
        with pytest.raises(V2RunError) as error:
            getattr(lifecycle.runtime, operation)(project_id)
        assert error.value.code == "project_has_active_runs"
        assert error.value.details["run_ids"] == ([] if busy == "reserved" else ["active-run"])
        assert _snapshot(lifecycle.root) == before
    finally:
        if busy == "reserved":
            lifecycle.runtime._release_project(project_id)
    _assert_admission_released(lifecycle.runtime, project_id)


@pytest.mark.parametrize("operation", ["trash_project", "permanently_delete_project"])
@pytest.mark.parametrize("project_id", [CANONICAL_3GB1_PROJECT_ID, WEBUI_3GB1_PROJECT_ID, "missing-project"])
def test_protected_and_missing_projects_fail_without_storage_changes(
    lifecycle: Lifecycle, operation: str, project_id: str,
) -> None:
    before = _snapshot(lifecycle.root)
    expected = FileNotFoundError if project_id == "missing-project" else ProtectedProjectError
    with pytest.raises(expected):
        getattr(lifecycle.runtime, operation)(project_id)
    assert _snapshot(lifecycle.root) == before
    _assert_admission_released(lifecycle.runtime, project_id)


def test_permanent_delete_requires_trash(lifecycle: Lifecycle) -> None:
    project_id, _ = _prepared_project(lifecycle, "active")
    before = _snapshot(lifecycle.root)
    with pytest.raises(ProjectStateError, match="trashed"):
        lifecycle.runtime.permanently_delete_project(project_id)
    assert _snapshot(lifecycle.root) == before
    _assert_admission_released(lifecycle.runtime, project_id)


def test_trash_restore_retains_identity_workflow_inputs_and_results(lifecycle: Lifecycle) -> None:
    project_id, commit_id = _prepared_project(lifecycle, "retained")
    run_id = _completed_run(lifecycle, project_id, commit_id)
    workspace = lifecycle.authoring.load_workspace(project_id)
    before = _snapshot(lifecycle.root)
    trashed = lifecycle.runtime.trash_project(project_id)
    assert trashed.id == project_id
    assert trashed.deleted_at is not None
    assert lifecycle.projects.load_meta(project_id) is None
    restored = lifecycle.projects.restore(project_id)
    assert restored.id == project_id
    assert restored.deleted_at is None
    assert lifecycle.authoring.load_workspace(project_id) == workspace
    assert lifecycle.runtime.projection(project_id, run_id).status == "succeeded"
    metadata = Path("projects") / project_id / "project.json"
    assert {key: value for key, value in _snapshot(lifecycle.root).items() if key != metadata} == {
        key: value for key, value in before.items() if key != metadata
    }
    _assert_admission_released(lifecycle.runtime, project_id)


def test_permanent_delete_removes_scopes_and_warmed_caches_only_for_target(lifecycle: Lifecycle) -> None:
    project_id, commit_id = _prepared_project(lifecycle, "deleted")
    run_id = _completed_run(lifecycle, project_id, commit_id)
    other_id, other_commit = _prepared_project(lifecycle, "other")
    other_run = _completed_run(lifecycle, other_id, other_commit)
    duplicate = lifecycle.authoring.duplicate_project(project_id, name="independent")
    for root in lifecycle.scopes(project_id):
        root.mkdir(parents=True, exist_ok=True)
        (root / "retained-content").write_bytes(b"science")
    untouched = {root: _snapshot(root) for owner in (other_id, duplicate.id) for root in lifecycle.scopes(owner)}
    assert (project_id, run_id) in lifecycle.runtime._registry._runs
    assert project_id in lifecycle.authoring._active_commits
    assert (project_id, commit_id) in lifecycle.authoring._verified_commits
    lifecycle.runtime.trash_project(project_id)
    lifecycle.runtime.permanently_delete_project(project_id)
    assert all(not root.exists() for root in lifecycle.scopes(project_id))
    assert {root: _snapshot(root) for root in untouched} == untouched
    with pytest.raises(V2RunError) as error:
        lifecycle.runtime.projection(project_id, run_id)
    assert error.value.code == "run_not_found"
    assert all(owner != project_id for owner, _ in lifecycle.runtime._registry._runs)
    assert project_id not in lifecycle.authoring._active_commits
    assert all(owner != project_id for owner, _ in lifecycle.authoring._verified_commits)
    assert lifecycle.runtime.projection(other_id, other_run).status == "succeeded"
    assert lifecycle.authoring.load_active_commit(other_id).workflow_commit_id == other_commit
    assert (other_id, other_commit) in lifecycle.authoring._verified_commits
    assert lifecycle.projects.read_input(duplicate.id, "input-used")[1] == b">protein\nACDE\n"
    _assert_admission_released(lifecycle.runtime, project_id)


def test_mid_delete_failure_stops_deletion_retains_caches_and_releases_lease(
    lifecycle: Lifecycle, monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id, commit_id = _prepared_project(lifecycle, "interrupted")
    run_id = _completed_run(lifecycle, project_id, commit_id)
    for root in lifecycle.scopes(project_id):
        root.mkdir(parents=True, exist_ok=True)
        (root / "retained-content").write_bytes(b"science")
    lifecycle.runtime.trash_project(project_id)
    cache, outputs, runs, project = lifecycle.scopes(project_id)
    later = {root: _snapshot(root) for root in (outputs, runs, project)}
    records = dict(lifecycle.runtime._registry._runs)
    active = dict(lifecycle.authoring._active_commits)
    verified = dict(lifecycle.authoring._verified_commits)
    real_remove = manager_module.shutil.rmtree
    failure = OSError("output deletion interrupted")

    def remove(root: Path) -> None:
        if root == outputs:
            raise failure
        real_remove(root)

    with monkeypatch.context() as scoped:
        scoped.setattr(manager_module.shutil, "rmtree", remove)
        with pytest.raises(OSError) as error:
            lifecycle.runtime.permanently_delete_project(project_id)
    assert error.value is failure
    assert not cache.exists()
    assert {root: _snapshot(root) for root in later} == later
    assert lifecycle.runtime._registry._runs == records
    assert lifecycle.authoring._active_commits == active
    assert lifecycle.authoring._verified_commits == verified
    assert lifecycle.runtime.projection(project_id, run_id).status == "succeeded"
    _assert_admission_released(lifecycle.runtime, project_id)
