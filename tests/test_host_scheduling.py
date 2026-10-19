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
    monkeypatch.setattr(sqlite3, 'connect', connect)
    app.install('tests.fixtures.host_module:held_module')
    app.save_project(project['id'], {'nodes': [{'id': 'held', 'type': 'held.node'}]}, {})
    host_module.entered.clear(); host_module.release.clear()
    newer = app.start(project['id'])
    try:
        assert host_module.entered.wait(1)
        for observer in (app, Workbench(tmp_path)):
            assert observer.get_run(run['id'])['status'] == 'failed'
            assert observer.get_run(newer['id'])['status'] == 'running'
        app.cancel_run(run['id'])
        assert app.get_run(newer['id'])['status'] == 'running'
    finally:
        host_module.release.set()
        wait_run(app, newer)


def test_workdir_allocation_failure_only_stops_the_node_and_its_dependents(tmp_path, monkeypatch):
    import tempfile
    from fastapi.testclient import TestClient
    from protein_workbench_public.http.app import create_http_app
    from tests.run_helpers import wait_response
    app = Workbench(tmp_path)
    app.install('tests.fixtures.host_module:branch_module')
    project = app.create_project('Allocation failure')
    flow = {'nodes': [{'id': name, 'type': 'branch.node'} for name in ('one', 'dependent', 'isolated')], 'edges': [{'source': 'one', 'source_port': 'result', 'target': 'dependent', 'target_port': 'source'}]}
    app.save_project(project['id'], flow, {})
    allocate = tempfile.mkdtemp
    failed = False
    def once(*args, **kwargs):
        nonlocal failed
        if kwargs.get('prefix') == 'execution-' and not failed:
            failed = True
            raise OSError('one execution directory allocation refused')
        return allocate(*args, **kwargs)
    monkeypatch.setattr(tempfile, 'mkdtemp', once)
    with TestClient(create_http_app(app)) as client:
        run = wait_response(client, client.post(f"/api/projects/{project['id']}/runs")).json()
        assert run['status'] == 'failed'
        assert {key: value['status'] for key, value in run['nodes'].items()} == {'one': 'failed', 'dependent': 'blocked', 'isolated': 'succeeded'}
        assert 'allocation refused' in str(run['nodes']['one']['diagnostics'])
        output = run['nodes']['isolated']['outputs']['result'][0]
        assert client.get(f'/api/packages/{output}/file', params={'key': 'data'}).content == b'complete result'
        assert not client.get(f"/api/projects/{project['id']}").json()['running']


def test_first_running_commit_already_has_its_execution_lease(tmp_path, monkeypatch):
    import json
    import sqlite3
    app = Workbench(tmp_path)
    project = app.create_project('Lease before record')
    other = Workbench(tmp_path)
    connect = sqlite3.connect
    observed = []
    class ObserveCommit(sqlite3.Connection):
        def commit(self):
            run = self.execute("SELECT data FROM records WHERE kind='run'").fetchone() if self.in_transaction and not observed else None
            super().commit()
            if run:
                observed.append('checking')
                observed[0] = other.get_run(json.loads(run[0])['id'])['status']
    monkeypatch.setattr(sqlite3, 'connect', lambda *args, **kwargs: connect(*args, **kwargs, factory=ObserveCommit))
    run = wait_run(app, app.start(project['id']))
    assert observed == ['running']
    assert run['status'] == 'succeeded'


def test_thread_dispatch_failure_reports_terminal_state_and_releases_both_leases(tmp_path, monkeypatch):
    from threading import Thread
    app = Workbench(tmp_path)
    app.install('tests.fixtures.host_module:branch_module')
    project = app.create_project('Dispatch')
    app.save_project(project['id'], {'nodes': [{'id': 'one', 'type': 'branch.node'}]}, {})
    def refuse(_thread):
        raise RuntimeError('thread dispatch refused')
    with monkeypatch.context() as fault:
        fault.setattr(Thread, 'start', refuse)
        with pytest.raises(RuntimeError, match='dispatch refused'):
            app.start(project['id'])
    failed = app.list_runs(project['id'])[0]
    assert failed['status'] == 'failed'
    assert failed['nodes']['one']['status'] == 'blocked'
    assert 'dispatch refused' in str(failed['diagnostics'])
    app.save_project(project['id'], {'nodes': [], 'edges': []}, {})
    assert wait_run(app, app.start(project['id']))['status'] == 'succeeded'


def test_workdir_cleanup_failure_keeps_received_output_and_continues_independent_group(tmp_path, monkeypatch):
    import shutil
    app = Workbench(tmp_path)
    app.install('tests.fixtures.host_module:branch_module')
    project = app.create_project('Cleanup')
    app.save_project(project['id'], {'nodes': [{'id': name, 'type': 'branch.node'} for name in ('one', 'other')]}, {})
    remove = shutil.rmtree
    failed = False
    def once(path, *args, **kwargs):
        nonlocal failed
        if path.parent == tmp_path / 'work' and path.name.startswith('execution-') and not failed:
            failed = True
            raise OSError('directory cleanup refused')
        return remove(path, *args, **kwargs)
    monkeypatch.setattr(shutil, 'rmtree', once)
    run = wait_run(app, app.start(project['id']))
    assert run['status'] == 'failed'
    assert run['nodes']['one']['status'] == 'failed'
    assert 'cleanup refused' in str(run['nodes']['one']['diagnostics'])
    assert run['nodes']['other']['status'] == 'succeeded'
    with app.package(run['nodes']['one']['outputs']['result'][0]).open('data') as stream:
        assert stream.read() == b'complete result'


def test_fatal_commit_failure_keeps_received_results_and_labels_unstarted_independent_nodes(tmp_path, monkeypatch):
    import sqlite3
    app = Workbench(tmp_path)
    app.install('tests.fixtures.host_module:branch_module')
    project = app.create_project('Fatal commit')
    app.save_project(project['id'], {'nodes': [{'id': name, 'type': 'branch.node'} for name in ('one', 'dependent', 'isolated')], 'edges': [{'source': 'one', 'source_port': 'result', 'target': 'dependent', 'target_port': 'source'}]}, {})
    connect = sqlite3.connect
    refused = False
    class FailAfterFirst(sqlite3.Connection):
        def commit(self):
            nonlocal refused
            if self.in_transaction and (refused or self.execute("SELECT COUNT(*) FROM records WHERE kind='package'").fetchone()[0] > 1):
                refused = True
                raise sqlite3.OperationalError('second result commit refused')
            return super().commit()
    monkeypatch.setattr(sqlite3, 'connect', lambda *args, **kwargs: connect(*args, **kwargs, factory=FailAfterFirst))
    run = wait_run(app, app.start(project['id']))
    assert run['status'] == 'failed'
    assert {name: node['status'] for name, node in run['nodes'].items()} == {'one': 'succeeded', 'dependent': 'failed', 'isolated': 'blocked'}
    assert 'before this node started' in run['nodes']['isolated']['diagnostics'][0]
    assert 'upstream' not in str(run['nodes']['isolated']['diagnostics']).lower()
    assert len(app.list_packages(project['id'])) == 1
    with app.package(run['nodes']['one']['outputs']['result'][0]).open('data') as stream:
        assert stream.read() == b'complete result'
