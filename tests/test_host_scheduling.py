"""Backend runs observed through public application operations."""
from time import monotonic, sleep

import pytest

from core.host import HostError, Workbench
from tests.fixtures import host_module


def wait_run(app, run):
    deadline = monotonic() + 5
    while run['status'] == 'running' and monotonic() < deadline:
        sleep(.01)
        run = app.get_run(run['id'])
    assert run['status'] != 'running', run
    return run


def test_start_returns_while_backend_holds_project_and_another_client_can_cancel(tmp_path):
    app = Workbench(tmp_path)
    app.install('tests.fixtures.host_module:held_module')
    project = app.create_project('Held')
    app.save_project(project['id'], {'nodes': [{'id': 'held', 'type': 'held.node'}], 'edges': []}, {})
    host_module.entered.clear(); host_module.release.clear()
    run = app.start(project['id'])
    try:
        assert run['status'] == 'running'
        assert host_module.entered.wait(1)
        other = Workbench(tmp_path)
        with pytest.raises(HostError, match='running'):
            other.save_project(project['id'], {'nodes': []}, {})
        assert other.get_project(project['id'])['running']
        other.cancel_run(run['id'])
        host_module.release.set()
        terminal = wait_run(app, run)
        assert terminal['status'] == 'cancelled'
        assert terminal['nodes']['held']['status'] == 'cancelled'
        other.save_project(project['id'], {'nodes': []}, {})
    finally:
        host_module.release.set()


def test_invalid_connected_group_does_not_block_a_valid_isolated_node(tmp_path):
    app = Workbench(tmp_path)
    app.install('tests.fixtures.host_module:empty_module')
    project = app.create_project('Groups')
    app.save_project(project['id'], {'nodes': [{'id': 'good', 'type': 'empty.source'}, {'id': 'missing', 'type': 'not.installed'}, {'id': 'blocked', 'type': 'empty.receive'}], 'edges': [{'source': 'missing', 'source_port': 'result', 'target': 'blocked', 'target_port': 'source'}]}, {})
    run = wait_run(app, app.start(project['id']))
    assert run['nodes']['good']['status'] == 'succeeded'
    assert run['nodes']['missing']['status'] == 'configuration_blocked'
    assert run['nodes']['blocked']['status'] == 'configuration_blocked'
    assert 'Missing module node' in run['groups'][1]['diagnostics'][0]
    assert run['status'] == 'failed'


def test_runtime_scientific_failure_blocks_only_descendants_and_keeps_partial_files(tmp_path):
    app = Workbench(tmp_path)
    app.install('tests.fixtures.host_module:branch_module')
    project = app.create_project('Branches')
    flow = {'nodes': [{'id': 'source', 'type': 'branch.node'}, {'id': 'bad', 'type': 'branch.node', 'parameters': {'fail': True}}, {'id': 'independent', 'type': 'branch.node'}, {'id': 'descendant', 'type': 'branch.node'}], 'edges': [
        {'source': 'source', 'source_port': 'result', 'target': 'bad', 'target_port': 'source'},
        {'source': 'source', 'source_port': 'result', 'target': 'independent', 'target_port': 'source'},
        {'source': 'bad', 'source_port': 'result', 'target': 'descendant', 'target_port': 'source'},
    ]}
    app.save_project(project['id'], flow, {})
    run = wait_run(app, app.start(project['id']))
    assert run['status'] == 'failed'
    assert {key: value['status'] for key, value in run['nodes'].items()} == {'source': 'succeeded', 'bad': 'failed', 'independent': 'succeeded', 'descendant': 'blocked'}
    partial = app.package(run['nodes']['bad']['outputs']['result'][0])
    with partial.open('data') as stream:
        assert stream.read() == b'partial result'
    assert run['nodes']['bad']['continuation'] == {'completed': 1}


