"""FastAPI server exposing module registry and type registry."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from core.module_definition import ModuleDefinition, ParameterDefinition, PortDefinition
from core.module_registry import ModuleRegistry, discover_modules
from core.type_registry import TypeRegistry

# Global registries, initialized at startup
type_registry: TypeRegistry
module_registry: ModuleRegistry


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


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
        global type_registry, module_registry
        type_registry = TypeRegistry()
        module_registry = ModuleRegistry(type_registry)
        discover_modules(module_registry)
        yield

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

    return app


app = create_app()
