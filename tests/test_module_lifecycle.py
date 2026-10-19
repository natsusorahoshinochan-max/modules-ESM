"""Module package management through the application's HTTP entry."""
from io import BytesIO
from zipfile import ZipFile
from pathlib import Path
import subprocess
import sys

from fastapi.testclient import TestClient

from protein_workbench_public.bootstrap import create_application


def wheel():
    data = BytesIO()
    with ZipFile(data, 'w') as archive:
        archive.writestr('lifecycle_example/__init__.py', '''from pathlib import Path
from protein_workbench_public.module_api import Module, Node, Outcome, Delivery, OutputPort, InputPort

def execute(call, runtime):
    value = '|'.join(call.settings[name] for name in ('credential', 'model', 'service', 'program'))
    (runtime.workdir / 'result').write_text(value)
    return Outcome(outputs={'result': [Delivery('example.environment', 'data', {'data': 'result'})]})

def module():
    return Module(id='lifecycle.example', name='Lifecycle example', nodes=(Node('lifecycle.first', 'First', execute, outputs={'result': OutputPort('example.environment')}), Node('lifecycle.second', 'Second', execute, inputs={'source': InputPort(('example.environment',))}, outputs={'result': OutputPort('example.environment')})), settings={name: {'type': 'string', 'title': name, 'secret': name == 'credential'} for name in ('credential', 'model', 'service', 'program')}, ui=str(Path(__file__).with_name('ui.js')))
''')
        archive.writestr('lifecycle_example/ui.js', '''export const runtime = { react: 19 }
export function register({ React }) {
  return { viewers: [{ id: 'lifecycle.viewer', name: 'Environment result', formats: ['example.environment'], component: ({ package: pkg }) => React.createElement('p', null, pkg.format) }] }
}
''')
        archive.writestr('lifecycle_example-0.1.dist-info/METADATA', 'Metadata-Version: 2.1\nName: lifecycle-example\nVersion: 0.1\n')
        archive.writestr('lifecycle_example-0.1.dist-info/WHEEL', 'Wheel-Version: 1.0\nGenerator: test\nRoot-Is-Purelib: true\nTag: py3-none-any\n')
        archive.writestr('lifecycle_example-0.1.dist-info/RECORD', '')
    return data.getvalue()


def unsafe_wheel():
    data = BytesIO()
    with ZipFile(data, 'w') as archive:
        archive.writestr('../escaped', 'must not write')
    return data.getvalue()


def install(client):
    return client.post('/api/module-packages', params={'filename': 'lifecycle_example-0.1-py3-none-any.whl', 'entry_point': 'lifecycle_example:module'}, content=wheel())


def test_selected_package_lifecycle_preserves_project_and_delivered_files(tmp_path):
    settings = {'credential': 'chosen-token', 'model': '/existing/model', 'service': 'http://localhost:9000', 'program': '/existing/program'}
    flow = {'nodes': [{'id': 'one', 'type': 'lifecycle.first', 'parameters': {'node_only': 17}, 'inputs': {}}, {'id': 'two', 'type': 'lifecycle.second', 'parameters': {}, 'inputs': {}}], 'edges': [{'source': 'one', 'source_port': 'result', 'target': 'two', 'target_port': 'source'}]}
    with TestClient(create_application(data_root=tmp_path)) as client:
        response = install(client)
        assert response.status_code == 200, response.text
        module = response.json()
        assert module['enabled'] and module['settings'] == {}
        ui = client.get('/api/modules/lifecycle.example/ui.js')
        assert ui.status_code == 200
        assert 'register({ React })' in ui.text
        assert client.put('/api/modules/lifecycle.example/settings', json={'settings': settings}).status_code == 200
        project = client.post('/api/projects', json={'name': 'Kept workflow'}).json()['id']
        assert client.put(f'/api/projects/{project}', json={'flow': flow, 'layout': {'one': {'x': 11, 'y': 2}}}).status_code == 200
        result = client.post(f'/api/projects/{project}/runs').json()
        assert result['status'] == 'succeeded', result
        package = result['nodes']['one']['outputs']['result'][0]
        assert client.get(f'/api/packages/{package}/file', params={'key': 'data'}).content == b'chosen-token|/existing/model|http://localhost:9000|/existing/program'
        assert client.put('/api/modules/lifecycle.example/enabled', json={'enabled': False}).status_code == 200
        assert client.get('/api/modules/lifecycle.example/ui.js').status_code == 400
        unavailable = client.get(f'/api/projects/{project}').json()
        assert unavailable['flow'] == flow
        assert unavailable['layout'] == {'one': {'x': 11, 'y': 2}}
        assert unavailable['missing_modules'] == ['lifecycle.first', 'lifecycle.second']
        rejected = client.post(f'/api/projects/{project}/runs')
        assert rejected.status_code == 400
        assert 'lifecycle.first' in rejected.json()['detail']
        assert client.put('/api/modules/lifecycle.example/enabled', json={'enabled': True}).status_code == 200
        assert client.get(f'/api/projects/{project}').json()['missing_modules'] == []
        assert client.delete('/api/modules/lifecycle.example').status_code == 200
        assert client.get(f'/api/projects/{project}').json()['flow'] == flow
        assert client.get(f'/api/packages/{package}/file', params={'key': 'data'}).status_code == 200
        assert install(client).status_code == 200
        client.put('/api/modules/lifecycle.example/settings', json={'settings': settings})
    cold = subprocess.run([sys.executable, '-c', """
import sys
from pathlib import Path
from fastapi.testclient import TestClient
from protein_workbench_public.bootstrap import create_application
with TestClient(create_application(data_root=Path(sys.argv[1]))) as client:
    assert client.get('/api/projects/' + sys.argv[2]).json()['missing_modules'] == []
    result = client.post('/api/projects/' + sys.argv[2] + '/runs').json()
    assert result['status'] == 'succeeded', result
    assert client.get('/api/packages/' + sys.argv[3] + '/file', params={'key': 'data'}).status_code == 200
""", str(tmp_path), project, package], cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True)
    assert cold.returncode == 0, cold.stderr
    with TestClient(create_application(data_root=tmp_path)) as reopened:
        assert reopened.delete('/api/modules/lifecycle.example').status_code == 200


