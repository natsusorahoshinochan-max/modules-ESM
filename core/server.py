"""FastAPI server exposing module registry, type registry, execution, and projects."""

from __future__ import annotations

import asyncio
import uuid
import shutil
from typing import Any, AsyncGenerator

from contextlib import asynccontextmanager
from fastapi import FastAPI, File, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware

from core.executor import Executor
from core.graph import NodeState, Workflow, WorkflowEdge, WorkflowNode
from core.module_definition import ModuleDefinition, ParameterDefinition, PortDefinition
from core.module_registry import ModuleRegistry, discover_modules
from core.project import ProjectManager, ProjectMeta, UIState
from core.type_registry import TypeRegistry
from core.workflow_module import WorkflowModule

# Global registries, initialized at startup
type_registry: TypeRegistry
module_registry: ModuleRegistry
project_manager: ProjectManager

# Active WebSocket connections for execution progress
_active_ws: list[WebSocket] = []
_active_runs: dict[str, asyncio.Task] = {}
_module_factories: dict[str, type[WorkflowModule]] = {}


def register_module_factory(module_id: str, factory: type[WorkflowModule]) -> None:
    """Register a factory for instantiating a workflow module."""
    _module_factories[module_id] = factory


def _port_to_dict(p: PortDefinition) -> dict:
    return {
        "name": p.name,
        "type_id": p.type_id,
        "display_name": p.display_name,
        "description": p.description,
    }


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
        "output_ports": [_port_to_dict(p) for p in m.output_ports],
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


async def _broadcast_state(node_id: str, old_state: str, new_state: str) -> None:
    disconnected = []
    for ws in _active_ws:
        try:
            await ws.send_json({
                "type": "node_state",
                "node_id": node_id,
                "old_state": old_state,
                "new_state": new_state,
            })
        except Exception:
            disconnected.append(ws)
    for ws in disconnected:
        _active_ws.remove(ws)


def create_app() -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
        global type_registry, module_registry, project_manager
        type_registry = TypeRegistry()
        module_registry = ModuleRegistry(type_registry)
        discover_modules(module_registry)
        project_manager = ProjectManager(module_registry=module_registry)

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
        register_module_factory("prompt.build_residue_layout", BuildResidueLayoutModule)
        register_module_factory("prompt.apply_residue_edits", ApplyResidueEditsModule)
        register_module_factory("prompt.compute_secondary_structure", ComputeSecondaryStructureModule)
        register_module_factory("prompt.compute_sasa", ComputeSASAModule)
        register_module_factory("prompt.override_residue_track", OverrideResidueTrackModule)
        register_module_factory("prompt.add_function_annotation", AddFunctionAnnotationModule)
        register_module_factory("prompt.assemble_protein_prompt", AssembleProteinPromptModule)
        yield
        for task in _active_runs.values():
            task.cancel()

    app = FastAPI(title="Protein Workbench", version="0.1.0", lifespan=lifespan)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ── modules & types ──────────────────────────────────────────────

    @app.get("/api/modules")
    async def list_modules() -> list[dict]:
        return [_module_to_dict(m) for m in module_registry.list_all()]

    @app.get("/api/types")
    async def list_types() -> list[str]:
        return type_registry.list_all()

    # ── execution ────────────────────────────────────────────────────

    @app.websocket("/ws/execution")
    async def execution_ws(websocket: WebSocket) -> None:
        await websocket.accept()
        _active_ws.append(websocket)
        try:
            while True:
                await websocket.receive_text()
        except WebSocketDisconnect:
            pass
        except Exception:
            pass
        finally:
            if websocket in _active_ws:
                _active_ws.remove(websocket)

    @app.post("/api/execute")
    async def execute_workflow(payload: dict) -> dict:
        workflow = Workflow()
        for n in payload["nodes"]:
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

        cycle = workflow.validate_acyclic()
        if cycle:
            return {"error": f"Workflow contains a cycle: {cycle}"}

        modules: dict[str, WorkflowModule] = {}
        for node in workflow.nodes.values():
            factory = _module_factories.get(node.module_id)
            if factory is None:
                return {"error": f"Unknown module: {node.module_id}"}
            modules[node.module_id] = factory()

        executor = Executor()
        executor.on_state_change(
            lambda nid, old, new: asyncio.create_task(
                _broadcast_state(nid, old.value, new.value)
            )
        )

        run_id = str(uuid.uuid4())
        project_id = payload.get("project_id", f"ephemeral-{run_id[:8]}")
        project_dir = str(project_manager.root_dir / project_id)
        seed = payload.get("seed", 42)

        async def _run() -> None:
            try:
                await executor.execute(
                    workflow=workflow, modules=modules,
                    project_dir=project_dir, run_id=run_id, seed=seed,
                )
                for ws in _active_ws:
                    try:
                        await ws.send_json({"type": "run_complete", "run_id": run_id})
                    except Exception:
                        pass
            except asyncio.CancelledError:
                for ws in _active_ws:
                    try:
                        await ws.send_json({"type": "run_cancelled", "run_id": run_id})
                    except Exception:
                        pass
            except Exception as e:
                for ws in _active_ws:
                    try:
                        await ws.send_json({"type": "run_error", "run_id": run_id, "error": str(e)})
                    except Exception:
                        pass

        task = asyncio.create_task(_run())
        _active_runs[run_id] = task
        return {"run_id": run_id}

    @app.post("/api/execute/cancel")
    async def cancel_execution(payload: dict) -> dict:
        run_id = payload.get("run_id", "")
        task = _active_runs.pop(run_id, None)
        if task and not task.done():
            task.cancel()
            return {"status": "cancelled"}
        return {"status": "not_found"}

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
        project_dir = project_manager._project_dir(project_id)
        inputs_dir = project_dir / "inputs"
        inputs_dir.mkdir(parents=True, exist_ok=True)
        dest = inputs_dir / (file.filename or "uploaded")
        with open(dest, "wb") as f:
            shutil.copyfileobj(file.file, f)
        return {"path": str(dest), "filename": file.filename}

    @app.get("/api/projects/{project_id}/outputs/{filename:path}")
    async def download_output(project_id: str, filename: str):
        meta = project_manager.load_meta(project_id)
        if meta is None:
            return {"error": "Project not found"}
        file_path = project_manager._project_dir(project_id) / "outputs" / filename
        if not file_path.exists():
            return {"error": "File not found"}
        return FileResponse(str(file_path), filename=filename)
    return app


app = create_app()
