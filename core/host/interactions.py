"""Owned temporary module calls with explicit inputs and file receipt."""
from dataclasses import dataclass, field
from threading import Condition, Event, RLock
from contextlib import contextmanager
import os
import stat

from .storage import _relative, receive, StoredPackage
from uuid import uuid4

from protein_workbench_public.module_api import Call, InteractionResult
from .application import HostError, _json_text
from .execution import ExecutionRuntime


@dataclass
class Session:
    project: str
    declaration: object
    call: Call
    runtime: ExecutionRuntime
    cancel: Event = field(default_factory=Event)
    lock: RLock = field(default_factory=RLock)
    state: str = 'ready'
    result: InteractionResult | None = None
    readers: int = 0
    reading: Condition = field(default_factory=Condition)


class Interactions:
    def __init__(self, host):
        self.host = host
        self.sessions = {}
        self.lock = RLock()

    def begin(self, project, identity, inputs, parameters):
        self.host.get_project(project)
        matches = [(record, item) for record, module in self.host._modules()
                   for item in module.interactions if item.id == identity]
        if len(matches) != 1:
            raise HostError(f'Interaction is unavailable: {identity}')
        record, declaration = matches[0]
        if set(inputs) - set(declaration.inputs):
            raise HostError('Unknown interaction input port')
        _json_text(parameters)
        runtime = ExecutionRuntime(self.host.new_workdir())
        packages = {}
        try:
            for name, port in declaration.inputs.items():
                references = inputs.get(name, [])
                if not isinstance(references, list):
                    raise HostError(f'Input {name} requires explicit package or preview references')
                if (port.required and not references) or (port.cardinality == 'one' and len(references) > 1):
                    raise HostError(f'Input {name} is unavailable or has incorrect cardinality; select delivered packages')
                values = []
                for reference in references:
                    if isinstance(reference, str):
                        value = self.host.package(reference)
                    elif isinstance(reference, dict) and set(reference) == {'interaction', 'output'} and all(isinstance(item, str) for item in reference.values()):
                        source = self.get(reference['interaction'])
                        with source.lock:
                            if source.project != project or source.state != 'preview' or source.cancel.is_set():
                                raise HostError('Referenced preview is unavailable or belongs to another project')
                            delivery = source.result.outputs.get(reference['output'])
                            if delivery is None or delivery.format not in port.accepts:
                                raise HostError(f'Input {name} requires an accepted temporary output format')
                            # A child owns a complete copy, so undo history and cancellation
                            # can release any previous preview independently.
                            destination = runtime.workdir / 'inputs'
                            destination.mkdir(exist_ok=True)
                            input_record = receive(project, delivery, source.runtime.workdir, destination)
                            value = StoredPackage(input_record, destination / input_record['id'])
                    else:
                        raise HostError(f'Input {name} requires explicit package or preview references')
                    if value.metadata()['project_id'] != project or value.format not in port.accepts:
                        raise HostError(f'Input {name} requires an accepted package owned by this project')
                    values.append(value)
                packages[name] = tuple(values)
        except BaseException:
            self.host.discard_workdir(runtime.workdir)
            raise
        session = Session(project, declaration, Call(packages, parameters, record['settings']), runtime)
        runtime._cancel = session.cancel.is_set
        token = uuid4().hex
        with self.lock:
            self.sessions[token] = session
        return {'id': token}

    def get(self, token):
        with self.lock:
            session = self.sessions.get(token)
        if session is None:
            raise HostError('Temporary interaction has ended')
        return session

    def execute(self, token):
        session = self.get(token)
        with session.lock:
            if session.state != 'ready' or session.cancel.is_set():
                raise HostError('Interaction is no longer ready')
            session.state = 'executing'
            try:
                with self.host._project_operation([session.project]):
                    result = session.declaration.execute(session.call, session.runtime)
                if session.cancel.is_set():
                    raise HostError('Interaction cancelled')
                if not isinstance(result, InteractionResult):
                    raise HostError('Interaction must return public InteractionResult')
                _json_text(result.data)
                session.result = result
                session.state = 'preview'
                return {'id': token, 'data': result.data, 'outputs': list(result.outputs)}
            except Exception as exc:
                self._end(token, session)
                raise HostError(f'Interaction failed: {exc}') from exc

    @contextmanager
    def open_file(self, token, output, key):
        session = self.get(token)
        with session.lock:
            if session.state != 'preview' or session.cancel.is_set():
                raise HostError('Interaction has no available preview')
            delivery = session.result.outputs.get(output)
            if delivery is None or key not in delivery.files:
                raise HostError('Unknown temporary output file')
            parts = _relative(delivery.files[key], 'temporary file source')
            directory = os.open(session.runtime.workdir, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            try:
                for part in parts[:-1]:
                    next_directory = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
                    os.close(directory)
                    directory = next_directory
                descriptor = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
                info = os.fstat(descriptor)
                if not stat.S_ISREG(info.st_mode) or not info.st_mode & 0o444:
                    os.close(descriptor)
                    raise HostError('Temporary output must be a readable regular file')
                stream = os.fdopen(descriptor, 'rb')
            finally:
                os.close(directory)
            with session.reading:
                session.readers += 1
        try:
            yield stream
        finally:
            try:
                stream.close()
            finally:
                with session.reading:
                    session.readers -= 1
                    session.reading.notify_all()

    def _wait_readers(self, session):
        with session.reading:
            session.reading.wait_for(lambda: session.readers == 0)

    def accept(self, token, output):
        session = self.get(token)
        with session.lock:
            if session.state != 'preview' or session.cancel.is_set():
                raise HostError('Interaction has no available preview')
            if output not in session.result.outputs:
                raise HostError(f'Unknown interaction output: {output}')
            self._wait_readers(session)
            if session.cancel.is_set():
                raise HostError('Interaction cancelled')
            accept_input = self.host.create_draft_input if self.host.get_project(session.project).get('tutorial') else self.host.create_input
            result = accept_input(session.project, session.result.outputs[output], session.runtime.workdir, retain_workdir=True)
            return result

    def cancel(self, token):
        with self.lock:
            session = self.sessions.get(token)
        if session is None:
            return
        session.cancel.set()
        # Do not release a running handler's files while it still owns them.
        with session.lock:
            self._end(token, session)

    def _end(self, token, session):
        self._wait_readers(session)
        with self.lock:
            self.sessions.pop(token, None)
        if session.runtime.workdir in self.host._workdirs:
            self.host.discard_workdir(session.runtime.workdir)
        session.state = 'ended'

    def close(self):
        for token in list(self.sessions):
            self.cancel(token)
