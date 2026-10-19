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
