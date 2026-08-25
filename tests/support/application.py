"""Explicit application composition for HTTP integration tests."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from fastapi import FastAPI

from core.catalog.model import FrozenCatalog
from core.execution.environment import admit_environment_configuration
from core.execution.ledger import LedgerStore
from core.execution.node_attempt import NodeAttemptFactory
from core.execution.results.cache import ProjectReplayIndex
from core.execution.results.store import ResultStore
from core.execution.runtime import V2RunService
from core.project.manager import ProjectManager
from core.project.objects import ProjectObjectStore
from core.workflow.authoring import WorkflowAuthoringService
from protein_workbench_public.http.app import create_http_app
from protein_workbench_public.application_environment import (
    application_storage_roots,
)


def create_application(
    *,
    frozen_catalog_override: FrozenCatalog,
    v2_environment_configuration: (
        Mapping[tuple[str, str], Mapping[str, Any]] | None
    ) = None,
    ledger_transaction_store: LedgerStore | None = None,
) -> FastAPI:
    """Compose an app around explicit test-owned dependencies."""
    catalog = frozen_catalog_override
    storage = application_storage_roots()
    projects = ProjectManager(
        root_dir=storage.projects,
        cache_root=storage.cache,
        output_root=storage.outputs,
        run_root=storage.runs,
    )
    authoring = WorkflowAuthoringService(projects, catalog)
    environment = admit_environment_configuration(
        catalog,
        (
            {}
            if v2_environment_configuration is None
            else v2_environment_configuration
        ),
    )
    result_store = ResultStore(
        ProjectObjectStore(projects),
        ProjectReplayIndex(projects),
    )
    runtime = V2RunService(
        projects,
        catalog,
        authoring,
        NodeAttemptFactory(projects, environment, result_store),
        result_store,
        ledger_transaction_store,
    )
    return create_http_app(catalog, projects, authoring, runtime)
