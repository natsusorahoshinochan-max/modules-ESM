"""FastAPI server exposing module registry, type registry, execution, and projects."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import os
import uuid
import shutil
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any, AsyncGenerator

from contextlib import ExitStack, asynccontextmanager, suppress
from importlib.resources import as_file, files
from fastapi import (
    Body,
    FastAPI,
    File,
    Request,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.responses import JSONResponse, Response, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError

from core.cache_operations import CacheService
from core.executor import Executor
from core.lifecycle_events import (
    RunCapacityError,
    RunEventBroker,
    RunEventType,
    SubscriberLimitError,
)
from core.graph import (
    Workflow,
    WorkflowEdge,
    WorkflowNode,
    WorkflowValidationError,
    WorkflowValidationErrorKind,
    WorkflowValidationResult,
)
from core.module_definition import ModuleDefinition, ParameterDefinition, PortDefinition
from core.module_registry import ModuleRegistry, discover_modules
from core.port_types import builtin_frozen_catalog
from core.project import (
    ProjectManager,
    ProjectMeta,
    ProtectedProjectError,
    UIState,
)
from core.provider_readiness import (
    LiveProviderReadinessResolver,
    ReadinessResolver,
    assess_workflow_readiness,
)
from core.run_manifest import create_run_manifest_store
from core.recovery import RunRecoveryError, RunRecoveryService
from core.recovery_types import RecoveryAction, RecoveryProvenance
from core.storage import (
    StoragePathError,
    validate_identifier,
    validate_relative_path,
)
from core.type_registry import TypeRegistry
from core.workflow_module import WorkflowModule
from protein_workbench_public import (
    bundle_bytes,
    bundle_digest,
    load_bundle,
    validate_response,
)

# Global registries, initialized at startup
type_registry: TypeRegistry
module_registry: ModuleRegistry
project_manager: ProjectManager


@dataclass
class ActiveRun:
    project_id: str
    run_id: str
    cancellation_requested: asyncio.Event
    task: asyncio.Task | None = None


_active_runs: dict[str, ActiveRun] = {}
_active_project_runs: dict[str, ActiveRun] = {}
_cache_mutations: set[str] = set()
_run_start_reservations: set[str] = set()
ModuleFactory = Callable[[], WorkflowModule]
_module_factories: dict[str, ModuleFactory] = {}
_run_events = RunEventBroker()
MAX_RUN_NODES = 2048
MAX_RUN_EDGES = 8192
MAX_ACTIVE_RUNS = 8
RUN_CANCELLATION_TIMEOUT_SECONDS = 5.0
TRUSTED_BROWSER_ORIGINS = frozenset(
    {
        "http://127.0.0.1:5173",
        "http://localhost:5173",
        "http://127.0.0.1:8000",
        "http://localhost:8000",
    }
)


def _is_trusted_browser_origin(request: Request | WebSocket) -> bool:
    origin = request.headers.get("origin")
    return origin is None or origin in TRUSTED_BROWSER_ORIGINS


def register_module_factory(module_id: str, factory: ModuleFactory) -> None:
    """Register a factory for instantiating a workflow module."""
    _module_factories[module_id] = factory


def _port_to_dict(p: PortDefinition) -> dict:
    result = {
        "name": p.name,
        "type_id": p.type_id,
        "display_name": p.display_name,
        "description": p.description,
        "required": p.required,
        "allow_multiple": p.allow_multiple,
    }
    if p.artifact_kind is not None:
        result["artifact_kind"] = p.artifact_kind
    return result


def _param_to_dict(p: ParameterDefinition) -> dict:
    result: dict = {
        "name": p.name,
        "type": p.type,
        "default": p.default,
        "display_name": p.display_name,
        "description": p.description,
    }
    if p.min_value is not None:
        result["min"] = p.min_value
    if p.max_value is not None:
        result["max"] = p.max_value
    if p.options is not None:
        result["options"] = p.options
    return result


def _module_to_dict(m: ModuleDefinition) -> dict:
    return {
        "module_id": m.module_id,
        "version": m.version,
        "display_name": m.display_name,
        "category": m.category,
        "description": m.description,
        "input_ports": [_port_to_dict(p) for p in m.input_ports],
        "input_groups": [
            {
                "name": group.name,
                "alternatives": [
                    list(alternative)
                    for alternative in group.alternatives
                ],
                "required": group.required,
                "allow_multiple": group.allow_multiple,
            }
            for group in m.input_groups
        ],
        "output_ports": [_port_to_dict(p) for p in m.output_ports],
        "output_groups": [
            {
                "name": group.name,
                "alternatives": [
                    list(alternative)
                    for alternative in group.alternatives
                ],
            }
            for group in m.output_groups
        ],
        "parameters": [_param_to_dict(p) for p in m.parameters],
        "module_api": m.module_api,
    }


def _project_meta_to_dict(m: ProjectMeta) -> dict:
    return {
        "id": m.id,
        "name": m.name,
        "created_at": m.created_at,
        "modified_at": m.modified_at,
        "workflow_version": m.workflow_version,
        "module_dependencies": m.module_dependencies,
        "seed": m.seed,
        "legacy_seed": m.legacy_seed,
        "seed_version": m.seed_version,
    }


def _workflow_to_dict(wf: Workflow) -> dict:
    return {
        "nodes": [
            {
                "node_id": n.node_id,
                "module_id": n.module_id,
                "module_version": n.module_version,
                "parameters": n.parameters,
                "available": getattr(n, "available", True),
            }
            for n in wf.nodes.values()
        ],
        "edges": [
            {
                "source_node_id": e.source_node_id,
                "source_port": e.source_port,
                "target_node_id": e.target_node_id,
                "target_port": e.target_port,
            }
            for e in wf.edges
        ],
    }


def _workflow_from_payload(
    payload: dict[str, Any],
) -> tuple[Workflow, tuple[WorkflowValidationError, ...]]:
    """Build a Workflow while retaining structural errors for validation."""
    workflow = Workflow()
    errors: list[WorkflowValidationError] = []
    nodes = payload.get("nodes")
    if not isinstance(nodes, list):
        return workflow, (
            WorkflowValidationError(
                kind=WorkflowValidationErrorKind.MALFORMED_WORKFLOW,
                message="Workflow 'nodes' must be a list",
            ),
        )

    for raw_node in nodes:
        if not isinstance(raw_node, dict):
            errors.append(WorkflowValidationError(
                kind=WorkflowValidationErrorKind.MALFORMED_WORKFLOW,
                message="Each Workflow Node must be an object",
            ))
            continue
        missing_fields = [
            field_name
            for field_name in ("node_id", "module_id")
            if field_name not in raw_node
        ]
        if missing_fields:
            errors.append(WorkflowValidationError(
                kind=WorkflowValidationErrorKind.MALFORMED_WORKFLOW,
                message=(
                    "Workflow Node is missing required fields: "
                    f"{', '.join(missing_fields)}"
                ),
            ))
            continue
        invalid_string_fields = [
            field_name
            for field_name in ("node_id", "module_id", "module_version")
            if not isinstance(
                raw_node.get(field_name, "1.0.0"),
                str,
            )
        ]
        if invalid_string_fields:
            errors.append(WorkflowValidationError(
                kind=WorkflowValidationErrorKind.MALFORMED_WORKFLOW,
                message=(
                    "Workflow Node fields must be strings: "
                    f"{', '.join(invalid_string_fields)}"
                ),
            ))
            continue
        if not isinstance(raw_node.get("parameters", {}), dict):
            errors.append(WorkflowValidationError(
                kind=WorkflowValidationErrorKind.MALFORMED_WORKFLOW,
                message="Workflow Node 'parameters' must be an object",
            ))
            continue
        node = WorkflowNode(
            node_id=raw_node["node_id"],
            module_id=raw_node["module_id"],
            module_version=raw_node.get("module_version", "1.0.0"),
            parameters=raw_node.get("parameters", {}),
        )
        if node.node_id in workflow.nodes:
            errors.append(WorkflowValidationError(
                kind=WorkflowValidationErrorKind.DUPLICATE_NODE_ID,
                message=f"Node ID '{node.node_id}' appears more than once",
                node_id=node.node_id,
                module_id=node.module_id,
            ))
            continue
        workflow.add_node(node)

    edges = payload.get("edges", [])
    if not isinstance(edges, list):
        errors.append(WorkflowValidationError(
            kind=WorkflowValidationErrorKind.MALFORMED_WORKFLOW,
            message="Workflow 'edges' must be a list",
        ))
        return workflow, tuple(errors)

    for raw_edge in edges:
        if not isinstance(raw_edge, dict):
            errors.append(WorkflowValidationError(
                kind=WorkflowValidationErrorKind.MALFORMED_WORKFLOW,
                message="Each Workflow Edge must be an object",
            ))
            continue
        required_fields = (
            "source_node_id",
            "source_port",
            "target_node_id",
            "target_port",
        )
        missing_fields = [
            field_name
            for field_name in required_fields
            if field_name not in raw_edge
        ]
        if missing_fields:
            errors.append(WorkflowValidationError(
                kind=WorkflowValidationErrorKind.MALFORMED_WORKFLOW,
                message=(
                    "Workflow Edge is missing required fields: "
                    f"{', '.join(missing_fields)}"
                ),
            ))
            continue
        invalid_string_fields = [
            field_name
            for field_name in required_fields
            if not isinstance(raw_edge[field_name], str)
        ]
        if invalid_string_fields:
            errors.append(WorkflowValidationError(
                kind=WorkflowValidationErrorKind.MALFORMED_WORKFLOW,
                message=(
                    "Workflow Edge fields must be strings: "
                    f"{', '.join(invalid_string_fields)}"
                ),
            ))
            continue
        edge = WorkflowEdge(
            source_node_id=raw_edge["source_node_id"],
            source_port=raw_edge["source_port"],
            target_node_id=raw_edge["target_node_id"],
            target_port=raw_edge["target_port"],
        )
        edge_has_missing_node = False
        if edge.source_node_id not in workflow.nodes:
            errors.append(WorkflowValidationError(
                kind=WorkflowValidationErrorKind.EDGE_NODE_NOT_FOUND,
                message=(
                    f"Source Node '{edge.source_node_id}' is not in the Workflow"
                ),
                node_id=edge.source_node_id,
                port=edge.source_port,
            ))
            edge_has_missing_node = True
        if edge.target_node_id not in workflow.nodes:
            errors.append(WorkflowValidationError(
                kind=WorkflowValidationErrorKind.EDGE_NODE_NOT_FOUND,
                message=(
                    f"Target Node '{edge.target_node_id}' is not in the Workflow"
                ),
                node_id=edge.target_node_id,
                port=edge.target_port,
            ))
            edge_has_missing_node = True
        if not edge_has_missing_node:
            workflow.add_edge(edge)
    return workflow, tuple(errors)


def _ui_state_to_dict(ui: UIState) -> dict:
    return {
        "node_positions": ui.node_positions,
        "node_dimensions": ui.node_dimensions,
        "groupings": ui.groupings,
        "colors": ui.colors,
        "annotations": ui.annotations,
        "canvas_zoom": ui.canvas_zoom,
        "viewport": ui.viewport,
    }


def create_app(
    *,
    module_factory_overrides: Mapping[str, ModuleFactory] | None = None,
    runtime_module_allowlist: frozenset[str] | None = None,
    provider_readiness_resolver: ReadinessResolver | None = None,
    provider_aliases: Mapping[str, str] | None = None,
) -> FastAPI:
    """Create the backend, optionally replacing external-boundary Modules."""
    trusted_readiness_resolver = (
        provider_readiness_resolver
        if provider_readiness_resolver is not None
        else LiveProviderReadinessResolver()
    )
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
        global type_registry, module_registry, project_manager
        catalog_candidate = builtin_frozen_catalog()
        _run_events.clear()
        _active_runs.clear()
        _active_project_runs.clear()
        _run_start_reservations.clear()
        _module_factories.clear()
        type_registry = TypeRegistry()
        module_registry = ModuleRegistry(type_registry)
        discover_modules(module_registry)
        project_manager = ProjectManager(
            root_dir=os.environ.get("PROTEIN_WORKBENCH_PROJECT_ROOT", "projects"),
            module_registry=module_registry,
            cache_root=os.environ.get("PROTEIN_WORKBENCH_CACHE_ROOT"),
            output_root=os.environ.get("PROTEIN_WORKBENCH_OUTPUT_ROOT"),
            run_root=os.environ.get("PROTEIN_WORKBENCH_RUN_ROOT"),
        )

        from modules.stub import EchoModule
        register_module_factory("stub.echo", EchoModule)
        from modules.import_structure import ImportStructureModule
        from modules.import_sequence import ImportSequenceModule
        from modules.export_structure import ExportStructureModule
        from modules.export_sequence import ExportSequenceModule
        register_module_factory("import.structure", ImportStructureModule)
        register_module_factory("import.sequence", ImportSequenceModule)
        register_module_factory("export.structure", ExportStructureModule)
        register_module_factory("export.sequence", ExportSequenceModule)
        from modules.build_residue_layout import BuildResidueLayoutModule
        from modules.apply_residue_edits import ApplyResidueEditsModule
        from modules.compute_secondary_structure import ComputeSecondaryStructureModule
        from modules.compute_sasa import ComputeSASAModule
        from modules.override_residue_track import OverrideResidueTrackModule
        from modules.add_function_annotation import AddFunctionAnnotationModule
        from modules.assemble_protein_prompt import AssembleProteinPromptModule
        from modules.prompt_random_mask.module import RandomMaskModule
        from modules.prompt_random_insert_masked.module import RandomInsertMaskedModule
        from modules.prompt_random_fixed_positions.module import RandomFixedPositionsModule
        from modules.esm3_generate.module import ESM3GenerateModule
        register_module_factory("prompt.build_residue_layout", BuildResidueLayoutModule)
        register_module_factory("prompt.apply_residue_edits", ApplyResidueEditsModule)
        register_module_factory("prompt.compute_secondary_structure", ComputeSecondaryStructureModule)
        register_module_factory("prompt.compute_sasa", ComputeSASAModule)
        register_module_factory("prompt.override_residue_track", OverrideResidueTrackModule)
        register_module_factory("prompt.add_function_annotation", AddFunctionAnnotationModule)
        register_module_factory("prompt.assemble_protein_prompt", AssembleProteinPromptModule)
        register_module_factory("prompt.random_mask", RandomMaskModule)
        register_module_factory("prompt.random_insert_masked", RandomInsertMaskedModule)
        register_module_factory("prompt.random_fixed_positions", RandomFixedPositionsModule)
        register_module_factory("esm3.generate", ESM3GenerateModule)
        from modules.esm3_generate_sequence import ESM3GenerateSequenceModule
        from modules.esm3_update_prompt_sequence import UpdatePromptSequenceModule
        from modules.esm3_generate_structure import ESM3GenerateStructureModule
        register_module_factory("esm3.generate_sequence", ESM3GenerateSequenceModule)
        register_module_factory("esm3.update_prompt_sequence", UpdatePromptSequenceModule)
        register_module_factory("esm3.generate_structure", ESM3GenerateStructureModule)
        from modules.proteinmpnn.module_design import ProteinMPNNDesignModule
        from modules.proteinmpnn.module_score import ProteinMPNNScoreModule
        from modules.proteinmpnn.module_constraints import ProteinMPNNConstraintsModule
        register_module_factory("proteinmpnn.design", ProteinMPNNDesignModule)
        register_module_factory("proteinmpnn.score", ProteinMPNNScoreModule)
        register_module_factory("proteinmpnn.constraints", ProteinMPNNConstraintsModule)
        from modules.esmfold2_fold.module import ESMFold2FoldModule
        from modules.simplefold_fold.module import SimpleFoldFoldModule
        from modules.simplefold_evaluate.module import SimpleFoldEvaluateModule
        register_module_factory("esmfold2.fold", ESMFold2FoldModule)
        register_module_factory("simplefold.fold", SimpleFoldFoldModule)
        register_module_factory("simplefold.evaluate", SimpleFoldEvaluateModule)
        from modules.structure_align.module import StructureAlignModule
        from modules.structure_tm_score.module import StructureTMScoreModule
        from modules.structure_rmsd.module import StructureRMSDModule
        from modules.structure_pairwise_align.module import PairwiseAlignModule
        from modules.structure_batch_tm_score.module import BatchTMScoreModule
        from modules.compute_dssp.module import ComputeDSSPModule
        from modules.secondary_structure_agreement.module import SecondaryStructureAgreementModule
        from modules.aggregate_confidence.module import AggregateConfidenceModule
        from modules.merge_scores.module import MergeScoresModule
        register_module_factory("structure.align", StructureAlignModule)
        register_module_factory("structure.tm_score", StructureTMScoreModule)
        register_module_factory("structure.rmsd", StructureRMSDModule)
        register_module_factory("structure.pairwise_align", PairwiseAlignModule)
        register_module_factory("structure.batch_tm_score", BatchTMScoreModule)
        register_module_factory("compute.dssp", ComputeDSSPModule)
        register_module_factory("scoring.ss_agreement", SecondaryStructureAgreementModule)
        register_module_factory("scoring.aggregate_confidence", AggregateConfidenceModule)
        register_module_factory("scoring.merge", MergeScoresModule)
        from modules.filter_candidates.module import FilterCandidatesModule
        from modules.sort_candidates.module import SortCandidatesModule
        from modules.top_k.module import TopKModule
        from modules.weighted_rank.module import WeightedRankModule
        from modules.pareto_select.module import ParetoSelectModule
        from modules.diversity_select.module import DiversitySelectModule
        from modules.selection_concat.module import ConcatCandidatesModule
        register_module_factory("selection.filter", FilterCandidatesModule)
        register_module_factory("selection.sort", SortCandidatesModule)
        register_module_factory("selection.top_k", TopKModule)
        register_module_factory("selection.weighted_rank", WeightedRankModule)
        register_module_factory("selection.pareto", ParetoSelectModule)
        register_module_factory("selection.diversity", DiversitySelectModule)
        register_module_factory("selection.concat", ConcatCandidatesModule)
        from modules.extract_sequence_from_structure.module import ExtractSequenceFromStructureModule
        from modules.extract_backbone.module import ExtractBackboneModule
        from modules.select_chains.module import SelectChainsModule
        from modules.map_residue_track.module import MapResidueTrackModule
        register_module_factory("convert.extract_sequence", ExtractSequenceFromStructureModule)
        register_module_factory("convert.extract_backbone", ExtractBackboneModule)
        register_module_factory("convert.select_chains", SelectChainsModule)
        register_module_factory("convert.map_track", MapResidueTrackModule)
        for module_id, factory in (module_factory_overrides or {}).items():
            if module_registry.get(module_id) is None:
                raise RuntimeError(
                    f"Cannot override unknown Module '{module_id}'"
                )
            register_module_factory(module_id, factory)
        with ExitStack() as asset_stack:
            workflow_path = os.environ.get(
                "PROTEIN_WORKBENCH_CANONICAL_WORKFLOW"
            )
            packaged_workflow = workflow_path is None
            if packaged_workflow:
                workflow_path = str(asset_stack.enter_context(
                    as_file(files("examples").joinpath("3gb1_pipeline.json"))
                ))
            ui_path = os.environ.get("PROTEIN_WORKBENCH_CANONICAL_UI")
            if ui_path is None:
                ui_path = str(asset_stack.enter_context(
                    as_file(
                        files("examples").joinpath(
                            "3gb1_pipeline_ui.json"
                        )
                    )
                ))
            canonical_structure = asset_stack.enter_context(
                as_file(files("pdbs").joinpath("3GB1.pdb"))
            )
            project_manager.ensure_seed_project(
                workflow_path,
                ui_path,
                version=os.environ.get(
                    "PROTEIN_WORKBENCH_CANONICAL_VERSION",
                    "1",
                ),
                input_sources=(
                    {"pdbs/3GB1.pdb": canonical_structure}
                    if packaged_workflow
                    else None
                ),
            )
        _cache_mutations.clear()
        app.state.frozen_catalog = catalog_candidate
        yield
        for active_run in tuple(_active_runs.values()):
            active_run.cancellation_requested.set()
        active_tasks = tuple(
            active_run.task
            for active_run in _active_runs.values()
            if active_run.task is not None
        )
        if active_tasks:
            await asyncio.gather(*active_tasks, return_exceptions=True)

    app = FastAPI(title="Protein Workbench", version="0.1.0", lifespan=lifespan)

    @app.middleware("http")
    async def enforce_trusted_mutation_origin(
        request: Request,
        call_next: Any,
    ) -> Any:
        if (
            request.method not in {"GET", "HEAD", "OPTIONS"}
            and not _is_trusted_browser_origin(request)
        ):
            return JSONResponse(
                status_code=403,
                content={
                    "error": {
                        "kind": "untrusted_origin",
                        "message": "Browser origin is not allowed",
                    }
                },
            )
        return await call_next(request)

    @app.exception_handler(StoragePathError)
    async def storage_path_error_handler(
        request: Request,
        error: StoragePathError,
    ) -> JSONResponse:
        del request
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "kind": "invalid_storage_path",
                    "field": error.field,
                    "message": str(error),
                },
            },
        )

    @app.exception_handler(ProtectedProjectError)
    async def protected_project_error_handler(
        request: Request,
        error: ProtectedProjectError,
    ) -> JSONResponse:
        del request
        return JSONResponse(
            status_code=403,
            content={
                "error": {
                    "kind": "protected_canonical_project",
                    "message": str(error),
                },
            },
        )

    @app.exception_handler(RunCapacityError)
    async def run_capacity_error_handler(
        request: Request,
        error: RunCapacityError,
    ) -> JSONResponse:
        del request
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "kind": "run_capacity_exceeded",
                    "message": str(error),
                    "nodes": error.nodes,
                    "edges": error.edges,
                    "limits": {
                        "nodes": MAX_RUN_NODES,
                        "edges": MAX_RUN_EDGES,
                    },
                },
            },
        )

    @app.exception_handler(RunRecoveryError)
    async def run_recovery_error_handler(
        request: Request,
        error: RunRecoveryError,
    ) -> JSONResponse:
        del request
        return JSONResponse(
            status_code=error.status_code,
            content=error.to_dict(),
        )

    @app.exception_handler(RequestValidationError)
    async def request_validation_error_handler(
        request: Request,
        error: RequestValidationError,
    ) -> JSONResponse:
        del request
        body_error = any(
            item.get("loc", (None,))[0] == "body"
            for item in error.errors()
        )
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "kind": (
                        "invalid_request_body"
                        if body_error
                        else "invalid_request"
                    ),
                    "message": (
                        "Request body is invalid"
                        if body_error
                        else "Request is invalid"
                    ),
                }
            },
        )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(TRUSTED_BROWSER_ORIGINS),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    protocol_discovery = load_bundle()["bundle_discovery"]

    @app.get(
        protocol_discovery["route"],
        include_in_schema=False,
    )
    async def public_protocol_bundle() -> Response:
        return Response(
            content=bundle_bytes(),
            media_type=protocol_discovery["media_type"],
            headers={
                protocol_discovery["digest_header"]: bundle_digest(),
            },
        )

    catalog_operation = load_bundle()["rest_operations"]["catalog_snapshot"]

    @app.get(catalog_operation["route"], include_in_schema=False)
    async def public_catalog_snapshot(request: Request) -> dict[str, Any]:
        payload = request.app.state.frozen_catalog.public_snapshot(
            protocol_digest=bundle_digest(),
        )
        validate_response(
            "catalog_snapshot",
            catalog_operation["response"]["success_status"],
            payload,
        )
        return payload

    # ── modules & types ──────────────────────────────────────────────

    @app.get("/api/modules")
    async def list_modules() -> list[dict]:
        return [_module_to_dict(m) for m in module_registry.list_all()]

    @app.get("/api/types")
    async def list_types() -> list[str]:
        return type_registry.list_all()

    # ── execution ────────────────────────────────────────────────────

    def require_run_capacity(workflow: Workflow) -> None:
        if (
            len(workflow.nodes) > MAX_RUN_NODES
            or len(workflow.edges) > MAX_RUN_EDGES
        ):
            raise RunCapacityError(
                nodes=len(workflow.nodes),
                edges=len(workflow.edges),
            )

    @app.websocket("/ws/execution")
    async def execution_ws(websocket: WebSocket) -> None:
        if not _is_trusted_browser_origin(websocket):
            await websocket.close(code=4403)
            return
        await websocket.accept()
        try:
            while True:
                await websocket.receive_text()
        except WebSocketDisconnect:
            pass
        except Exception:
            pass

    async def start_execution(
        *,
        project_id: str,
        workflow: Workflow,
        validation: WorkflowValidationResult,
        options: dict[str, Any],
        recovery: RecoveryProvenance | None = None,
    ) -> dict[str, Any]:
        disallowed_modules = sorted({
            node.module_id
            for node in workflow.nodes.values()
            if (
                runtime_module_allowlist is not None
                and node.module_id not in runtime_module_allowlist
            )
        })
        if disallowed_modules:
            raise RunRecoveryError(
                "module_not_allowed",
                "Workflow contains a Module disabled by this backend",
                status_code=422,
                module_ids=disallowed_modules,
            )
        if (
            len(_active_runs) + len(_run_start_reservations)
            >= MAX_ACTIVE_RUNS
        ):
            return JSONResponse(
                status_code=429,
                content={
                    "error": {
                        "kind": "active_run_capacity_exceeded",
                        "message": "Backend has too many active runs",
                        "limit": MAX_ACTIVE_RUNS,
                    }
                },
            )
        active_run = _active_project_runs.get(project_id)
        if (
            active_run is not None
            or project_id in _run_start_reservations
        ):
            content: dict[str, Any] = {
                "error": {
                    "kind": "active_run_conflict",
                    "message": "Project already has an active run",
                    "project_id": project_id,
                }
            }
            if active_run is not None:
                content["error"]["active_run_id"] = active_run.run_id
            return JSONResponse(
                status_code=409,
                content=content,
            )
        if project_id in _cache_mutations:
            return JSONResponse(
                status_code=409,
                content={
                    "error": {
                        "kind": "cache_mutation_conflict",
                        "message": "Project Cache is being changed",
                        "project_id": project_id,
                    }
                },
            )
        modules: dict[str, WorkflowModule] = {}
        for node in workflow.nodes.values():
            factory = _module_factories.get(node.module_id)
            if factory is None:
                raise RuntimeError(
                    f"No runtime factory registered for Module '{node.module_id}'"
                )
            modules[node.module_id] = factory()

        raw_force_rerun = options.get("force_rerun_nodes", [])
        if (
            not isinstance(raw_force_rerun, list)
            or not all(isinstance(node_id, str) for node_id in raw_force_rerun)
        ):
            raise StoragePathError(
                "force_rerun_nodes",
                "Invalid force_rerun_nodes",
            )
        force_rerun = {
            validate_identifier(node_id, "node_id")
            for node_id in raw_force_rerun
        }
        unknown_force_rerun = sorted(force_rerun - workflow.nodes.keys())
        if unknown_force_rerun:
            raise RunRecoveryError(
                "node_not_found",
                "Force-rerun selection contains an unknown Node",
                status_code=404,
                node_ids=unknown_force_rerun,
            )
        seed = options.get("seed", 42)
        if (
            not isinstance(seed, int)
            or isinstance(seed, bool)
            or seed < 0
            or seed > 2**63 - 1
        ):
            raise RunRecoveryError(
                "invalid_run_seed",
                "Run seed must be a non-negative integer",
                status_code=422,
            )
        run_id = str(uuid.uuid4())
        project_dir = str(project_manager.project_dir(project_id))
        for node_id, node in workflow.nodes.items():
            context = project_manager.run_context(
                project_id,
                run_id,
                node_id,
                seed=seed,
            )
            if node.module_id in {"import.sequence", "import.structure"}:
                context.input_path(node.parameters.get("file_path", ""))

        _run_start_reservations.add(project_id)
        readiness_task = asyncio.create_task(asyncio.to_thread(
            assess_workflow_readiness,
            workflow,
            trusted_readiness_resolver,
            provider_aliases=provider_aliases,
        ))
        try:
            readiness = await asyncio.shield(readiness_task)
        except asyncio.CancelledError:
            await readiness_task
            raise
        finally:
            _run_start_reservations.discard(project_id)
        if not readiness.ready:
            with create_run_manifest_store(
                run_dir=project_manager.run_dir(project_id, run_id),
                project_id=project_id,
                run_id=run_id,
                workflow=workflow,
                modules=modules,
                seed=seed,
                source_dir=Path.cwd(),
                recovery=recovery,
            ) as manifest_store:
                for fact in readiness.facts:
                    manifest_store.record_resolved_provider_readiness(fact)
                manifest_store.set_status("failed")
            return JSONResponse(
                status_code=503,
                content={
                    "project_id": project_id,
                    "run_id": run_id,
                    "error": {
                        "kind": "required_provider_unavailable",
                        "message": (
                            "Required scientific provider readiness "
                            "could not be established"
                        ),
                        "readiness": readiness.public_facts(),
                    },
                },
            )

        stream = _run_events.create(project_id, run_id)
        cancellation_requested = asyncio.Event()
        active_run = ActiveRun(
            project_id=project_id,
            run_id=run_id,
            cancellation_requested=cancellation_requested,
        )
        executor = Executor()
        executor.on_lifecycle_event(
            lambda event_type, node_id, details: stream.publish(
                event_type,
                node_id=node_id,
                details=details,
            )
        )

        def cleanup(completed: asyncio.Task | None) -> None:
            if (
                completed is None
                or _active_runs.get(run_id) is active_run
                and active_run.task is completed
            ):
                _active_runs.pop(run_id, None)
            if _active_project_runs.get(project_id) is active_run:
                _active_project_runs.pop(project_id, None)

        async def run() -> None:
            try:
                await executor.execute(
                    workflow=workflow,
                    modules=modules,
                    project_dir=project_dir,
                    run_id=run_id,
                    seed=seed,
                    force_rerun_nodes=force_rerun,
                    project_manager=project_manager,
                    project_id=project_id,
                    provider_readiness=readiness.executor_payload(),
                    recovery=recovery,
                    cancellation_requested=cancellation_requested,
                    cancellation_timeout=RUN_CANCELLATION_TIMEOUT_SECONDS,
                )
            except asyncio.CancelledError:
                if not stream.terminal:
                    stream.publish(
                        RunEventType.RUN_CANCELLED,
                        details={
                            "status": "cancelled",
                            "duration_ms": stream.elapsed_ms,
                        },
                    )
                raise
            except Exception:
                if not stream.terminal:
                    stream.publish(
                        RunEventType.RUN_FAILED,
                        details={
                            "status": "failed",
                            "duration_ms": stream.elapsed_ms,
                            "error": {
                                "kind": "run_setup_error",
                                "message": "Run setup failed",
                                "retryable": False,
                            },
                        },
                    )
            finally:
                cleanup(asyncio.current_task())

        task = asyncio.create_task(run())
        active_run.task = task
        _active_runs[run_id] = active_run
        _active_project_runs[project_id] = active_run

        task.add_done_callback(cleanup)
        result = {
            "project_id": project_id,
            "run_id": run_id,
            **validation.to_dict(),
        }
        if recovery is not None:
            result["recovery"] = recovery
        return result

    @app.post("/api/execute")
    async def execute_workflow(payload: dict) -> Any:
        workflow, construction_errors = _workflow_from_payload(payload)
        require_run_capacity(workflow)
        semantic_validation = workflow.validate(module_registry)
        validation = WorkflowValidationResult(
            construction_errors + semantic_validation.errors
        )
        if not validation.valid:
            return JSONResponse(
                status_code=422,
                content=validation.to_dict(),
            )

        supplied_project_id = payload.get("project_id")
        if supplied_project_id is not None:
            validate_identifier(supplied_project_id, "project_id")
            if project_manager.load_meta(supplied_project_id) is None:
                return JSONResponse(
                    status_code=404,
                    content={"error": "Project not found"},
                )
            execution_project_id = supplied_project_id
        else:
            execution_project_id = f"ephemeral-{uuid.uuid4().hex[:8]}"
        return await start_execution(
            project_id=execution_project_id,
            workflow=workflow,
            validation=validation,
            options=payload,
        )

    @app.post("/api/projects/{project_id}/run")
    async def execute_saved_workflow(
        project_id: str,
        payload: dict | None = None,
    ) -> Any:
        options = payload or {}
        meta = project_manager.load_meta(project_id)
        if meta is None:
            return JSONResponse(
                status_code=404,
                content={"error": "Project not found"},
            )
        workflow = project_manager.load_workflow(project_id)
        require_run_capacity(workflow)
        validation = workflow.validate(module_registry)
        if not validation.valid:
            return JSONResponse(
                status_code=422,
                content=validation.to_dict(),
            )

        return await start_execution(
            project_id=project_id,
            workflow=workflow,
            validation=validation,
            options=options,
        )

    @app.websocket("/api/projects/{project_id}/run/{run_id}/ws")
    async def run_execution_ws(
        websocket: WebSocket,
        project_id: str,
        run_id: str,
    ) -> None:
        if not _is_trusted_browser_origin(websocket):
            await websocket.close(code=4403)
            return
        try:
            stream = _run_events.get(project_id, run_id)
        except StoragePathError:
            await websocket.close(code=4400)
            return
        if stream is None:
            await websocket.close(code=4404)
            return
        await websocket.accept()
        try:
            subscription = stream.subscribe()
        except SubscriberLimitError:
            await websocket.close(code=4429)
            return
        disconnect = asyncio.create_task(websocket.receive())

        async def send(event: dict[str, Any]) -> bool:
            await asyncio.wait_for(
                websocket.send_json(event),
                timeout=5,
            )
            return event["type"] in {
                RunEventType.RUN_COMPLETED.value,
                RunEventType.RUN_FAILED.value,
                RunEventType.RUN_CANCELLED.value,
            }

        try:
            for event in subscription.replay:
                if disconnect.done() or await send(event):
                    return
            while True:
                next_event = asyncio.create_task(subscription.live.get())
                done, _ = await asyncio.wait(
                    {next_event, disconnect},
                    return_when=asyncio.FIRST_COMPLETED,
                )
                if disconnect in done:
                    next_event.cancel()
                    with suppress(asyncio.CancelledError):
                        await next_event
                    return
                event = next_event.result()
                if event is None:
                    await asyncio.wait_for(
                        websocket.close(code=1013),
                        timeout=5,
                    )
                    return
                if await send(event):
                    return
        except (TimeoutError, WebSocketDisconnect, RuntimeError):
            pass
        finally:
            disconnect.cancel()
            with suppress(asyncio.CancelledError):
                await disconnect
            stream.unsubscribe(subscription)

    @app.post("/api/execute/cancel")
    async def cancel_execution(payload: dict) -> dict:
        run_id = validate_identifier(payload.get("run_id", ""), "run_id")
        active_run = _active_runs.get(run_id)
        project_id = (
            active_run.project_id
            if active_run is not None
            else None
        )
        supplied_project_id = payload.get("project_id")
        if supplied_project_id is not None:
            supplied_project_id = validate_identifier(
                supplied_project_id,
                "project_id",
            )
            if supplied_project_id != project_id:
                return {"status": "not_found"}
        elif project_id is not None and not project_id.startswith("ephemeral-"):
            return {
                "status": "project_scope_required",
                "run_id": run_id,
            }
        if (
            active_run is not None
            and active_run.task is not None
            and not active_run.task.done()
        ):
            active_run.cancellation_requested.set()
            return {
                "status": "cancellation_requested",
                "project_id": project_id,
                "run_id": run_id,
            }
        return {"status": "not_found"}

    @app.post("/api/projects/{project_id}/run/{run_id}/cancel")
    async def cancel_project_run(
        project_id: str,
        run_id: str,
    ) -> Any:
        safe_project_id = validate_identifier(project_id, "project_id")
        safe_run_id = validate_identifier(run_id, "run_id")
        active_run = _active_project_runs.get(safe_project_id)
        if active_run is None or active_run.run_id != safe_run_id:
            return JSONResponse(
                status_code=404,
                content={
                    "error": {
                        "kind": "active_run_not_found",
                        "message": "Active project run was not found",
                    }
                },
            )
        if active_run.task is None or active_run.task.done():
            return JSONResponse(
                status_code=404,
                content={
                    "error": {
                        "kind": "active_run_not_found",
                        "message": "Active project run was not found",
                    }
                },
            )
        active_run.cancellation_requested.set()
        return {
            "status": "cancellation_requested",
            "project_id": safe_project_id,
            "run_id": safe_run_id,
        }

    # ── durable run recovery ─────────────────────────────────────────

    @app.get("/api/projects/{project_id}/run/{run_id}/status")
    def get_run_status(project_id: str, run_id: str) -> dict[str, Any]:
        return RunRecoveryService(project_manager).status(
            project_id,
            run_id,
        )

    @app.get("/api/projects/{project_id}/run/{run_id}/manifest")
    def get_run_manifest(project_id: str, run_id: str) -> dict[str, Any]:
        return RunRecoveryService(project_manager).manifest(
            project_id,
            run_id,
        )

    @app.get("/api/projects/{project_id}/run/{run_id}/outputs")
    def get_run_outputs(
        project_id: str,
        run_id: str,
    ) -> dict[str, Any]:
        return RunRecoveryService(project_manager).outputs(
            project_id,
            run_id,
        )

    @app.get(
        "/api/projects/{project_id}/run/{run_id}"
        "/artifacts/{reference:path}"
    )
    def get_run_artifact(
        project_id: str,
        run_id: str,
        reference: str,
    ) -> StreamingResponse:
        record, chunks = RunRecoveryService(
            project_manager
        ).artifact_chunks(project_id, run_id, reference)
        return StreamingResponse(
            chunks,
            media_type="application/octet-stream",
            headers={"content-length": str(record["size"])},
        )

    async def recover_node(
        project_id: str,
        run_id: str,
        node_id: str,
        *,
        action: RecoveryAction,
        payload: dict[str, Any] | None,
    ) -> Any:
        if payload is not None and not isinstance(payload, dict):
            raise RunRecoveryError(
                "invalid_recovery_request",
                "Recovery request body must be an object",
                status_code=422,
            )
        if payload is not None and payload.get("seed", ...) is None:
            raise RunRecoveryError(
                "invalid_recovery_seed",
                "Recovery seed must be a non-negative integer",
                status_code=422,
            )
        service = RunRecoveryService(project_manager)
        service.manifest(project_id, run_id)
        try:
            workflow = project_manager.load_workflow(project_id)
        except (
            AttributeError,
            KeyError,
            OSError,
            RecursionError,
            TypeError,
            ValueError,
        ):
            raise RunRecoveryError(
                "invalid_workflow",
                "Current Workflow is not readable",
                status_code=409,
            ) from None
        plan = service.recovery_plan(
            project_id,
            run_id,
            node_id,
            action=action,
            workflow=workflow,
            requested_seed=(payload or {}).get("seed"),
        )
        validation = workflow.validate(module_registry)
        if not validation.valid:
            return JSONResponse(
                status_code=422,
                content=validation.to_dict(),
            )
        return await start_execution(
            project_id=project_id,
            workflow=workflow,
            validation=validation,
            options={
                "seed": plan.seed,
                "force_rerun_nodes": list(plan.force_rerun_nodes),
            },
            recovery=plan.provenance,
        )

    @app.post(
        "/api/projects/{project_id}/run/{run_id}/nodes/{node_id}/retry"
    )
    async def retry_run_node(
        project_id: str,
        run_id: str,
        node_id: str,
        payload: Any = Body(default=None),
    ) -> Any:
        return await recover_node(
            project_id,
            run_id,
            node_id,
            action=RecoveryAction.RETRY,
            payload=payload,
        )

    @app.post(
        "/api/projects/{project_id}/run/{run_id}"
        "/nodes/{node_id}/force-rerun"
    )
    async def force_rerun_node(
        project_id: str,
        run_id: str,
        node_id: str,
        payload: Any = Body(default=None),
    ) -> Any:
        return await recover_node(
            project_id,
            run_id,
            node_id,
            action=RecoveryAction.FORCE_RERUN,
            payload=payload,
        )


    # ── cache management ────────────────────────────────────────────

    @app.get("/api/projects/{project_id}/cache")
    def list_project_cache(project_id: str) -> dict[str, Any]:
        return CacheService(project_manager).entries(project_id)

    @app.get("/api/projects/{project_id}/cache/{node_id}")
    def list_node_cache(
        project_id: str,
        node_id: str,
    ) -> dict[str, Any]:
        return CacheService(project_manager).entries(
            project_id,
            node_id,
        )

    def require_cache_mutation_idle(project_id: str) -> None:
        safe_project_id = validate_identifier(project_id, "project_id")
        active_run = _active_project_runs.get(safe_project_id)
        if (
            active_run is not None
            or safe_project_id in _run_start_reservations
        ):
            raise RunRecoveryError(
                "active_run_conflict",
                "Cache cannot be cleared while the project is running",
                status_code=409,
                project_id=safe_project_id,
                **(
                    {"active_run_id": active_run.run_id}
                    if active_run is not None
                    else {}
                ),
            )

    async def clear_cache(
        project_id: str,
        node_id: str | None = None,
    ) -> dict[str, Any]:
        safe_project_id = validate_identifier(project_id, "project_id")
        require_cache_mutation_idle(safe_project_id)
        if safe_project_id in _cache_mutations:
            raise RunRecoveryError(
                "cache_mutation_conflict",
                "Project Cache is already being changed",
                status_code=409,
                project_id=safe_project_id,
            )
        _cache_mutations.add(safe_project_id)
        mutation = asyncio.create_task(asyncio.to_thread(
            CacheService(project_manager).clear,
            safe_project_id,
            node_id,
        ))
        try:
            return await asyncio.shield(mutation)
        except asyncio.CancelledError:
            await mutation
            raise
        finally:
            _cache_mutations.discard(safe_project_id)

    @app.delete("/api/projects/{project_id}/cache")
    async def clear_project_cache(project_id: str) -> dict[str, Any]:
        """Clear all cached outputs for a project."""
        return await clear_cache(project_id)

    @app.delete("/api/projects/{project_id}/cache/{node_id}")
    async def clear_node_cache(
        project_id: str,
        node_id: str,
    ) -> dict[str, Any]:
        """Clear cached outputs for a specific node."""
        return await clear_cache(project_id, node_id)


    # ── node output ─────────────────────────────────────────────────

    @app.get("/api/projects/{project_id}/nodes/{node_id}/output")
    def get_node_output(
        project_id: str,
        node_id: str,
        run_id: str | None = None,
    ) -> dict[str, Any]:
        """Return manifest-bound artifacts for one explicit run and Node."""
        if run_id is None:
            raise RunRecoveryError(
                "run_scope_required",
                "Node output retrieval requires an explicit run_id",
                status_code=422,
            )
        safe_node_id = validate_identifier(node_id, "node_id")
        service = RunRecoveryService(project_manager)
        manifest = service.manifest(project_id, run_id)
        if safe_node_id not in {
            module.get("node_id")
            for module in manifest.get("modules", [])
            if isinstance(module, dict)
        }:
            raise RunRecoveryError(
                "node_not_found",
                "Node was not found in the selected run",
                status_code=404,
                node_id=safe_node_id,
            )
        outputs = service.outputs(project_id, run_id)
        outputs["node_id"] = safe_node_id
        outputs["artifacts"] = [
            artifact
            for artifact in outputs["artifacts"]
            if artifact["node_id"] == safe_node_id
        ]
        return outputs

    # ── projects CRUD ────────────────────────────────────────────────

    @app.get("/api/projects")
    async def list_projects() -> list[dict]:
        return [_project_meta_to_dict(m) for m in project_manager.list_projects()]

    @app.post("/api/projects")
    async def create_project(payload: dict) -> dict:
        name = payload.get("name", "Untitled")
        meta = project_manager.create(name)
        return _project_meta_to_dict(meta)

    @app.get("/api/projects/{project_id}")
    async def get_project_meta(project_id: str) -> dict:
        meta = project_manager.load_meta(project_id)
        if meta is None:
            return {"error": "Project not found"}
        return _project_meta_to_dict(meta)

    @app.get("/api/projects/{project_id}/workflow")
    async def get_project_workflow(project_id: str) -> dict:
        meta = project_manager.load_meta(project_id)
        if meta is None:
            return {"error": "Project not found"}
        wf = project_manager.load_workflow(project_id)
        return _workflow_to_dict(wf)

    @app.put("/api/projects/{project_id}/workflow")
    async def save_project_workflow(project_id: str, payload: dict) -> dict:
        meta = project_manager.load_meta(project_id)
        if meta is None:
            return {"error": "Project not found"}

        workflow = Workflow()
        for n in payload.get("nodes", []):
            node = WorkflowNode(
                node_id=n["node_id"],
                module_id=n["module_id"],
                module_version=n.get("module_version", "1.0.0"),
                parameters=n.get("parameters", {}),
            )
            workflow.add_node(node)

        for e in payload.get("edges", []):
            edge = WorkflowEdge(
                source_node_id=e["source_node_id"],
                source_port=e["source_port"],
                target_node_id=e["target_node_id"],
                target_port=e["target_port"],
            )
            workflow.add_edge(edge)

        # Load existing UI or default
        ui = project_manager.load_ui(project_id)
        meta = project_manager.save(project_id, workflow, ui)
        return _project_meta_to_dict(meta)

    @app.get("/api/projects/{project_id}/ui")
    async def get_project_ui(project_id: str) -> dict:
        meta = project_manager.load_meta(project_id)
        if meta is None:
            return {"error": "Project not found"}
        ui = project_manager.load_ui(project_id)
        return _ui_state_to_dict(ui)

    @app.put("/api/projects/{project_id}/ui")
    async def save_project_ui(project_id: str, payload: dict) -> dict:
        meta = project_manager.load_meta(project_id)
        if meta is None:
            return {"error": "Project not found"}

        ui = UIState(
            node_positions=payload.get("node_positions", {}),
            node_dimensions=payload.get("node_dimensions", {}),
            groupings=payload.get("groupings", []),
            colors=payload.get("colors", {}),
            annotations=payload.get("annotations", []),
            canvas_zoom=payload.get("canvas_zoom", 1.0),
            viewport=payload.get("viewport", {}),
        )

        wf = project_manager.load_workflow(project_id)
        meta = project_manager.save(project_id, wf, ui)
        return _project_meta_to_dict(meta)


    # ── file upload / download ───────────────────────────────────────


    @app.post("/api/projects/{project_id}/inputs")
    async def upload_input(project_id: str, file: UploadFile = File(...)):
        meta = project_manager.load_meta(project_id)
        if meta is None:
            return {"error": "Project not found"}
        project_manager.assert_writable(project_id)
        uploaded_name = file.filename or "uploaded"
        dest = project_manager.input_path(project_id, uploaded_name)
        dest.parent.mkdir(parents=True, exist_ok=True)
        with open(dest, "wb") as f:
            shutil.copyfileobj(file.file, f)
        return {
            "path": f"inputs/{uploaded_name}",
            "filename": file.filename,
        }

    @app.get("/api/projects/{project_id}/outputs/{filename:path}")
    def download_output(project_id: str, filename: str):
        parts = validate_relative_path(filename, "output_path")
        if len(parts) < 2:
            raise StoragePathError("output_path", "Invalid output_path")
        run_id, *artifact_parts = parts
        record, chunks = RunRecoveryService(
            project_manager
        ).artifact_chunks(
            project_id,
            run_id,
            "/".join(artifact_parts),
        )
        return StreamingResponse(
            chunks,
            media_type="application/octet-stream",
            headers={"content-length": str(record["size"])},
        )
    return app


app = create_app()
