"""Portable, original owner evidence for the protected WebUI example."""

from __future__ import annotations

from dataclasses import asdict
from importlib.resources import as_file, files
from io import BytesIO
import json
import os
from pathlib import Path
import tempfile
from typing import Any
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

from datatypes.i_json import canonical_json_bytes
from core.execution.recorded_run import RecordedRun
from core.execution.ledger.projections import RunProjection
from core.execution.ledger.store import FilesystemLedgerStore
from core.execution.results.store import ResultStore
from core.project.manager import WEBUI_3GB1_PROJECT_ID, ProjectInputDescriptor, ProjectManager
from core.project.objects import ProjectObjectStore
from core.project.storage import write_new_file_durable
from core.workflow.authoring import WorkflowAuthoringService


EXAMPLE_RESOURCE_NAMESPACE = "protein-workbench-webui-example-results/v1"
EXAMPLE_RESOURCE_NAME = "webui-3gb1.results.zip"


def _example_projection(
    projects: ProjectManager,
    authoring: WorkflowAuthoringService,
    run_id: str,
) -> RunProjection:
    project_id = WEBUI_3GB1_PROJECT_ID
    project = projects.require_meta(project_id)
    if not project.seed:
        raise ValueError("Example evidence requires the protected WebUI Project")
    reading = RecordedRun.load(projects, project_id, run_id)
    if reading is None:
        raise ValueError("Example Run has no completed reading")
    projection = reading.projection()
    commit = authoring.recorded_commit(
        project_id, workflow_commit_id=projection.workflow_commit_id,
    )
    if projection.status != "succeeded" or projection.derived_from_run_id is not None:
        raise ValueError("Example resource requires one successful original Run")
    scope = projection.execution_scope
    if scope is None or scope.mode != "full":
        raise ValueError("Example resource requires a full Run")
    expected_nodes = {node["node_id"] for node in commit.workflow["nodes"]}
    if set(scope.execution_node_ids) != expected_nodes or {
        disposition.node_id for disposition in projection.node_dispositions
    } != expected_nodes:
        raise ValueError("Example Run does not cover every Workflow Node")
    if any(
        disposition.outcome != "succeeded" or disposition.resolution != "executed"
        for disposition in projection.node_dispositions
    ):
        raise ValueError("Example resource requires freshly executed Nodes without cache replay")
    return projection


