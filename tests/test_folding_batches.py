"""Folding batches through the public application and public tool slot."""
import json
import zipfile

from core.host import Workbench
from modules.folding.contract import PredictionResult
from protein_workbench_public.module_api import Delivery
from tests.run_helpers import wait_run


def batch_app(tmp_path, monkeypatch):
    calls = []
    failing = {'sequence': 'DEF'}
    def create(settings):
        def predict(request, parameters, runtime):
            calls.append((request.sequence, dict(parameters)))
            if request.sequence == 'DEF' and failing.get('entered') is not None:
                failing['entered'].set()
                assert failing['release'].wait(5), 'Continuation was not released'
            if request.sequence == failing['sequence']:
                raise ValueError('provider exhausted its attempts')
            (runtime.workdir / 'result.pdb').write_text(request.sequence)
            return PredictionResult('result.pdb')
        return predict
    monkeypatch.setattr('tests.fixtures.prediction_tool.create', create)
    app = Workbench(tmp_path)
    app.install('modules.folding:module')
    app.install('tests.fixtures.prediction_tool:module')
    project = app.create_project('Batch')
    work = app.new_workdir()
    (work / 'input.json').write_text(json.dumps({'objects': [
        {'id': str(index), 'sequence': sequence} for index, sequence in enumerate(['ACD', 'DEF', 'GHI'])
    ]}))
    package = app.create_input(project['id'], Delivery('workbench.sequence', 'input', {'input': 'input.json'}), work)
    flow = {'nodes': [{'id': 'predict', 'type': 'workbench.predict', 'inputs': {'sequence': [package['id']]}, 'tools': {'predictor': 'lab.external'}, 'tool_parameters': {'predictor': {'seed': 0}}}], 'edges': []}
    app.save_project(project['id'], flow, {})
    return app, project, flow, calls, failing


def manifest(app, run):
    package = app.package(run['nodes']['predict']['outputs']['structure'][0])
    with package.open(package.entry) as stream:
        return package, json.load(stream)


def test_failed_batch_stops_unstarted_requests_and_exports_successful_partial(tmp_path, monkeypatch):
    app, project, _, calls, _ = batch_app(tmp_path, monkeypatch)
    run = wait_run(app, app.start(project['id']))
    assert calls == [('ACD', {'seed': 0}), ('DEF', {'seed': 0})]
    assert run['status'] == 'failed'
    assert 'provider exhausted' in str(run['nodes']['predict']['diagnostics'])
    package, document = manifest(app, run)
    assert [obj['sequence'] for obj in document['objects']] == ['ACD']
    with package.open(document['objects'][0]['structure']['file']) as stream:
        assert stream.read() == b'ACD'
    archive = app.export_package(package.id)
    try:
        with zipfile.ZipFile(archive) as exported:
            assert len(exported.namelist()) >= 2
    finally:
        archive.unlink()


def test_continue_uses_original_call_and_skips_accepted_successes_after_canvas_changes(tmp_path, monkeypatch):
    app, project, flow, calls, failing = batch_app(tmp_path, monkeypatch)
    first = wait_run(app, app.start(project['id']))
    partial, partial_document = manifest(app, first)
    flow['nodes'][0]['tool_parameters']['predictor']['seed'] = 99
    flow['nodes'][0]['tools']['predictor'] = 'missing.tool'
    app.save_project(project['id'], flow, {})
    failing['sequence'] = None
    reopened = Workbench(tmp_path)
    resumed = wait_run(reopened, reopened.continue_run(first['id'], 'predict'))
    assert resumed['id'] == first['id']
    assert resumed['status'] == 'succeeded', resumed
    assert calls == [('ACD', {'seed': 0}), ('DEF', {'seed': 0}), ('DEF', {'seed': 0}), ('GHI', {'seed': 0})]
    package, document = manifest(reopened, resumed)
    assert [obj['sequence'] for obj in document['objects']] == ['ACD', 'DEF', 'GHI']
    assert document['objects'][0] == partial_document['objects'][0]
    for obj in document['objects']:
        with package.open(obj['structure']['file']) as stream:
            assert stream.read().decode() == obj['sequence']
    assert reopened.package(partial.id).id == partial.id


