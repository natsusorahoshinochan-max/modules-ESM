"""Warm application instances converge on the current installation."""
from io import BytesIO
import subprocess
import sys
from zipfile import ZipFile

import pytest

from fastapi.testclient import TestClient

from protein_workbench_public.bootstrap import create_application
from tests.test_module_lifecycle import INSTALL_HEADERS
from tests.run_helpers import wait_response


def package(label, *, namespace=False, module_id='reinstall.example', python_name='warm_example', with_ui=True):
    data = BytesIO()
    with ZipFile(data, 'w') as archive:
        folder = f'shared_warm/{python_name}' if namespace else python_name
        archive.writestr(folder + '/__init__.py', f'''from pathlib import Path
from protein_workbench_public.module_api import Module, Node, Outcome, OutputPort, Delivery
def execute(call, runtime):
    (runtime.workdir / 'data').write_text({label!r})
    return Outcome(outputs={{'result': [Delivery('warm.text', 'data', {{'data': 'data'}})]}})
def module():
    return Module({module_id!r}, {label!r}, nodes=(Node({module_id + '.node'!r}, {label!r}, execute, outputs={{'result': OutputPort('warm.text')}}),), ui=str(Path(__file__).with_name('ui.js')) if {with_ui!r} else None)
''')
        archive.writestr(folder + '/ui.js', f"export const label = {label!r}; export const runtime = {{react:19}}; export function register() {{return {{actions:[{{id:'warm.action',name:label,component:()=>null}}]}}}}")
        archive.writestr('warm_example-0.1.dist-info/METADATA', 'Metadata-Version: 2.1\nName: warm-example\nVersion: 0.1\n')
        archive.writestr('warm_example-0.1.dist-info/WHEEL', 'Wheel-Version: 1.0\nRoot-Is-Purelib: true\nTag: py3-none-any\n')
        archive.writestr('warm_example-0.1.dist-info/RECORD', '')
    return data.getvalue()


def install(client, content, entry='warm_example:module'):
    return client.post('/api/module-packages', headers=INSTALL_HEADERS, params={'filename': 'warm_example-0.1-py3-none-any.whl', 'entry_point': entry}, content=content)


def assert_execution(client, module_id, expected):
    project = client.post('/api/projects', json={'name':'Current module'}).json()['id']
    flow = {'nodes':[{'id':'read','type':module_id+'.node','parameters':{},'inputs':{}}],'edges':[]}
    assert client.put(f'/api/projects/{project}', json={'flow':flow,'layout':{}}).status_code == 200
    run = wait_response(client, client.post(f'/api/projects/{project}/runs')).json()
    assert run['status'] == 'succeeded', run
    result = run['nodes']['read']['outputs']['result'][0]
    assert client.get(f'/api/packages/{result}/file', params={'key':'data'}).text == expected


@pytest.mark.parametrize("with_ui", [True, False])
def test_warm_instance_reinstalls_after_another_process_uninstalls(tmp_path, with_ui):
    with TestClient(create_application(data_root=tmp_path)) as warm:
        assert install(warm, package('original', with_ui=with_ui)).status_code == 200
        other = subprocess.run([sys.executable, '-c', '''from pathlib import Path
import sys
from fastapi.testclient import TestClient
from protein_workbench_public.bootstrap import create_application
with TestClient(create_application(data_root=Path(sys.argv[1]))) as client:
    assert client.delete('/api/modules/reinstall.example').status_code == 200
''', str(tmp_path)], capture_output=True, text=True, timeout=20)
        assert other.returncode == 0, other.stderr
        restored = install(warm, package('replacement', with_ui=with_ui))
        assert restored.status_code == 200, restored.text
        assert next(item for item in warm.get('/api/catalog').json()['modules'] if item['id'] == 'reinstall.example')['name'] == 'replacement'
        assert_execution(warm, 'reinstall.example', 'replacement')
        warm.delete('/api/modules/reinstall.example')


def test_warm_instance_reads_other_process_replacement_without_stealing_shared_namespace(tmp_path):
    entry = 'shared_warm.alpha:module'
    with TestClient(create_application(data_root=tmp_path)) as warm:
        assert install(warm, package('old', namespace=True, python_name='alpha'), entry).status_code == 200
        beta = install(warm, package('independent', namespace=True, python_name='beta', module_id='other.example'), 'shared_warm.beta:module')
        assert beta.status_code == 200, beta.text
        chosen = tmp_path / 'replacement.whl'
        chosen.write_bytes(package('new', namespace=True, python_name='alpha'))
        other = subprocess.run([sys.executable, '-c', '''from pathlib import Path
import sys
from fastapi.testclient import TestClient
from protein_workbench_public.bootstrap import create_application
from tests.test_module_reinstallation import install
with TestClient(create_application(data_root=Path(sys.argv[1]))) as client:
    assert client.delete('/api/modules/reinstall.example').status_code == 200
    result = install(client, Path(sys.argv[2]).read_bytes(), 'shared_warm.alpha:module')
    assert result.status_code == 200, result.text
''', str(tmp_path), str(chosen)], capture_output=True, text=True, timeout=20)
        assert other.returncode == 0, other.stderr
        catalog = warm.get('/api/catalog').json()
        names = {item['id']: item['name'] for item in catalog['nodes']}
        assert names['reinstall.example.node'] == 'new'
        assert names['other.example.node'] == 'independent'
        assert_execution(warm, 'reinstall.example', 'new')
        assert_execution(warm, 'other.example', 'independent')
        for module_id in ('reinstall.example', 'other.example'):
            assert warm.put(f'/api/modules/{module_id}/enabled', json={'enabled': True}).status_code == 200
            warm.delete(f'/api/modules/{module_id}')


