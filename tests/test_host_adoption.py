"""Generic package ownership through the public application boundary."""
import os
import sqlite3

import pytest

from core.host import Workbench
from protein_workbench_public.module_api import Delivery


def input_package(app, project):
    work = app.new_workdir()
    (work / 'first').write_bytes(b'\x00opaque scientific id: original\xff')
    (work / 'second').write_bytes(b'other bytes')
    return app.create_input(project['id'], Delivery('unknown.binary', '../entry', {'../entry': 'first', 'a\\b': 'second'}), work)


def test_adoption_copies_all_opaque_files_with_new_storage_identity(tmp_path):
    app = Workbench(tmp_path)
    source = app.create_project('source')
    target = app.create_project('target')
    original = input_package(app, source)
    adopted = app.adopt(target['id'], original['id'])
    assert adopted['id'] != original['id']
    assert adopted['project_id'] == target['id']
    assert {k: adopted[k] for k in ('format', 'entry', 'files')} == {k: original[k] for k in ('format', 'entry', 'files')}
    reopened = Workbench(tmp_path)
    for key in original['files']:
        with app.package(original['id']).open(key) as before, reopened.package(adopted['id']).open(key) as after:
            assert after.read() == before.read()
    assert app.adopt(target['id'], original['id'])['id'] not in (original['id'], adopted['id'])


def test_delete_source_and_export_remain_independent_of_producer(tmp_path):
    import json
    import zipfile
    from core.host import HostError
    app = Workbench(tmp_path / 'store')
    research = tmp_path / 'research.pdb'
    research.write_bytes(b'original research')
    source = app.create_project('source')
    target = app.create_project('target')
    original = input_package(app, source)
    adopted = app.adopt(target['id'], original['id'])
    app.delete_project(source['id'])
    with pytest.raises(HostError, match='Unknown project'):
        app.get_project(source['id'])
    with pytest.raises(HostError, match='Unknown package'):
        app.package(original['id'])
    assert research.read_bytes() == b'original research'
    app = Workbench(tmp_path / 'store')
    archive = app.export_package(adopted['id'])
    try:
        with zipfile.ZipFile(archive) as zipped:
            descriptor = json.loads(zipped.read('package.json'))
            assert descriptor['entry'] == '../entry'
            assert descriptor['format'] == 'unknown.binary'
            assert descriptor['files'] == [{'key': '../entry', 'member': 'files/000000'}, {'key': 'a\\b', 'member': 'files/000001'}]
            assert zipped.read('files/000000') == b'\x00opaque scientific id: original\xff'
            assert zipped.read('files/000001') == b'other bytes'
            assert len(set(zipped.namelist())) == 3
    finally:
        archive.unlink()
    assert app.adopt(target['id'], adopted['id'])['id'] != adopted['id']