def test_continuation_commit_failure_preserves_old_partial_and_private_progress(tmp_path, monkeypatch):
    import sqlite3
    app, project, _, calls, failing = batch_app(tmp_path, monkeypatch)
    first = wait_run(app, app.start(project['id']))
    old = first['nodes']['predict']
    old_packages = app.list_packages(project['id'])
    failing['sequence'] = None
    connect = sqlite3.connect
    armed = [True]
    class RejectNewOutput(sqlite3.Connection):
        def commit(self):
            count = self.execute("SELECT COUNT(*) FROM records WHERE kind='package'").fetchone()[0]
            if armed[0] and count > len(old_packages):
                armed[0] = False
                raise sqlite3.OperationalError('continuation output commit refused')
            return super().commit()
    monkeypatch.setattr(sqlite3, 'connect', lambda *args, **kwargs: connect(*args, **kwargs, factory=RejectNewOutput))
    failed = wait_run(app, app.continue_run(first['id'], 'predict'))
    assert failed['status'] == 'failed'
    assert 'commit refused' in str(failed['nodes']['predict']['diagnostics'])
    assert failed['nodes']['predict']['outputs'] == old['outputs']
    assert failed['nodes']['predict']['continuation'] == old['continuation']
    assert failed['nodes']['predict']['progress'] == old['progress']
    assert app.list_packages(project['id']) == old_packages
    final = wait_run(app, app.continue_run(first['id'], 'predict'))
    assert final['status'] == 'succeeded'
    assert [sequence for sequence, _ in calls] == ['ACD', 'DEF', 'DEF', 'GHI', 'DEF', 'GHI']


def test_continuation_accepts_retry_after_initial_delivery_failed_without_any_progress(tmp_path, monkeypatch):
    import os
    app, project, _, calls, failing = batch_app(tmp_path, monkeypatch)
    failing['sequence'] = None
    sync = os.fsync
    monkeypatch.setattr(os, 'fsync', lambda fd: (_ for _ in ()).throw(OSError('disk full')))
    failed = wait_run(app, app.start(project['id']))
    assert failed['nodes']['predict']['outputs'] == {}
    assert failed['nodes']['predict']['continuation'] is None
    monkeypatch.setattr(os, 'fsync', sync)
    final = wait_run(app, app.continue_run(failed['id'], 'predict'))
    assert final['status'] == 'succeeded'
    assert [sequence for sequence, _ in calls] == ['ACD', 'DEF', 'GHI', 'ACD', 'DEF', 'GHI']


def test_continue_after_persistent_terminal_commit_failure_uses_last_accepted_state(tmp_path, monkeypatch):
    import sqlite3
    from threading import Event
    app, project, flow, calls, failing = batch_app(tmp_path, monkeypatch)
    app.install('tests.fixtures.prediction_tool:consumer_module')
    app.install('tests.fixtures.host_module:branch_module')
    flow['nodes'] += [
        {'id': 'reader', 'type': 'lab.consume', 'parameters': {'note': 'original'}},
        {'id': 'independent', 'type': 'branch.node'},
        {'id': 'other_failure', 'type': 'branch.node', 'parameters': {'fail': True}},
    ]
    flow['edges'] = [{'source': 'predict', 'source_port': 'structure', 'target': 'reader', 'target_port': 'source'}]
    app.save_project(project['id'], flow, {})
    first = wait_run(app, app.start(project['id']))
    old = first['nodes']['predict']
    packages = app.list_packages(project['id'])
    failing['sequence'] = None
    connect = sqlite3.connect
    refused = Event()
    class RefusedTerminalCommit(sqlite3.Connection):
        def commit(self):
            if self.in_transaction and (refused.is_set() or self.execute("SELECT COUNT(*) FROM records WHERE kind='package'").fetchone()[0] > len(packages)):
                refused.set()
                raise sqlite3.OperationalError('persistent continuation terminal commit refused')
            return super().commit()
    monkeypatch.setattr(sqlite3, 'connect', lambda *args, **kwargs: connect(*args, **kwargs, factory=RefusedTerminalCommit))
    interrupted = wait_run(app, app.continue_run(first['id'], 'predict'))
    assert refused.is_set()
    assert interrupted['status'] == 'failed'
    assert 'persistent continuation terminal commit refused' in str(interrupted['diagnostics'])
    for field in ('outputs', 'continuation', 'progress'):
        assert interrupted['nodes']['predict'][field] == old[field]
    assert interrupted['calls'] == first['calls']
    assert app.list_packages(project['id']) == packages
    monkeypatch.setattr(sqlite3, 'connect', connect)
    reopened = Workbench(tmp_path)
    assert reopened.get_run(first['id'])['status'] == 'failed'
    flow['nodes'][0]['inputs'] = {'sequence': []}
    flow['nodes'][0]['tool_parameters']['predictor']['seed'] = 99
    flow['nodes'][0]['tools']['predictor'] = 'missing.tool'
    flow['nodes'][1]['parameters'] = {'note': 'changed canvas'}
    reopened.save_project(project['id'], flow, {})
    final = wait_run(reopened, reopened.continue_run(first['id'], 'predict'))
    assert final['id'] == first['id']
    assert final['nodes']['predict']['status'] == 'succeeded'
    assert final['calls']['predict'] == first['calls']['predict']
    assert final['nodes']['independent'] == first['nodes']['independent']
    assert final['nodes']['other_failure'] == first['nodes']['other_failure']
    package, document = manifest(reopened, final)
    assert [obj['sequence'] for obj in document['objects']] == ['ACD', 'DEF', 'GHI']
    for obj in document['objects']:
        with package.open(obj['structure']['file']) as stream:
            assert stream.read().decode() == obj['sequence']
    assert final['nodes']['reader']['status'] == 'succeeded'
    reader = reopened.package(final['nodes']['reader']['outputs']['result'][0])
    with reader.open(reader.entry) as stream:
        assert json.load(stream) == {'count': 3, 'parameters': {'note': 'original'}}
    assert calls == [(sequence, {'seed': 0}) for sequence in ['ACD', 'DEF', 'DEF', 'GHI', 'DEF', 'GHI']]


