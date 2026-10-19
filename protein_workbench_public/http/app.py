"""Unversioned HTTP application around the public module host."""
from pathlib import Path
import tempfile
from dataclasses import dataclass, field
from threading import Lock
from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse, FileResponse
from pydantic import BaseModel, Field
from starlette.background import BackgroundTask
from starlette.concurrency import run_in_threadpool

from core.host import HostError, Workbench
from protein_workbench_public.module_api import Delivery


class ArchiveResponse(FileResponse):
    """Remove the fully built download even if sending it is interrupted."""
    async def __call__(self, scope, receive, send):
        try:
            await super().__call__(scope, receive, send)
        finally:
            Path(self.path).unlink(missing_ok=True)


class ModuleUIResponse(StreamingResponse):
    def __init__(self, stream):
        self.stream = stream
        def chunks():
            with stream:
                while chunk := stream.read(1024 * 1024):
                    yield chunk
        super().__init__(chunks(), media_type='text/javascript')

    async def __call__(self, scope, receive, send):
        try:
            await super().__call__(scope, receive, send)
        finally:
            self.stream.close()


class ProjectName(BaseModel):
    name: str


class ProjectEdit(BaseModel):
    flow: dict
    layout: dict = Field(default_factory=dict)


class ProjectCopy(BaseModel):
    name: str
    flow: dict | None = None
    layout: dict | None = None


class InstallModule(BaseModel):
    entry_point: str


class ModuleConfiguration(BaseModel):
    settings: dict


class EnableModule(BaseModel):
    enabled: bool


class Adoption(BaseModel):
    package_id: str


class InputDescription(BaseModel):
    format: str
    entry: str
    files: dict[str, str]


@dataclass
class Upload:
    project_id: str
    workdir: Path
    files: dict[str, str] = field(default_factory=dict)
    pending: set[str] = field(default_factory=set)


