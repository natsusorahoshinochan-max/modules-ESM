"""The production composition root for the generic module host."""
from pathlib import Path

from fastapi import FastAPI

from core.host import Workbench
from protein_workbench_public.application_environment import application_storage_roots
from protein_workbench_public.http.app import create_http_app


def create_application(*, data_root: Path | None = None) -> FastAPI:
    """Initialize official declarations once; subsequent opens respect module choices."""
    host = Workbench(data_root or application_storage_roots().data)
    if not host._records('application'):
        host.install('modules.folding:module')
        host._put('application', {'id': 'initialized'})
    return create_http_app(host)
