"""The sole production application composition root."""

from __future__ import annotations

from collections.abc import Mapping
from contextlib import ExitStack
from importlib.resources import as_file, files
import json
from typing import Any

from fastapi import FastAPI

from core.catalog.builder import build_frozen_catalog
from core.catalog.declarations import ModulePackageRegistration
from core.execution.environment import admit_environment_configuration
from core.execution.node_attempt import NodeAttemptFactory
from core.execution.results.cache import ProjectReplayIndex
from core.execution.results.store import ResultStore
from core.project.manager import ProjectManager
from core.project.objects import ProjectObjectStore
from core.execution.runtime import V2RunService
from core.workflow.authoring import WorkflowAuthoringService
from modules.collection_ops.package import MODULE_PACKAGE as COLLECTION_OPS
from modules.esm3.package import MODULE_PACKAGE as ESM3
from modules.folding.package import MODULE_PACKAGE as FOLDING
from modules.prompt_authoring.package import MODULE_PACKAGE as PROMPT_AUTHORING
from modules.protein_io.package import MODULE_PACKAGE as PROTEIN_IO
from modules.proteinmpnn.package import MODULE_PACKAGE as PROTEINMPNN
from modules.selection.package import MODULE_PACKAGE as SELECTION
from modules.solubility.package import MODULE_PACKAGE as SOLUBILITY
from modules.structure_annotation.package import (
    MODULE_PACKAGE as STRUCTURE_ANNOTATION,
)
from modules.structure_comparison.package import (
    MODULE_PACKAGE as STRUCTURE_COMPARISON,
)
from modules.structure_prediction.package import (
    MODULE_PACKAGE as STRUCTURE_PREDICTION,
)
from modules.structure_transform.package import (
    MODULE_PACKAGE as STRUCTURE_TRANSFORM,
)
from protein_workbench_public.http.app import create_http_app
from protein_workbench_public.application_environment import (
    application_storage_roots,
)
from protein_workbench_public.provider_environment import (
    provider_environment_configuration,
)
from protein_workbench_public.workflow_codec import decode_workflow_document


_MODULE_REGISTRATIONS = (
    COLLECTION_OPS,
    ESM3,
    FOLDING,
    PROMPT_AUTHORING,
    PROTEIN_IO,
    PROTEINMPNN,
    SELECTION,
    SOLUBILITY,
    STRUCTURE_ANNOTATION,
    STRUCTURE_COMPARISON,
    STRUCTURE_PREDICTION,
    STRUCTURE_TRANSFORM,
)


def module_registrations() -> tuple[ModulePackageRegistration, ...]:
    """Return the explicit immutable production registration set."""
    return _MODULE_REGISTRATIONS


def create_application(
    *,
    v2_environment_configuration: (
        Mapping[str, Mapping[str, Any]] | None
    ) = None,
) -> FastAPI:
    """Construct the current backend and bind it to the public HTTP app."""
    catalog = build_frozen_catalog(module_registrations())
    storage = application_storage_roots()
    projects = ProjectManager(
        root_dir=storage.projects,
        cache_root=storage.cache,
        output_root=storage.outputs,
        run_root=storage.runs,
    )
    authoring = WorkflowAuthoringService(projects, catalog)
    with ExitStack() as asset_stack:
        canonical_structure = asset_stack.enter_context(
            as_file(
                files("examples").joinpath(
                    "v2",
                    "structures",
                    "3GB1.pdb",
                )
            )
        )
        canonical_workflow_path = asset_stack.enter_context(
            as_file(
                files("examples").joinpath(
                    "v2",
                    "canonical-3gb1.workflow.json",
                )
            )
        )
        canonical_workflow = decode_workflow_document(
            json.loads(
                canonical_workflow_path.read_text(encoding="utf-8")
            )
        )
        authoring.install_seed_commit(
            workflow=canonical_workflow,
            input_sources={"3GB1.pdb": canonical_structure},
        )
    environment = admit_environment_configuration(
        catalog,
        (
            provider_environment_configuration()
            if v2_environment_configuration is None
            else v2_environment_configuration
        ),
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
    return create_http_app(catalog, projects, authoring, runtime)
