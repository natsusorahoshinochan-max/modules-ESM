"""FastAPI server exposing module registry, type registry, and execution."""

from __future__ import annotations

import asyncio
import uuid
from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from core.executor import Executor
from core.graph import NodeState, Workflow, WorkflowEdge, WorkflowNode
from core.module_definition import ModuleDefinition, ParameterDefinition, PortDefinition
from core.module_registry import ModuleRegistry, discover_modules
from core.type_registry import TypeRegistry
from core.workflow_module import WorkflowModule

# Global registries, initialized at startup
type_registry: TypeRegistry
module_registry: ModuleRegistry

# Active WebSocket connections for execution progress
_active_ws: list[WebSocket] = []

# In-memory project store (placeholder until ticket 03 persistence)
_projects: dict[str, dict[str, Any]] = {}
_workflows: dict[str, Workflow] = {}
_active_runs: dict[str, asyncio.Task] = {}

# Factory: module_id → WorkflowModule constructor
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


async def _broadcast_state(node_id: str, old_state: str, new_state: str) -> None:
    """Push a node state change to all connected WebSocket clients."""
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
    """Create and configure the FastAPI application."""

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
        global type_registry, module_registry
        type_registry = TypeRegistry()
        module_registry = ModuleRegistry(type_registry)
        discover_modules(module_registry)
        # Register known module factories
        from modules.stub import EchoModule
        register_module_factory("stub.echo", EchoModule)
        yield
        # Cancel any active runs on shutdown
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

    @app.get("/api/modules")
    async def list_modules() -> list[dict]:
        """Return all registered module definitions."""
        return [_module_to_dict(m) for m in module_registry.list_all()]

    @app.get("/api/types")
    async def list_types() -> list[str]:
        """Return all registered type ID strings."""
        return type_registry.list_all()

    @app.websocket("/ws/execution")
    async def execution_ws(websocket: WebSocket) -> None:
        """WebSocket for real-time execution progress."""
        await websocket.accept()
        _active_ws.append(websocket)
        try:
            while True:
                # Keep connection alive; client sends pings
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
        """Execute a workflow and return a run ID.

        Request body:
            nodes: list of {node_id, module_id, module_version, parameters?}
            edges: list of {source_node_id, source_port, target_node_id, target_port}
            project_id: optional project ID (default: ephemeral)
            seed: optional random seed (default: 42)

        Returns:
            {run_id: str}
        """
        # Build workflow from payload
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

        # Validate acyclic
        cycle = workflow.validate_acyclic()
        if cycle:
            return {"error": f"Workflow contains a cycle: {cycle}"}

        # Build module instances
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
        project_dir = f"/tmp/protein-workbench/{project_id}"
        seed = payload.get("seed", 42)

        async def _run() -> None:
            try:
                await executor.execute(
                    workflow=workflow,
                    modules=modules,
                    project_dir=project_dir,
                    run_id=run_id,
                    seed=seed,
                )
                # Broadcast completion
                for ws in _active_ws:
                    try:
                        await ws.send_json({
                            "type": "run_complete",
                            "run_id": run_id,
                        })
                    except Exception:
                        pass
            except asyncio.CancelledError:
                for ws in _active_ws:
                    try:
                        await ws.send_json({
                            "type": "run_cancelled",
                            "run_id": run_id,
                        })
                    except Exception:
                        pass
            except Exception as e:
                for ws in _active_ws:
                    try:
                        await ws.send_json({
                            "type": "run_error",
                            "run_id": run_id,
                            "error": str(e),
                        })
                    except Exception:
                        pass

        task = asyncio.create_task(_run())
        _active_runs[run_id] = task

        return {"run_id": run_id}

    @app.post("/api/execute/cancel")
    async def cancel_execution(payload: dict) -> dict:
        """Cancel an active execution run.

        Request body:
            run_id: the run ID to cancel.

        Returns:
            {status: str}
        """
        run_id = payload.get("run_id", "")
        task = _active_runs.pop(run_id, None)
        if task and not task.done():
            task.cancel()
            return {"status": "cancelled"}
        return {"status": "not_found"}

    return app


app = create_app()