def export_example_results(
    *,
    projects: ProjectManager,
    authoring: WorkflowAuthoringService,
    results: ResultStore,
    run_id: str,
    destination: Path,
) -> dict[str, Any]:
    """Export existing complete evidence; this operation invokes no Provider."""
    project_id = WEBUI_3GB1_PROJECT_ID
    projection = _example_projection(projects, authoring, run_id)
    payloads: dict[str, bytes] = {}

    def retain(path: str, payload: bytes) -> dict[str, Any]:
        payloads[path] = payload
        return {"path": path}

    inputs = []
    for reference in projects.stored_input_references(project_id):
        descriptor, payload = projects.read_input(project_id, reference)
        inputs.append({**asdict(descriptor), "file": retain(f"inputs/{reference}.bin", payload)})
    records = [
        {"collection": parts[0], "name": parts[1], "file": retain(f"workflow/{parts[0]}/{parts[1]}", payload)}
        for parts, payload in authoring.webui_example_records()
    ]
    transactions = [
        {"name": name, "file": retain(f"ledger/{name}", payload)}
        for name, payload in FilesystemLedgerStore().read_transactions(
            root=projects.run_storage_root(project_id),
            relative_parts=(run_id, "ledger"),
        )
    ]
    objects = [
        {"content_digest": reference.content_digest,
         **retain(f"objects/{reference.content_digest.removeprefix('sha256:')}.bin", payload)}
        for reference, payload in results.published_object_closure(project_id, projection.publications)
    ]
    manifest = {
        "schema_namespace": EXAMPLE_RESOURCE_NAMESPACE,
        "project_id": project_id,
        "workflow_commit_id": projection.workflow_commit_id,
        "run_id": run_id,
        "terminal_cursor": projection.ledger_cursor.value,
        "inputs": inputs,
        "workflow_records": records,
        "ledger_transactions": transactions,
        "objects": objects,
    }
    payloads["manifest.json"] = canonical_json_bytes(manifest)
    payloads["reading.json"] = (projects.run_storage_directory(project_id, run_id) / "reading.json").read_bytes()
    payloads["readings.json"] = canonical_json_bytes({
        "schema_version": 1, "run_reading": {"path": "reading.json"}, "workflow_records": [],
    })
    stream = BytesIO()
    with ZipFile(stream, "w", compression=ZIP_DEFLATED, compresslevel=9) as archive:
        for path, payload in sorted(payloads.items()):
            info = ZipInfo(path, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(info, payload)
    content = stream.getvalue()
    write_new_file_durable(destination.parent, (destination.name,), content)
    return {
        "schema_namespace": EXAMPLE_RESOURCE_NAMESPACE,
        "project_id": project_id, "workflow_commit_id": projection.workflow_commit_id,
        "run_id": run_id,
        "compressed_bytes": len(content), "uncompressed_bytes": sum(map(len, payloads.values())),
        "file_count": len(payloads), "object_count": len(objects),
        "transaction_count": len(transactions),
    }


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def install_example_results(
    *,
    resource: Path,
    projects: ProjectManager,
    authoring: WorkflowAuthoringService,
) -> str:
    """Install original dependencies, then atomically expose the complete Run."""
    project_id = WEBUI_3GB1_PROJECT_ID
    with ZipFile(resource) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        readings = json.loads(archive.read("readings.json"))
        if readings["schema_version"] != 1:
            raise ValueError("Unsupported example reading version")
        run_id = manifest["run_id"]
        reading = archive.read(readings["run_reading"]["path"])
        projection = json.loads(reading)["projection"]
        if (manifest["project_id"] != project_id or projection["project_id"] != project_id
                or projection["run_id"] != run_id
                or projection["workflow_commit_id"] != manifest["workflow_commit_id"]
                or projection["ledger_cursor"] != manifest["terminal_cursor"]):
            raise ValueError("Example reading does not identify the recorded Run")
        existing_runs = projects.stored_run_ids(project_id)
        if existing_runs:
            if existing_runs != (run_id,):
                raise ValueError("Existing protected WebUI example Runs differ from the resource")
            return run_id
        inputs = {
            item["project_input_ref"]: (
                ProjectInputDescriptor(**{key: item[key] for key in
                    ("project_input_ref", "filename", "size", "content_digest")}),
                archive.read(item["file"]["path"]),
            )
            for item in manifest["inputs"]
        }
        if projects.ensure_webui_example_project(inputs=inputs) is None:
            raise ValueError("Protected WebUI Project cannot be installed")
        records = tuple(
            ((item["collection"], item["name"]), archive.read(item["file"]["path"]))
            for item in [*manifest["workflow_records"], *readings["workflow_records"]]
        )
        authoring.install_webui_example_records(records)
        for item in manifest["objects"]:
            try:
                write_new_file_durable(
                    projects._object_storage_root(project_id),
                    ProjectObjectStore._relative_parts(item["content_digest"]),
                    archive.read(item["path"]),
                )
            except FileExistsError:
                pass
        transactions = tuple(
            (item["name"], archive.read(item["file"]["path"]))
            for item in manifest["ledger_transactions"]
        )
        ledger_store = FilesystemLedgerStore()
        run_root = projects.run_storage_root(project_id)
        run_root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix=f".{project_id}-", dir=run_root.parent) as pending:
            pending_root = Path(pending)
            for name, payload in transactions:
                ledger_store.publish(root=pending_root, relative_parts=(run_id, "ledger", name), payload=payload)
            write_new_file_durable(pending_root, (run_id, "reading.json"), reading)
            (pending_root / run_id).rename(projects.run_storage_directory(project_id, run_id))
            _fsync_directory(run_root)
        return run_id


def install_bundled_example_results(
    *, projects: ProjectManager, authoring: WorkflowAuthoringService,
) -> str:
    """Install the declared resource shipped with the production example."""
    with as_file(files("examples").joinpath("v2", EXAMPLE_RESOURCE_NAME)) as resource:
        return install_example_results(
            resource=resource, projects=projects, authoring=authoring,
        )
