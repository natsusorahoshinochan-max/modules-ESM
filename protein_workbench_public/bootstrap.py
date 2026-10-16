"""The sole production application composition root."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from contextlib import ExitStack
from importlib.resources import as_file, files
from importlib.util import find_spec
import json
from typing import Any

from fastapi import FastAPI

from core.catalog.builder import build_frozen_catalog
from core.catalog.authoring import build_authoring_capability_projection
from core.catalog.declarations import ModulePackageRegistration
from core.catalog.model import FrozenCatalog
from core.workflow.document import WorkflowDocument
from protein_workbench_public.module_registry import DEFAULT_MODULES, InstalledModule, installed_modules
from protein_workbench_public.module_management import ModuleManager
from protein_workbench_public.http.module_routes import register_module_routes
from core.execution.environment import admit_environment_configuration
from core.execution.node_attempt import NodeAttemptFactory
from core.execution.results.cache import ProjectReplayIndex
from core.execution.results.store import ResultStore
from core.project.manager import ProjectManager
from core.project.objects import ProjectObjectStore
from core.execution.runtime import V2RunService
from core.workflow.authoring import WorkflowAuthoringService
from protein_workbench_public.http.app import create_http_app
from protein_workbench_public.application_environment import (
    application_storage_roots,
)
from protein_workbench_public.provider_environment import (
    provider_environment_configuration,
)
from protein_workbench_public.workflow_codec import decode_workflow_document
from protein_workbench_public.example_results import (
    install_bundled_example_results,
)


def module_registrations() -> tuple[ModulePackageRegistration, ...]:
    """Discover the bundled packages through the public package entry point."""
    return tuple(package.registration() for package in DEFAULT_MODULES)


def _workflow_modules_present(workflow: WorkflowDocument, catalog: FrozenCatalog) -> bool:
    return all(
        catalog.get_contract("node_type", node.node_type_id) is not None
        and catalog.get_contract("binding", node.binding_id) is not None
        for node in workflow.nodes
    )


def _install_teaching_resources(
    projects: ProjectManager,
    authoring: WorkflowAuthoringService,
    catalog: FrozenCatalog,
    *,
    load_example_results: bool,
) -> None:
    """Install available teaching content only when its module contracts are present."""
    if not any(contract.contract_kind == "node_type" for contract in catalog.contracts) or find_spec("examples") is None:
        return
    resource_root = files("examples").joinpath("v2")
    canonical_resource = resource_root.joinpath("canonical-3gb1.workflow.json")
    webui_resource = resource_root.joinpath("webui-3gb1.example.json")
    structure_resource = resource_root.joinpath("structures", "3GB1.pdb")
    if not structure_resource.is_file():
        return
    with ExitStack() as asset_stack:
        structure = asset_stack.enter_context(as_file(structure_resource))
        if canonical_resource.is_file():
            workflow = decode_workflow_document(json.loads(canonical_resource.read_text(encoding="utf-8")))
            if _workflow_modules_present(workflow, catalog):
                authoring.install_seed_commit(workflow=workflow, input_sources={"3GB1.pdb": structure})
        if webui_resource.is_file():
            workflow = decode_workflow_document(json.loads(webui_resource.read_text(encoding="utf-8"))["workflow"])
            if _workflow_modules_present(workflow, catalog):
                if load_example_results and resource_root.joinpath("webui-3gb1.results.zip").is_file():
                    install_bundled_example_results(projects=projects, authoring=authoring)
                else:
                    authoring.install_webui_example_commit(workflow=workflow, input_sources={"3GB1.pdb": structure})


def create_application(
    *,
    v2_environment_configuration: (
        Mapping[str, Mapping[str, Any]] | None
    ) = None,
    load_example_results: bool = True,
) -> FastAPI:
    """Construct the current backend and bind it to the public HTTP app."""
    app = _compose_application(
        installed_modules(application_storage_roots().data),
        v2_environment_configuration=v2_environment_configuration,
        load_example_results=load_example_results,
    )

    def activate(
        packages: tuple[InstalledModule, ...], persist: Callable[[], None],
        environment: Mapping[str, Mapping[str, Any]] | None,
    ) -> None:
        configured = environment if environment is not None else v2_environment_configuration
        if configured is not None:
            active_bindings = {
                binding.binding_id for package in packages if package.enabled
                for binding in package.registration().bindings
            }
            configured = {key: value for key, value in configured.items() if key in active_bindings}
        replacement = _compose_application(
            packages, v2_environment_configuration=configured,
            load_example_results=load_example_results,
        )
        try:
            persist()
        except OSError:
            replacement.state.run_runtime.shutdown()
            raise
        old_runtime = app.state.run_runtime
        app.router.routes = [*replacement.router.routes, *module_routes]
        app.state = replacement.state
        app.state.module_manager = manager
        old_runtime.shutdown()

    manager = ModuleManager(application_storage_roots().data, lambda: app.state.run_runtime, activate)
    previous_route_count = len(app.router.routes)
    register_module_routes(app, manager)
    module_routes = app.router.routes[previous_route_count:]
    app.state.module_manager = manager
    return app


def _compose_application(
    packages: tuple[InstalledModule, ...],
    *,
    v2_environment_configuration: Mapping[str, Mapping[str, Any]] | None,
    load_example_results: bool,
) -> FastAPI:
    storage = application_storage_roots()
    registrations = tuple(package.registration() for package in packages if package.enabled)
    catalog = build_frozen_catalog(registrations)
    authoring_projection = build_authoring_capability_projection(
        registrations,
        catalog,
    )
    projects = ProjectManager(
        root_dir=storage.projects,
        cache_root=storage.cache,
        output_root=storage.outputs,
        run_root=storage.runs,
    )
    authoring = WorkflowAuthoringService(
        projects,
        catalog,
    )
    _install_teaching_resources(projects, authoring, catalog, load_example_results=load_example_results)
    if v2_environment_configuration is None:
        active_bindings = {contract.contract_id for contract in catalog.contracts if contract.contract_kind == "binding"}
        configured = provider_environment_configuration() if active_bindings else {}
        v2_environment_configuration = {
            binding_id: values for binding_id, values in configured.items()
            if binding_id in active_bindings
        }
    environment = admit_environment_configuration(
        catalog,
        v2_environment_configuration,
    )
    result_store = ResultStore(
        ProjectObjectStore(projects),
        ProjectReplayIndex(projects),
    )
    node_attempt_factory = NodeAttemptFactory(
        projects,
        environment,
        result_store,
    )
    runtime = V2RunService(
        projects,
        catalog,
        authoring,
        node_attempt_factory,
        result_store,
    )
    return create_http_app(
        catalog,
        projects,
        authoring,
        runtime,
        authoring_projection=authoring_projection,
    )