def test_reinstallation_replaces_ui_address_and_rejects_previous_installation(tmp_path):
    with TestClient(create_application(data_root=tmp_path)) as client:
        first = install(client, package('old')).json()
        identity = first['installation_id']
        catalog = client.get('/api/catalog').json()
        old_url = next(item['ui_url'] for item in catalog['modules'] if item['id'] == first['id'])
        assert "'old'" in client.get(old_url).text
        disabled = client.put('/api/modules/reinstall.example/enabled', json={'enabled': False}).json()
        assert disabled['installation_id'] == identity
        assert client.get(old_url).status_code == 400
        enabled = client.put('/api/modules/reinstall.example/enabled', json={'enabled': True}).json()
        assert enabled['installation_id'] == identity
        client.delete('/api/modules/reinstall.example')
        second = install(client, package('new')).json()
        assert second['installation_id'] != identity
        assert client.get(old_url).status_code == 409
        new_url = next(item['ui_url'] for item in client.get('/api/catalog').json()['modules'] if item['id'] == first['id'])
        assert new_url != old_url
        assert "'new'" in client.get(new_url).text
        client.delete('/api/modules/reinstall.example')


def test_candidate_cannot_take_another_valid_installations_python_namespace(tmp_path):
    with TestClient(create_application(data_root=tmp_path)) as client:
        assert install(client, package('valid owner')).status_code == 200
        conflict = install(client, package('would replace', module_id='other.example'))
        assert conflict.status_code == 400
        assert 'namespace' in conflict.json()['detail']
        node = next(item for item in client.get('/api/catalog').json()['nodes'] if item['id'] == 'reinstall.example.node')
        assert node['name'] == 'valid owner'
        assert not any(item['id'] == 'other.example' for item in client.get('/api/modules').json())
        client.delete('/api/modules/reinstall.example')


def test_missing_package_directory_does_not_leave_a_no_ui_module_runnable(tmp_path):
    import shutil
    with TestClient(create_application(data_root=tmp_path)) as client:
        response = install(client, package('available', with_ui=False))
        assert response.status_code == 200, response.text
        shutil.rmtree(response.json()['package_path'])
        module = next(item for item in client.get('/api/modules').json() if item['id'] == 'reinstall.example')
        assert module['available'] is False
        assert 'directory is missing' in module['load_error']
        assert not any(item['id'] == 'reinstall.example.node' for item in client.get('/api/catalog').json()['nodes'])
        assert client.put('/api/modules/reinstall.example/enabled', json={'enabled':True}).status_code == 400
        assert client.delete('/api/modules/reinstall.example').status_code == 200
        restored = install(client, package('restored', with_ui=False))
        assert restored.status_code == 200, restored.text
        assert_execution(client, 'reinstall.example', 'restored')
        client.delete('/api/modules/reinstall.example')


def test_cold_installer_reserves_another_recorded_python_namespace(tmp_path):
    with TestClient(create_application(data_root=tmp_path)) as warm:
        assert install(warm, package('valid owner')).status_code == 200
        candidate = tmp_path / 'candidate.whl'
        candidate.write_bytes(package('would steal', module_id='other.example'))
        process = subprocess.run([sys.executable, '-c', '''from pathlib import Path
import sys
from fastapi.testclient import TestClient
from protein_workbench_public.bootstrap import create_application
from tests.test_module_reinstallation import install
with TestClient(create_application(data_root=Path(sys.argv[1]))) as client:
    result = install(client, Path(sys.argv[2]).read_bytes())
    assert result.status_code == 400, result.text
    assert 'namespace' in result.json()['detail']
    node = next(item for item in client.get('/api/catalog').json()['nodes'] if item['id'] == 'reinstall.example.node')
    assert node['name'] == 'valid owner'
''', str(tmp_path), str(candidate)], capture_output=True, text=True, timeout=20)
        assert process.returncode == 0, process.stderr
        warm.delete('/api/modules/reinstall.example')