def test_running_project_rejects_mutation_across_host_instances_without_waiting(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from core.host import HostError
    from tests.fixtures.host_module import entered, release
    app = Workbench(tmp_path)
    other = Workbench(tmp_path)
    project = app.create_project('running')
    source = app.create_project('source')
    package = input_package(app, source)
    app.install('tests.fixtures.host_module:held_module')
    app.save_project(project['id'], {'nodes': [{'id': 'held', 'type': 'held.node'}], 'edges': []}, {})
    entered.clear()
    release.clear()
    with ThreadPoolExecutor() as pool:
        future = pool.submit(app.start, project['id'])
        try:
            assert entered.wait(5)
            actions = [lambda: other.save_project(project['id'], {}, {}), lambda: other.adopt(project['id'], package['id']), lambda: other.delete_project(project['id']), lambda: other.start(project['id'])]
            for action in actions:
                with pytest.raises(HostError, match='running'):
                    action()
            work = other.new_workdir()
            (work / 'data').write_bytes(b'data')
            with pytest.raises(HostError, match='running'):
                other.create_input(project['id'], Delivery('binary', 'data', {'data': 'data'}), work)
            assert not work.exists()
            assert other.list_packages(project['id']) == []
            assert other.get_project(project['id'])['name'] == 'running'
        finally:
            release.set()
        assert future.result(timeout=5)['status'] == 'succeeded'
    other.save_project(project['id'], {'nodes': [], 'edges': []}, {})
    other.adopt(project['id'], package['id'])


def test_raw_cross_project_input_cannot_bypass_adoption(tmp_path):
    from core.host import HostError
    app = Workbench(tmp_path)
    app.install('tests.fixtures.host_module:module')
    source = app.create_project('source')
    target = app.create_project('target')
    work = app.new_workdir()
    (work / 'data').write_bytes(b'data')
    package = app.create_input(source['id'], Delivery('independent.request', 'data', {'data': 'data'}), work)
    flow = {'nodes': [{'id': 'encode', 'type': 'independent.encode', 'inputs': {'source': [package['id']]}}], 'edges': []}
    app.save_project(target['id'], flow, {})
    with pytest.raises(HostError, match='owned by.*project|adopt'):
        app.start(target['id'])
    adopted = app.adopt(target['id'], package['id'])
    flow['nodes'][0]['inputs']['source'] = [adopted['id']]
    app.save_project(target['id'], flow, {})
    assert app.start(target['id'])['status'] == 'succeeded'


@pytest.mark.parametrize('failure', ['missing', 'write', 'rename', 'commit'])
def test_failed_adoption_exposes_no_partial_result(tmp_path, monkeypatch, failure):
    from core.host import HostError
    app = Workbench(tmp_path)
    source = app.create_project('source')
    target = app.create_project('target')
    original = input_package(app, source)
    existing = input_package(app, target)
    before = set((tmp_path / 'packages').iterdir())
    if failure == 'missing':
        (tmp_path / 'packages' / original['id'] / '1').unlink()
        expected = 'a.*b'
    elif failure == 'write':
        fsync = os.fsync
        calls = [0]
        def fail_later(fd):
            calls[0] += 1
            if calls[0] == 2:
                raise OSError('later file disk full')
            return fsync(fd)
        monkeypatch.setattr(os, 'fsync', fail_later)
        expected = 'a.*b.*disk full'
    elif failure == 'rename':
        def fail_rename(*args):
            raise OSError('rename refused')
        monkeypatch.setattr(os, 'replace', fail_rename)
        expected = 'rename refused'
    else:
        connect = sqlite3.connect
        class CommitFailure(sqlite3.Connection):
            def commit(self):
                count = self.execute("SELECT count(*) FROM records WHERE kind='package'").fetchone()[0]
                if count > 2:
                    raise sqlite3.OperationalError('adoption commit refused')
                return super().commit()
        monkeypatch.setattr(sqlite3, 'connect', lambda *a, **k: connect(*a, **k, factory=CommitFailure))
        expected = 'adoption commit refused'
    with pytest.raises((HostError, OSError), match=expected):
        app.adopt(target['id'], original['id'])
    assert app.list_packages(target['id']) == [existing]
    assert set((tmp_path / 'packages').iterdir()) == before
    with app.package(original['id']).open(original['entry']) as stream:
        assert stream.read() == b'\x00opaque scientific id: original\xff'


def test_export_missing_later_file_fails_before_http_success_and_cleans_archive(tmp_path):
    from fastapi.testclient import TestClient
    from protein_workbench_public.http.app import create_http_app
    app = Workbench(tmp_path)
    source = app.create_project('source')
    package = input_package(app, source)
    (tmp_path / 'packages' / package['id'] / '1').unlink()
    with TestClient(create_http_app(app)) as client:
        response = client.get(f"/api/packages/{package['id']}/export.zip")
        assert response.status_code == 400
        assert repr('a\\b') in response.json()['detail']
    assert list((tmp_path / 'work').glob('export-*')) == []


@pytest.mark.parametrize('failure', ['stage', 'commit'])
def test_failed_source_deletion_restores_project_and_all_files(tmp_path, monkeypatch, failure):
    from pathlib import Path
    from core.host import HostError
    app = Workbench(tmp_path)
    source = app.create_project('source')
    package = input_package(app, source)
    if failure == 'stage':
        rename = Path.rename
        def fail_stage(path, target):
            if path.parent == tmp_path / 'packages':
                raise OSError('cannot stage owned files')
            return rename(path, target)
        monkeypatch.setattr(Path, 'rename', fail_stage)
        expected = 'cannot stage'
    else:
        connect = sqlite3.connect
        class CommitFailure(sqlite3.Connection):
            def commit(self):
                if not self.execute("SELECT 1 FROM records WHERE kind='project'").fetchone():
                    raise sqlite3.OperationalError('delete commit refused')
                return super().commit()
        monkeypatch.setattr(sqlite3, 'connect', lambda *a, **k: connect(*a, **k, factory=CommitFailure))
        expected = 'delete commit refused'
    with pytest.raises((HostError, OSError), match=expected):
        app.delete_project(source['id'])
    assert app.get_project(source['id'])['name'] == 'source'
    assert app.list_packages(source['id']) == [package]
    with app.package(package['id']).open(package['entry']) as stream:
        assert stream.read() == b'\x00opaque scientific id: original\xff'
    assert list((tmp_path / 'work').iterdir()) == []


def test_source_deletion_waits_for_in_progress_adoption_file_copy(tmp_path, monkeypatch):
    from threading import Event
    from concurrent.futures import ThreadPoolExecutor
    app = Workbench(tmp_path)
    other = Workbench(tmp_path)
    source = app.create_project('source')
    target = app.create_project('target')
    package = input_package(app, source)
    copying, release, deleting = Event(), Event(), Event()
    fsync = os.fsync
    def hold_copy(fd):
        copying.set()
        assert release.wait(5)
        return fsync(fd)
    monkeypatch.setattr(os, 'fsync', hold_copy)
    def delete():
        deleting.set()
        other.delete_project(source['id'])
    with ThreadPoolExecutor() as pool:
        adoption = pool.submit(app.adopt, target['id'], package['id'])
        try:
            assert copying.wait(5)
            deletion = pool.submit(delete)
            assert deleting.wait(5)
            assert not deletion.done()
        finally:
            release.set()
        adopted = adoption.result(timeout=5)
        deletion.result(timeout=5)
    with other.package(adopted['id']).open('a\\b') as stream:
        assert stream.read() == b'other bytes'


def test_http_delete_invalidates_idle_upload_and_rejects_active_upload(tmp_path):
    import asyncio
    import httpx
    from protein_workbench_public.http.app import create_http_app
    app = Workbench(tmp_path)
    project = app.create_project('uploads')
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=create_http_app(app)), base_url='http://test') as client:
            token = (await client.post(f"/api/projects/{project['id']}/uploads")).json()['upload_id']
            entered, release = asyncio.Event(), asyncio.Event()
            async def body():
                yield b'first'
                entered.set()
                await release.wait()
                yield b'last'
            upload = asyncio.create_task(client.put(f"/api/projects/{project['id']}/uploads/{token}/files", params={'key': 'entry'}, content=body()))
            try:
                await asyncio.wait_for(entered.wait(), 5)
                deleted = await client.delete(f"/api/projects/{project['id']}")
                assert deleted.status_code == 400
                assert 'active file uploads' in deleted.json()['detail']
            finally:
                release.set()
            assert (await upload).status_code == 200
            assert (await client.delete(f"/api/projects/{project['id']}")).status_code == 200
            stale = await client.post(f"/api/projects/{project['id']}/uploads/{token}/commit", json={'format': 'unknown', 'entry': 'entry', 'files': {'entry': 'entry'}})
            assert stale.status_code == 400
            assert 'Upload does not exist' in stale.json()['detail']
    asyncio.run(scenario())
    assert list((tmp_path / 'work').iterdir()) == []