def test_wheel_rejection_and_failed_factory_leave_no_installed_package(tmp_path):
    with TestClient(create_application(data_root=tmp_path)) as client:
        for filename in ('../outside.whl', '/outside.whl', r'..\outside.whl'):
            response = client.post('/api/module-packages', params={'filename': filename, 'entry_point': 'lifecycle_example:module'}, content=wheel())
            assert response.status_code == 400
        for content in (b'invalid wheel', unsafe_wheel()):
            rejected = client.post('/api/module-packages', params={'filename': 'lifecycle_example-0.1-py3-none-any.whl', 'entry_point': 'lifecycle_example:module'}, content=content)
            assert rejected.status_code == 400
        invalid = client.post('/api/module-packages', params={'filename': 'lifecycle_example-0.1-py3-none-any.whl', 'entry_point': 'lifecycle_example:missing'}, content=wheel())
        assert invalid.status_code == 400
        assert 'missing' in invalid.json()['detail']
        assert not any(tmp_path.glob('module-upload-*'))
        assert list((tmp_path / 'module-packages').iterdir()) == []
        assert 'lifecycle.example' not in [module['id'] for module in client.get('/api/modules').json()]
        assert install(client).status_code == 200
        assert client.delete('/api/modules/lifecycle.example').status_code == 200


def test_unavailable_package_reports_load_error_and_can_be_removed(tmp_path, monkeypatch):
    import importlib
    original = importlib.import_module
    with TestClient(create_application(data_root=tmp_path)) as client:
        assert install(client).status_code == 200

        def missing(name, *args, **kwargs):
            if name == 'lifecycle_example':
                raise ModuleNotFoundError('Required package is absent')
            return original(name, *args, **kwargs)

        monkeypatch.setattr(importlib, 'import_module', missing)
        catalog = client.get('/api/catalog').json()
        module = next(item for item in catalog['modules'] if item['id'] == 'lifecycle.example')
        assert module['available'] is False
        assert 'Required package is absent' in module['load_error']
        assert not any(node['id'].startswith('lifecycle.') for node in catalog['nodes'])
        assert client.put('/api/modules/lifecycle.example/enabled', json={'enabled': True}).status_code == 400
        assert client.delete('/api/modules/lifecycle.example').status_code == 200


def test_selected_wheel_cannot_register_an_unrelated_installed_entry(tmp_path):
    with TestClient(create_application(data_root=tmp_path)) as client:
        response = client.post('/api/module-packages', params={'filename': 'lifecycle_example-0.1-py3-none-any.whl', 'entry_point': 'tests.fixtures.host_module:module'}, content=wheel())
        assert response.status_code == 400
        assert 'selected wheel' in response.json()['detail']
        assert list((tmp_path / 'module-packages').iterdir()) == []
        assert not any(item['id'] == 'test.host' for item in client.get('/api/modules').json())


def test_official_defaults_do_not_restore_user_disabled_or_uninstalled_modules(tmp_path):
    with TestClient(create_application(data_root=tmp_path)) as client:
        modules = client.get('/api/modules').json()
        assert modules and all(item['enabled'] and item['settings'] == {} for item in modules)
        assert client.put('/api/modules/workbench.prediction/enabled', json={'enabled': False}).status_code == 200
        assert client.delete('/api/modules/workbench.simplefold').status_code == 200
    with TestClient(create_application(data_root=tmp_path)) as reopened:
        modules = {item['id']: item for item in reopened.get('/api/modules').json()}
        assert modules['workbench.prediction']['enabled'] is False
        assert 'workbench.simplefold' not in modules
        restored = reopened.post('/api/modules', json={'entry_point': 'modules.simplefold:module'})
        assert restored.status_code == 200
        assert restored.json()['enabled'] is True
