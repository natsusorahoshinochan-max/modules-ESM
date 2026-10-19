"""Batch control with the real adapters, isolating only SDK/worker execution."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from core.host import Workbench
from protein_workbench_public.module_api import Delivery
from tests.run_helpers import wait_run


@pytest.mark.parametrize('tool', ['workbench.esmfold2.local', 'workbench.esmfold2.remote', 'workbench.simplefold.local'])
def test_real_adapter_batch_stops_at_terminal_failure_and_continues_original_requests(tmp_path, monkeypatch, tool):
    calls = []
    failing = [True]
    resources = tmp_path / 'resources'
    resources.mkdir()
    for name in ('simplefold_100M.ckpt', 'esm2.pt', 'esm2-contact-regression.pt', 'ccd.pkl'):
        (resources / name).touch()
    if tool.endswith('.remote'):
        from modules.folding.adapters import create_remote
        class Client:
            def fold(self, **kwargs):
                calls.append((kwargs['sequence'], kwargs['config']))
                if kwargs['sequence'] == 'DEF' and failing[0]:
                    return ValueError('SDK final failure after applicable attempts')
                class Protein:
                    def to_pdb(self, stream):
                        stream.write(kwargs['sequence'])
                return SimpleNamespace(plddt=[.8, .9, .7], ptm=.75, to_protein_chain=lambda: Protein())
            def close(self):
                pass
        def client_factory(**kwargs):
            assert set(kwargs) == {'model', 'url', 'token', 'request_timeout'}  # Retry defaults belong to SDK.
            return Client()
        monkeypatch.setattr('modules.folding.adapters.create_remote', lambda settings: create_remote(settings, client_factory=client_factory, config_factory=lambda **kwargs: kwargs))
        parameters = {'num_sampling_steps': 17}
    else:
        parameters = {'seed': 0, 'num_steps': 7} if 'simplefold' in tool else {'seed': 0, 'num_sampling_steps': 17}
        class Worker:
            returncode = 0
            def __init__(self, args, **kwargs):
                assert args[1:4] == ['-m', 'protein_workbench_public.model_validation', '--']
                payload = json.loads(Path(args[-1]).read_text())
                calls.append((payload['sequence'], payload['parameters']))
                if payload['sequence'] == 'DEF' and failing[0]:
                    self.returncode = 1
                    kwargs['stderr'].write('terminal model process failure\n')
                    kwargs['stderr'].flush()
                    return
                work = Path(payload['workdir'])
                (work / 'model.pdb').write_text(payload['sequence'])
                result = {'structure_path': 'model.pdb', 'plddt': [.8, .9, .7], 'ptm': .75}
                name = 'simplefold' if 'simplefold' in tool else 'esmfold2'
                (work / (name + '-result.json')).write_text(json.dumps(result))
            def poll(self):
                return self.returncode
        monkeypatch.setattr('subprocess.Popen', Worker)
    app = Workbench(tmp_path / 'app')
    app.install('modules.folding:module')
    if 'simplefold' in tool:
        app.install('modules.simplefold:module')
        app.configure('workbench.simplefold', {'model_path': str(resources), 'esm2_source': str(resources), 'esm2_checkpoint': str(resources / 'esm2.pt'), 'ccd_path': str(resources / 'ccd.pkl')})
    else:
        app.configure('workbench.prediction', {'model_path': str(resources), 'language_model_path': str(resources), 'token': 'contract-credential'})
    project = app.create_project('Adapter batch')
    work = app.new_workdir()
    (work / 'batch').write_text(json.dumps({'objects': [{'id': str(index), 'sequence': sequence} for index, sequence in enumerate(['ACD', 'DEF', 'GHI'])]}))
    package = app.create_input(project['id'], Delivery('workbench.sequence', 'data', {'data': 'batch'}), work)
    flow = {'nodes': [{'id': 'predict', 'type': 'workbench.predict', 'inputs': {'sequence': [package['id']]}, 'tools': {'predictor': tool}, 'tool_parameters': {'predictor': parameters}}], 'edges': []}
    app.save_project(project['id'], flow, {})
    partial = wait_run(app, app.start(project['id']))
    assert partial['status'] == 'failed', partial
    assert [sequence for sequence, _ in calls] == ['ACD', 'DEF']
    assert partial['nodes']['predict']['continuation'] == {'completed': 1}
    failing[0] = False
    complete = wait_run(app, app.continue_run(partial['id'], 'predict'))
    assert complete['status'] == 'succeeded', complete
    assert [sequence for sequence, _ in calls] == ['ACD', 'DEF', 'DEF', 'GHI']
    for _, observed in calls:
        assert all(observed[name] == value for name, value in parameters.items())
    package = app.package(complete['nodes']['predict']['outputs']['structure'][0])
    with package.open(package.entry) as stream:
        document = json.load(stream)
    for obj in document['objects']:
        with package.open(obj['structure']['file']) as stream:
            assert stream.read().decode() == obj['sequence']
        with package.open(obj['confidence']['plddt']['file']) as stream:
            assert json.load(stream)['plddt'] == [.8, .9, .7]


def test_biohub_sdk_default_attempt_limit_is_exhausted_before_batch_stops(tmp_path, monkeypatch):
    import httpx
    from esm.sdk import esmfold2_client
    from modules.folding.adapters import create_remote
    attempts = []
    def transport(request):
        attempts.append(json.loads(request.content)['sequence'])
        return httpx.Response(503, json={'message': 'service temporarily unavailable'})
    def client_factory(**kwargs):
        client = esmfold2_client(**kwargs)
        assert client.max_retry_attempts == 5
        # Collapse only the SDK's wait time for this isolated HTTP contract check.
        client.min_retry_wait = client.max_retry_wait = 0
        client._client = httpx.Client(transport=httpx.MockTransport(transport))
        return client
    monkeypatch.setattr('modules.folding.adapters.create_remote', lambda settings: create_remote(settings, client_factory=client_factory))
    app = Workbench(tmp_path)
    app.install('modules.folding:module')
    app.configure('workbench.prediction', {'token': 'contract-only-credential', 'service_url': 'https://fixture.invalid'})
    project = app.create_project('SDK default attempts')
    work = app.new_workdir()
    (work / 'input').write_text(json.dumps({'objects': [{'id': 'first', 'sequence': 'ACD'}, {'id': 'unstarted', 'sequence': 'DEF'}]}))
    package = app.create_input(project['id'], Delivery('workbench.sequence', 'input', {'input': 'input'}), work)
    app.save_project(project['id'], {'nodes': [{'id': 'predict', 'type': 'workbench.predict', 'inputs': {'sequence': [package['id']]}, 'tools': {'predictor': 'workbench.esmfold2.remote'}}], 'edges': []}, {})
    result = wait_run(app, app.start(project['id']))
    assert result['status'] == 'failed', result
    assert attempts == ['ACD'] * 5
    assert result['nodes']['predict']['continuation'] == {'completed': 0}
    assert result['nodes']['predict']['outputs']['structure'] == []
