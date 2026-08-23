"""Explicit application composition for HTTP integration tests."""

from __future__ import annotations

from collections.abc import Mapping
import os
from typing import Any

from fastapi import FastAPI

from core.catalog.model import FrozenCatalog
from core.execution.environment import admit_environment_configuration
from core.execution.ledger import LedgerStore
from core.execution.node_attempt import NodeAttemptFactory
from core.execution.results import ProjectReplayIndex, ResultStore
from core.execution.runtime import V2RunService
from core.project.manager import ProjectManager
from core.project.objects import ProjectObjectStore
from core.workflow.authoring import WorkflowAuthoringService
from protein_workbench_public.http.app import create_http_app


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
    projects = ProjectManager(
        root_dir=os.environ.get("PROTEIN_WORKBENCH_PROJECT_ROOT", "projects"),
        cache_root=os.environ.get("PROTEIN_WORKBENCH_CACHE_ROOT"),
        output_root=os.environ.get("PROTEIN_WORKBENCH_OUTPUT_ROOT"),
        run_root=os.environ.get("PROTEIN_WORKBENCH_RUN_ROOT"),
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