def test_continuation_only_advances_original_blocked_dependents_after_full_delivery(tmp_path, monkeypatch):
    app, project, flow, calls, failing = batch_app(tmp_path, monkeypatch)
    app.install('tests.fixtures.prediction_tool:consumer_module')
    app.install('tests.fixtures.host_module:branch_module')
    flow['nodes'] += [
        {'id': 'reader', 'type': 'lab.consume', 'parameters': {'note': 'original'}},
        {'id': 'independent', 'type': 'branch.node'},
        {'id': 'other_failure', 'type': 'branch.node', 'parameters': {'fail': True}},
        {'id': 'invalid', 'type': 'missing.node'},
    ]
    flow['edges'] = [{'source': 'predict', 'source_port': 'structure', 'target': 'reader', 'target_port': 'source'}]
    app.save_project(project['id'], flow, {})
    first = wait_run(app, app.start(project['id']))
    assert first['nodes']['reader']['status'] == 'blocked'
    independent = first['nodes']['independent']
    other_failure = first['nodes']['other_failure']
    flow['nodes'][0]['inputs'] = {'sequence': []}
    flow['nodes'][1]['parameters'] = {'note': 'changed canvas'}
    app.save_project(project['id'], flow, {})
    still_partial = wait_run(app, app.continue_run(first['id'], 'predict'))
    assert still_partial['nodes']['reader']['status'] == 'blocked'
    failing['sequence'] = None
    resumed = wait_run(app, app.continue_run(first['id'], 'predict'))
    assert resumed['status'] == 'failed'  # The unrelated failure and invalid group remain.
    assert resumed['nodes']['predict']['status'] == 'succeeded'
    assert resumed['nodes']['reader']['status'] == 'succeeded'
    assert resumed['nodes']['independent'] == independent
    assert resumed['nodes']['other_failure'] == other_failure
    assert resumed['nodes']['invalid']['status'] == 'configuration_blocked'
    package = app.package(resumed['nodes']['reader']['outputs']['result'][0])
    with package.open(package.entry) as stream:
        assert json.load(stream) == {'count': 3, 'parameters': {'note': 'original'}}
    assert [sequence for sequence, _ in calls] == ['ACD', 'DEF', 'DEF', 'DEF', 'GHI']