def test_disconnecting_invalid_receiver_allows_preparation_group_to_start(tmp_path):
    app = Workbench(tmp_path)
    app.install('tests.fixtures.host_module:branch_module')
    project = app.create_project('Disconnect')
    source = {'id': 'source', 'type': 'branch.node'}
    receiver = {'id': 'receiver', 'type': 'branch.node', 'tools': {'unknown': 'missing'}}
    flow = {'nodes': [source, receiver], 'edges': [{'source': 'source', 'source_port': 'result', 'target': 'receiver', 'target_port': 'source'}]}
    app.save_project(project['id'], flow, {})
    before = wait_run(app, app.start(project['id']))
    assert all(node['status'] == 'configuration_blocked' for node in before['nodes'].values())
    flow['edges'] = []
    app.save_project(project['id'], flow, {})
    after = wait_run(app, app.start(project['id']))
    assert after['nodes']['source']['status'] == 'succeeded'
    assert after['nodes']['receiver']['status'] == 'configuration_blocked'


def test_http_run_survives_frontend_disconnect_and_cancel_is_observable(tmp_path):
    from fastapi.testclient import TestClient
    from protein_workbench_public.http.app import create_http_app
    app = Workbench(tmp_path)
    app.install('tests.fixtures.host_module:held_module')
    project = app.create_project('Disconnect frontend')
    app.save_project(project['id'], {'nodes': [{'id': 'held', 'type': 'held.node'}]}, {})
    host_module.entered.clear(); host_module.release.clear()
    try:
        with TestClient(create_http_app(app)) as frontend:
            response = frontend.post(f"/api/projects/{project['id']}/runs")
            assert response.status_code == 200
            run = response.json()
            assert host_module.entered.wait(1)
        with TestClient(create_http_app(Workbench(tmp_path))) as reopened:
            assert reopened.get(f"/api/runs/{run['id']}").json()['status'] == 'running'
            assert reopened.put(f"/api/projects/{project['id']}", json={'flow': {}, 'layout': {}}).status_code == 400
            assert reopened.post(f"/api/runs/{run['id']}/cancel").status_code == 200
        host_module.release.set()
        assert wait_run(app, run)['status'] == 'cancelled'
    finally:
        host_module.release.set()


def test_missing_endpoint_blocks_its_group_while_unconnected_valid_group_runs(tmp_path):
    app = Workbench(tmp_path)
    app.install('tests.fixtures.host_module:branch_module')
    project = app.create_project('Dangling connection')
    app.save_project(project['id'], {'nodes': [{'id': 'good', 'type': 'branch.node'}, {'id': 'bad', 'type': 'branch.node'}], 'edges': [{'source': 'absent', 'source_port': 'result', 'target': 'bad', 'target_port': 'source'}]}, {})
    run = wait_run(app, app.start(project['id']))
    assert run['nodes']['good']['status'] == 'succeeded'
    assert run['nodes']['bad']['status'] == 'configuration_blocked'
    assert 'missing node' in str(run['nodes']['bad']['diagnostics'])


def test_terminal_commit_failure_is_reported_instead_of_leaving_a_phantom_running_task(tmp_path, monkeypatch):
    import sqlite3
    from threading import Event
    app = Workbench(tmp_path)
    app.install('tests.fixtures.host_module:branch_module')
    project = app.create_project('Commit unavailable')
    app.save_project(project['id'], {'nodes': [{'id': 'source', 'type': 'branch.node'}]}, {})
    connect = sqlite3.connect
    refused = Event()
    class RefusedCommit(sqlite3.Connection):
        def commit(self):
            if self.in_transaction and (refused.is_set() or self.execute("SELECT COUNT(*) FROM records WHERE kind='package'").fetchone()[0]):
                refused.set()
                raise sqlite3.OperationalError('persistent terminal commit refused')
            return super().commit()
    monkeypatch.setattr(sqlite3, 'connect', lambda *args, **kwargs: connect(*args, **kwargs, factory=RefusedCommit))
    run = app.start(project['id'])
    assert refused.wait(1)
    terminal = wait_run(app, run)
    assert terminal['status'] == 'failed'
    assert 'persistent terminal commit refused' in str(terminal['diagnostics'])
    assert terminal['nodes']['source']['status'] == 'failed'
    assert app.list_packages(project['id']) == []
    assert Workbench(tmp_path).get_run(run['id'])['diagnostics'] == ['Run lease ended without a committed terminal state']
