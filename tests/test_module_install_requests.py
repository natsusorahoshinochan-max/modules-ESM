"""Browser request admission precedes all selected-wheel side effects."""
import asyncio

import pytest

from protein_workbench_public.bootstrap import create_application


@pytest.mark.parametrize('headers,status', [
    ({'content-type':'text/plain','origin':'https://attacker.example','sec-fetch-site':'cross-site','sec-fetch-mode':'no-cors'}, 403),
    ({'content-type':'application/octet-stream','x-workbench-module-package':'wheel','sec-fetch-site':'cross-site'}, 403),
    ({'content-type':'application/octet-stream','x-workbench-module-package':'wheel','sec-fetch-mode':'no-cors'}, 403),
    ({'content-type':'application/octet-stream','x-workbench-module-package':'wheel','origin':'null'}, 403),
    ({'content-type':'application/octet-stream'}, 415),
    ({'content-type':'text/plain','x-workbench-module-package':'wheel'}, 415),
])
def test_rejected_install_never_reads_body_or_creates_staging(tmp_path, headers, status):
    app = create_application(data_root=tmp_path)
    def forbidden(*args):
        pytest.fail('Rejected request reached installer')
    app.state.workbench.install_package = forbidden
    before = set(tmp_path.iterdir())
    messages = []
    async def receive():
        pytest.fail('Rejected request read its body')
    async def send(message):
        messages.append(message)
    scope = {'type':'http','asgi':{'version':'3.0'},'http_version':'1.1','method':'POST','scheme':'http','path':'/api/module-packages','raw_path':b'/api/module-packages','query_string':b'filename=chosen-0.1-py3-none-any.whl&entry_point=chosen:module','headers':[(name.encode(),value.encode()) for name,value in headers.items()],'server':('localhost',8000),'client':('127.0.0.1',1234),'root_path':''}
    asyncio.run(app(scope, receive, send))
    assert next(item['status'] for item in messages if item['type'] == 'http.response.start') == status
    assert set(tmp_path.iterdir()) == before


def test_vite_style_selected_request_installs_and_cross_origin_preflight_is_not_authorized(tmp_path):
    from fastapi.testclient import TestClient
    from tests.test_module_lifecycle import INSTALL_HEADERS, wheel
    with TestClient(create_application(data_root=tmp_path)) as client:
        preflight = client.options('/api/module-packages', headers={'Origin':'https://attacker.example', 'Access-Control-Request-Method':'POST', 'Access-Control-Request-Headers':'x-workbench-module-package,content-type'})
        assert 'access-control-allow-origin' not in preflight.headers
        response = client.post('/api/module-packages', params={'filename':'lifecycle_example-0.1-py3-none-any.whl','entry_point':'lifecycle_example:module'}, content=wheel(), headers={**INSTALL_HEADERS,'Origin':'http://localhost:5173','Sec-Fetch-Site':'same-origin','Sec-Fetch-Mode':'cors'})
        assert response.status_code == 200, response.text
        client.delete('/api/modules/lifecycle.example')
        response = client.post('/api/modules', content=b'{"entry_point":"modules.folding:module"}')
        assert response.status_code in (415, 422)