def test_http_continuation_lists_one_run_and_rejects_replacement_configuration(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from protein_workbench_public.http.app import create_http_app
    from tests.run_helpers import wait_response
    app, project, _, calls, failing = batch_app(tmp_path, monkeypatch)
    with TestClient(create_http_app(app)) as client:
        failed = wait_response(client, client.post(f"/api/projects/{project['id']}/runs")).json()
        failing['sequence'] = None
        route = f"/api/runs/{failed['id']}/nodes/predict/continue"
        rejected = client.post(route, json={'tool_parameters': {'predictor': {'seed': 8}}})
        assert rejected.status_code == 400
        response = wait_response(client, client.post(route))
        assert response.status_code == 200, response.text
        assert response.json()['status'] == 'succeeded'
        assert len(client.get(f"/api/projects/{project['id']}/runs").json()) == 1
        assert client.get(f"/api/runs/{failed['id']}").json() == response.json()
        assert calls[-1] == ('GHI', {'seed': 0})


def test_new_starts_always_compute_and_explicit_history_is_used_as_input(tmp_path, monkeypatch):
    app, project, flow, calls, failing = batch_app(tmp_path, monkeypatch)
    failing['sequence'] = None
    first = wait_run(app, app.start(project['id']))
    second = wait_run(app, app.start(project['id']))
    assert first['id'] != second['id']
    assert [sequence for sequence, _ in calls] == ['ACD', 'DEF', 'GHI', 'ACD', 'DEF', 'GHI']
    first_package, _ = manifest(app, first)
    second_package, _ = manifest(app, second)
    assert first_package.id != second_package.id
    app.install('tests.fixtures.prediction_tool:consumer_module')
    app.save_project(project['id'], {'nodes': [{'id': 'reader', 'type': 'lab.consume', 'inputs': {'source': [first_package.id]}}], 'edges': []}, {})
    history_run = wait_run(app, app.start(project['id']))
    assert history_run['status'] == 'succeeded'
    assert history_run['calls']['reader']['inputs'] == {'source': [first_package.id]}
    assert len(calls) == 6


def test_continuation_reacquires_run_lease_locks_project_and_observes_cancel(tmp_path, monkeypatch):
    from threading import Event
    import pytest
    from core.host import HostError
    app, project, flow, calls, failing = batch_app(tmp_path, monkeypatch)
    first = wait_run(app, app.start(project['id']))
    failing.update(sequence=None, entered=Event(), release=Event())
    started = app.continue_run(first['id'], 'predict')
    try:
        assert failing['entered'].wait(5)
        other = Workbench(tmp_path)
        assert other.get_project(project['id'])['running'] is True
        assert other.get_run(first['id'])['status'] == 'running'
        with pytest.raises(HostError, match='running'):
            other.save_project(project['id'], flow, {})
        with pytest.raises(HostError, match='running'):
            other.continue_run(first['id'], 'predict')
        other.cancel_run(first['id'])
    finally:
        failing['release'].set()
    cancelled = wait_run(app, started)
    assert cancelled['nodes']['predict']['status'] == 'cancelled'
    assert cancelled['nodes']['predict']['continuation'] == {'completed': 1}
    assert [sequence for sequence, _ in calls] == ['ACD', 'DEF', 'DEF']
    final = wait_run(app, app.continue_run(first['id'], 'predict'))
    assert final['status'] == 'succeeded'
    assert [sequence for sequence, _ in calls] == ['ACD', 'DEF', 'DEF', 'DEF', 'GHI']


def test_continue_cancelled_partial_resumes_unstarted_dependents_without_independent_cancelled_branch(tmp_path, monkeypatch):
    from threading import Event
    app, project, flow, calls, failing = batch_app(tmp_path, monkeypatch)
    app.install('tests.fixtures.prediction_tool:consumer_module')
    app.install('tests.fixtures.host_module:branch_module')
    flow['nodes'] += [{'id': 'reader', 'type': 'lab.consume'}, {'id': 'independent', 'type': 'branch.node'}]
    flow['edges'] = [{'source': 'predict', 'source_port': 'structure', 'target': 'reader', 'target_port': 'source'}]
    app.save_project(project['id'], flow, {})
    failing.update(sequence=None, entered=Event(), release=Event())
    started = app.start(project['id'])
    try:
        assert failing['entered'].wait(5)
        app.cancel_run(started['id'])
    finally:
        failing['release'].set()
    cancelled = wait_run(app, started)
    assert cancelled['nodes']['predict']['continuation'] == {'completed': 1}
    assert cancelled['nodes']['reader']['status'] == 'cancelled'
    assert cancelled['nodes']['independent']['status'] == 'cancelled'
    final = wait_run(app, app.continue_run(started['id'], 'predict'))
    assert final['nodes']['reader']['status'] == 'succeeded'
    assert final['nodes']['independent'] == cancelled['nodes']['independent']
    assert 'independent' not in final['calls']
    assert [sequence for sequence, _ in calls] == ['ACD', 'DEF', 'DEF', 'GHI']


def test_continuation_rejects_reinstalled_tool_that_no_longer_implements_original_slot(tmp_path, monkeypatch):
    from dataclasses import replace
    import pytest
    from core.host import HostError
    import tests.fixtures.prediction_tool as provider
    app, project, _, calls, failing = batch_app(tmp_path, monkeypatch)
    first = wait_run(app, app.start(project['id']))
    original = provider.module
    def changed_module():
        declaration = original()
        return replace(declaration, tools=tuple(replace(tool, slot='other.contract') for tool in declaration.tools))
    monkeypatch.setattr(provider, 'module', changed_module)
    app.install('tests.fixtures.prediction_tool:module')
    failing['sequence'] = None
    with pytest.raises(HostError, match='does not implement'):
        app.continue_run(first['id'], 'predict')
    assert app.get_run(first['id']) == first
    assert len(calls) == 2
