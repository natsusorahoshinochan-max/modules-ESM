"""Owned temporary module calls with explicit inputs and file receipt."""
from dataclasses import dataclass, field
from threading import Event, RLock
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
        packages = {}
        for name, port in declaration.inputs.items():
            ids = inputs.get(name, [])
            if not isinstance(ids, list) or any(not isinstance(key, str) for key in ids):
                raise HostError(f'Input {name} requires explicit package IDs')
            if (port.required and not ids) or (port.cardinality == 'one' and len(ids) > 1):
                raise HostError(f'Input {name} is unavailable or has incorrect cardinality; select delivered packages')
            values = tuple(self.host.package(key) for key in ids)
            if any(value.metadata()['project_id'] != project or value.format not in port.accepts for value in values):
                raise HostError(f'Input {name} requires an accepted package owned by this project')
            packages[name] = values
        _json_text(parameters)
        runtime = ExecutionRuntime(self.host.new_workdir())
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

    def accept(self, token, output):
        session = self.get(token)
        with session.lock:
            if session.state != 'preview' or session.cancel.is_set():
                raise HostError('Interaction has no available preview')
            if output not in session.result.outputs:
                raise HostError(f'Unknown interaction output: {output}')
            try:
                receive = self.host.create_draft_input if self.host.get_project(session.project).get('tutorial') else self.host.create_input
                return receive(session.project, session.result.outputs[output], session.runtime.workdir)
            finally:
                self._end(token, session)

    def cancel(self, token):
        session = self.get(token)
        session.cancel.set()
        # Do not release a running handler's files while it still owns them.
        with session.lock:
            self._end(token, session)

    def _end(self, token, session):
        with self.lock:
            self.sessions.pop(token, None)
        if session.runtime.workdir in self.host._workdirs:
            self.host.discard_workdir(session.runtime.workdir)
        session.state = 'ended'

    def close(self):
        for token in list(self.sessions):
            self.cancel(token)