def test_zip_response_removes_completed_archive_when_client_disconnects(tmp_path):
    import asyncio
    from protein_workbench_public.http.app import create_http_app
    app = Workbench(tmp_path)
    source = app.create_project('source')
    package = input_package(app, source)
    http_app = create_http_app(app)
    async def receive():
        return {'type': 'http.request', 'body': b'', 'more_body': False}
    async def send(message):
        if message['type'] == 'http.response.body':
            raise RuntimeError('client disconnected')
    scope = {'type': 'http', 'asgi': {'version': '3.0', 'spec_version': '2.4'}, 'method': 'GET', 'path': f"/api/packages/{package['id']}/export.zip", 'query_string': b'', 'headers': [], 'scheme': 'http', 'server': ('test', 80), 'client': ('test', 1), 'root_path': ''}
    with pytest.raises(RuntimeError, match='client disconnected'):
        asyncio.run(http_app(scope, receive, send))
    assert list((tmp_path / 'work').glob('export-*')) == []


def test_zip_index_preserves_colliding_opaque_keys_and_invalid_scientific_references(tmp_path):
    import json
    import zipfile
    app = Workbench(tmp_path)
    source = app.create_project('source')
    target = app.create_project('target')
    keys = ['../escape', '/absolute', 'a/b', 'a\\b', 'β/structure', 'package.json', 'nul\x00key']
    work = app.new_workdir()
    files = {}
    for i, key in enumerate(keys):
        filename = str(i)
        (work / filename).write_bytes(b'{"scientific_reference":"absent","structure":"missing.cif"}')
        files[key] = filename
    original = app.create_input(source['id'], Delivery('unknown.invalid-science', keys[0], files), work)
    adopted = app.adopt(target['id'], original['id'])
    archive = app.export_package(adopted['id'])
    try:
        with zipfile.ZipFile(archive) as zipped:
            index = json.loads(zipped.read('package.json'))
            assert [item['key'] for item in index['files']] == keys
            assert zipped.namelist() == ['package.json'] + [f'files/{i:06d}' for i in range(7)]
            for item in index['files']:
                assert json.loads(zipped.read(item['member']))['scientific_reference'] == 'absent'
    finally:
        archive.unlink()
