"""Generate, export and check the real protected WebUI example resource."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

from core.catalog.builder import build_frozen_catalog
from core.execution.results.cache import ProjectReplayIndex
from core.execution.results.store import ResultStore
from core.project.manager import WEBUI_3GB1_PROJECT_ID, ProjectManager
from core.project.objects import ProjectObjectStore
from core.workflow.authoring import WorkflowAuthoringService
from protein_workbench_public.application_environment import application_storage_roots
from protein_workbench_public.bootstrap import create_application, module_registrations
from protein_workbench_public.example_results import export_example_results, install_example_results
from protein_workbench_public.provider_environment import provider_environment_configuration
from verification.acceptance_campaign import ExecutionProfile


def _owners(data_root: Path):
    storage = application_storage_roots({"PROTEIN_WORKBENCH_DATA_ROOT": str(data_root)})
    projects = ProjectManager(storage.projects, cache_root=storage.cache, output_root=storage.outputs, run_root=storage.runs)
    catalog = build_frozen_catalog(module_registrations())
    authoring = WorkflowAuthoringService(projects, catalog)
    results = ResultStore(ProjectObjectStore(projects), ProjectReplayIndex(projects))
    return projects, catalog, authoring, results


def generate(data_root: Path, profile_path: Path, destination: Path) -> dict[str, Any]:
    """Run the exact current example once with real configured Providers."""
    if data_root.exists():
        raise ValueError("Example generation requires a new data root")
    if destination.exists():
        raise FileExistsError(destination)
    profile = ExecutionProfile.load(profile_path)
    environment = profile.complete_environment()
    environment["PROTEIN_WORKBENCH_DATA_ROOT"] = str(data_root)
    os.environ.clear()
    os.environ.update(environment)
    app = create_application(
        v2_environment_configuration=provider_environment_configuration(environment),
        load_example_results=False,
    )
    authoring = app.state.workflow_authoring
    commit = authoring.load_active_commit(WEBUI_3GB1_PROJECT_ID)
    runtime = app.state.run_runtime
    receipt = runtime.start(
        WEBUI_3GB1_PROJECT_ID, workflow_commit_id=commit.workflow_commit_id,
        client_request_id="generate-bundled-webui-example",
    )
    run_id = receipt["run_id"]
    projection = runtime.projection(WEBUI_3GB1_PROJECT_ID, run_id)
    if projection.status != "succeeded":
        raise RuntimeError(f"Example Run {run_id} ended {projection.status}; original evidence remains in the data root")
    projects = app.state.project_manager
    results = ResultStore(ProjectObjectStore(projects), ProjectReplayIndex(projects))
    return export_example_results(
        projects=projects, authoring=authoring, results=results,
        run_id=run_id, destination=destination,
    )


def export(data_root: Path, run_id: str, destination: Path) -> dict[str, Any]:
    """Package an already completed example without a Provider invocation."""
    projects, _catalog, authoring, results = _owners(data_root)
    return export_example_results(
        projects=projects, authoring=authoring, results=results,
        run_id=run_id, destination=destination,
    )


def verify(data_root: Path, resource: Path) -> dict[str, Any]:
    """Read every installed value and artifact with all Providers unavailable."""
    if data_root.exists():
        raise ValueError("Example resource verification requires a new data root")
    projects, catalog, authoring, _results = _owners(data_root)
    run_id = install_example_results(resource=resource, projects=projects, authoring=authoring)
    os.environ["PROTEIN_WORKBENCH_DATA_ROOT"] = str(data_root)
    app = create_application(v2_environment_configuration={}, load_example_results=False)
    runtime = app.state.run_runtime
    projection = runtime.projection(WEBUI_3GB1_PROJECT_ID, run_id)
    value_count = 0
    artifact_count = 0
    for publication in projection.publications:
        for output in publication.outputs:
            for index in range(output.value_count):
                runtime.typed_value(WEBUI_3GB1_PROJECT_ID, run_id, publication.node_id, output.output_port, index)
                value_count += 1
        for artifact in publication.artifacts:
            runtime.artifact(WEBUI_3GB1_PROJECT_ID, run_id, artifact.artifact_reference)
            artifact_count += 1
    return {"project_id": WEBUI_3GB1_PROJECT_ID, "run_id": run_id, "workflow_commit_id": projection.workflow_commit_id, "status": projection.status, "typed_value_count": value_count, "artifact_count": artifact_count}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    generating = commands.add_parser("generate")
    generating.add_argument("--data-root", type=Path, required=True)
    generating.add_argument("--profile", type=Path, required=True)
    generating.add_argument("--output", type=Path, required=True)
    exporting = commands.add_parser("export")
    exporting.add_argument("--data-root", type=Path, required=True)
    exporting.add_argument("--run-id", required=True)
    exporting.add_argument("--output", type=Path, required=True)
    verifying = commands.add_parser("verify")
    verifying.add_argument("--data-root", type=Path, required=True)
    verifying.add_argument("--resource", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "generate":
        report = generate(args.data_root.resolve(), args.profile.resolve(), args.output.resolve())
    elif args.command == "export":
        report = export(args.data_root.resolve(), args.run_id, args.output.resolve())
    else:
        report = verify(args.data_root.resolve(), args.resource.resolve())
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