def create_http_app(host: Workbench) -> FastAPI:
    # Upload staging is owned by this application; clients only receive random tokens.
    uploads: dict[str, Upload] = {}
    upload_lock = Lock()

    @asynccontextmanager
    async def lifespan(_app):
        try:
            yield
        finally:
            for upload in uploads.values():
                host.discard_workdir(upload.workdir)
            uploads.clear()
            host.discard_draft_inputs()

    app = FastAPI(title='Protein Workbench', lifespan=lifespan)
    app.state.workbench = host

    @app.exception_handler(HostError)
    async def host_error(_request: Request, error: HostError):
        return JSONResponse(status_code=error.status_code, content={'detail': str(error)})

    @app.exception_handler(OSError)
    async def file_error(_request: Request, error: OSError):
        return JSONResponse(status_code=400, content={'detail': f'File operation failed: {error}'})

    @app.get('/api/catalog')
    def catalog():
        return host.catalog()

    @app.get('/api/modules')
    def modules():
        return host.list_modules()

    @app.post('/api/modules')
    def install(body: InstallModule, request: Request):
        if request.headers.get('content-type', '').split(';')[0].strip().lower() != 'application/json':
            raise HostError('Module registration requires application/json', status_code=415)
        return host.install(body.entry_point)

    def require_selected_package_request(request):
        if (request.headers.get('sec-fetch-site', '').lower() == 'cross-site'
                or request.headers.get('sec-fetch-mode', '').lower() == 'no-cors'
                or request.headers.get('origin', '').strip().lower() == 'null'):
            raise HostError('Cross-site module installation is forbidden', status_code=403)
        if (request.headers.get('x-workbench-module-package') != 'wheel'
                or request.headers.get('content-type', '').split(';')[0].strip().lower() != 'application/octet-stream'):
            raise HostError('Selected wheel requests require X-Workbench-Module-Package: wheel and application/octet-stream', status_code=415)

    @app.post('/api/module-packages')
    async def install_package(request: Request, filename: str, entry_point: str):
        require_selected_package_request(request)
        if Path(filename).name != filename or "\\" in filename or not filename.endswith('.whl'):
            raise HostError('Select a wheel filename without a directory')
        with tempfile.TemporaryDirectory(prefix='module-upload-', dir=host.root) as directory:
            wheel = Path(directory) / filename
            with wheel.open('wb') as output:
                async for chunk in request.stream():
                    output.write(chunk)
            return await run_in_threadpool(host.install_package, wheel, entry_point)

    @app.put('/api/modules/{module_id}/settings')
    def configure(module_id: str, body: ModuleConfiguration):
        return host.configure(module_id, body.settings)

    @app.put('/api/modules/{module_id}/enabled')
    def enable(module_id: str, body: EnableModule):
        return host.enable(module_id, body.enabled)

    @app.delete('/api/modules/{module_id}')
    def uninstall(module_id: str):
        host.uninstall(module_id)
        return {'removed': module_id}

    @app.get('/api/modules/{module_id}/ui.js')
    def module_ui(module_id: str, installation_id: str):
        return ModuleUIResponse(host.open_module_ui(module_id, installation_id))

    @app.get('/api/tutorial')
    def tutorial():
        return host.tutorial()

    @app.post('/api/projects/{project_id}/copies')
    def copy_project(project_id: str, body: ProjectCopy):
        return host.copy_project(project_id, body.name, body.flow, body.layout)

    @app.get('/api/projects')
    def projects():
        return host.list_projects()

    @app.post('/api/projects')
    def create_project(body: ProjectName):
        return host.create_project(body.name)

    @app.get('/api/projects/{project_id}')
    def project(project_id: str):
        return host.get_project(project_id)

    @app.put('/api/projects/{project_id}')
    def save(project_id: str, body: ProjectEdit):
        return host.save_project(project_id, body.flow, body.layout)

    @app.delete('/api/projects/{project_id}')
    def delete_project(project_id: str):
        with upload_lock:
            owned = [(token, upload) for token, upload in uploads.items() if upload.project_id == project_id]
            if any(upload.pending for _, upload in owned):
                raise HostError('Wait for active file uploads before deleting this project')
            host.delete_project(project_id)
            for token, upload in owned:
                uploads.pop(token)
                host.discard_workdir(upload.workdir)
        return {'removed': project_id}

    @app.post('/api/projects/{project_id}/adoptions')
    def adopt(project_id: str, body: Adoption):
        return host.adopt(project_id, body.package_id)

    @app.get('/api/projects/{project_id}/packages')
    def packages(project_id: str):
        return host.list_packages(project_id)

    @app.post('/api/projects/{project_id}/uploads')
    def begin_upload(project_id: str):
        token = uuid4().hex
        with upload_lock:
            host.get_project(project_id)
            uploads[token] = Upload(project_id, host.new_workdir())
        return {'upload_id': token}

    def find_upload(project_id: str, upload_id: str):
        upload = uploads.get(upload_id)
        if upload is None or upload.project_id != project_id:
            raise HostError('Upload does not exist for this project')
        return upload

    @app.put('/api/projects/{project_id}/uploads/{upload_id}/files')
    async def upload_file(project_id: str, upload_id: str, key: str, request: Request):
        with upload_lock:
            upload = find_upload(project_id, upload_id)
            if not key or key in upload.files or key in upload.pending:
                raise HostError('File key is empty or already uploaded')
            upload.pending.add(key)
        # Logical package keys never become OS paths.
        filename = uuid4().hex
        destination = upload.workdir / filename
        try:
            with destination.open('wb') as output:
                async for chunk in request.stream():
                    output.write(chunk)
            with upload_lock:
                upload.files[key] = filename
        except BaseException:
            destination.unlink(missing_ok=True)
            raise
        finally:
            with upload_lock:
                upload.pending.discard(key)
        return {'key': key}

    @app.post('/api/projects/{project_id}/uploads/{upload_id}/commit')
    def commit_upload(project_id: str, upload_id: str, body: InputDescription):
        with upload_lock:
            upload = find_upload(project_id, upload_id)
            if upload.pending:
                raise HostError('Wait for all file uploads to finish before committing')
            if set(body.files) != set(upload.files) or any(body.files[key] != key for key in body.files):
                raise HostError('Declare each uploaded logical file key exactly once, mapping the key to itself')
            uploads.pop(upload_id)
        transferred = False
        try:
            receive = host.create_draft_input if host.get_project(project_id).get("tutorial") else host.create_input
            # Both receivers take ownership and release the workdir in their finally.
            transferred = True
            return receive(project_id, Delivery(body.format, body.entry, upload.files), upload.workdir)
        finally:
            if not transferred:
                host.discard_workdir(upload.workdir)

    @app.delete('/api/projects/{project_id}/uploads/{upload_id}')
    def discard_upload(project_id: str, upload_id: str):
        with upload_lock:
            upload = find_upload(project_id, upload_id)
            if upload.pending:
                raise HostError('Wait for active file uploads before discarding')
            uploads.pop(upload_id)
        host.discard_workdir(upload.workdir)
        return {'discarded': upload_id}

    @app.delete('/api/draft-inputs/{package_id}')
    def discard_draft_input(package_id: str):
        host.discard_draft_input(package_id)
        return {'discarded': package_id}

    @app.get('/api/packages/{package_id}')
    def package(package_id: str):
        return host.package(package_id).metadata()

    @app.get('/api/packages/{package_id}/export.zip')
    def export_package(package_id: str):
        archive = host.export_package(package_id)
        return ArchiveResponse(archive, media_type='application/zip', filename='package.zip')

    @app.get('/api/packages/{package_id}/file')
    def file(package_id: str, key: str):
        package = host.package(package_id)
        if key not in package.files:
            raise HostError(f'Package file does not exist: {key}')

        stream = package.open(key)

        def chunks():
            with stream:
                while chunk := stream.read(1024 * 1024):
                    yield chunk
        return StreamingResponse(chunks(), media_type='application/octet-stream', background=BackgroundTask(stream.close))

    @app.post('/api/projects/{project_id}/runs')
    def start(project_id: str):
        return host.start(project_id)

    @app.get('/api/projects/{project_id}/runs')
    def runs(project_id: str):
        return host.list_runs(project_id)

    @app.post('/api/runs/{run_id}/cancel')
    def cancel(run_id: str):
        return host.cancel_run(run_id)

    @app.get('/api/runs/{run_id}')
    def run(run_id: str):
        return host.get_run(run_id)

    return app
