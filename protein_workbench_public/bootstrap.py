"""The production composition root for the generic module host."""
from pathlib import Path

from fastapi import FastAPI

from core.host import Workbench
from protein_workbench_public.application_environment import application_storage_roots
from protein_workbench_public.http.app import create_http_app


def create_application(*, data_root: Path | None = None) -> FastAPI:
    """Open durable host storage without importing a scientific module."""
    return create_http_app(Workbench(data_root or application_storage_roots().data))
