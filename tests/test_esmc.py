import json
from types import SimpleNamespace

import numpy as np
import torch

from core.host import Workbench
from protein_workbench_public.module_api import Delivery
from tests.run_helpers import wait_run


def test_local_real_tokenizer_values_survive_public_run_and_reopen(tmp_path, monkeypatch):
    from modules.esmc.adapters import create_local
    from modules.esmc.formats import read_manifest, read_array
    class Model:
        from esm.models.esmc.config import EsmcConfig
        config = EsmcConfig(hidden_size=2, num_attention_heads=1, num_hidden_layers=1)
        def __call__(self, **kwargs):
            assert kwargs['input_ids'].tolist() == [[0, 5, 23, 2]]
            return SimpleNamespace(last_hidden_state=torch.tensor([[[100., 200.], [2., 4.], [6., 8.], [300., 400.]]]), logits=torch.arange(144.).reshape(1, 4, 36))
    monkeypatch.setattr('modules.esmc.adapters.load_local', lambda settings: Model())
    app = Workbench(tmp_path)
    app.install('modules.esmc:module')
    app.configure('workbench.esmc', {'model_path': str(tmp_path), 'device': 'cpu'})
    project = app.create_project('Representations')
    work = app.new_workdir()
    source = {'id': 'original', 'sequence': 'AC', 'positions': [{'sequence_index': 1, 'chain': 'B', 'author_number': 12, 'insertion_code': ''}, {'sequence_index': 2, 'chain': 'B', 'author_number': 12, 'insertion_code': 'A'}]}
    (work / 'in.json').write_text(json.dumps({'objects': [source]}))
    pkg = app.create_input(project['id'], Delivery('workbench.sequence', 'manifest.json', {'manifest.json': 'in.json'}), work)
    app.save_project(project['id'], {'nodes': [{'id': 'represent', 'type': 'workbench.represent', 'inputs': {'sequence': [pkg['id']]}, 'parameters': {'outputs': 'both', 'dtype': 'float16'}, 'tools': {'representation': 'workbench.esmc.local'}}], 'edges': []}, {})
    result = wait_run(app, app.start(project['id']))
    assert result['status'] == 'succeeded', result
    app = Workbench(tmp_path)
    output = app.package(result['nodes']['represent']['outputs']['representation'][0])
    manifest = read_manifest(output)
    obj = manifest['objects'][0]
    assert obj['model']['configuration']['hidden_size'] == 2
    assert obj['input'] == source
    assert obj['tokens'] == [{'index': 0, 'id': 0, 'name': '<cls>'}, {'index': 1, 'id': 5, 'name': 'A', 'sequence_index': 1}, {'index': 2, 'id': 23, 'name': 'C', 'sequence_index': 2}, {'index': 3, 'id': 2, 'name': '<eos>'}]
    assert obj['logits']['columns'][32] == {'index': 32, 'name': '<mask>'}
    assert obj['logits']['columns'][33] == {'index': 33}
    np.testing.assert_array_equal(read_array(output, obj['mean_embedding']), [4., 6.])
    np.testing.assert_array_equal(read_array(output, obj['logits']), np.arange(144.).reshape(4, 36))
    assert obj['mean_embedding']['semantics'] == 'mean of actual residue positions; excludes added special tokens and padding'
    assert obj['logits']['dtype'] == 'float16'
    target = app.create_project('Adopted values')
    adopted = app.adopt(target['id'], output.id)
    app.delete_project(project['id'])
    app.uninstall('workbench.esmc')
    from fastapi.testclient import TestClient
    from protein_workbench_public.http.app import create_http_app
    import io
    import zipfile
    with TestClient(create_http_app(app)) as client:
        response = client.get(f"/api/packages/{adopted['id']}/export.zip")
        assert response.status_code == 200
        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            index = json.loads(archive.read('package.json'))
            content = {item['key']: archive.read(item['member']) for item in index['files']}
        document = json.loads(content[index['entry']])
        assert document['parameters'] == {'outputs': 'both', 'dtype': 'float16'}
        descriptor = document['objects'][0]['mean_embedding']
        assert np.frombuffer(content[descriptor['pages'][0]['file']], dtype='<f2').tolist() == [4., 6.]
        assert document['objects'][0]['input']['positions'][1]['insertion_code'] == 'A'


def test_remote_sdk_actual_wire_axes_and_mean_are_preserved(tmp_path):
    import pickle
    import httpx
    from esm.sdk.forge import ESMCForgeInferenceClient
    from esm.utils.constants.api import MIMETYPE_ES_PICKLE
    from modules.esmc.adapters import create_remote, REMOTE_MEAN
    requests = []
    clients = []
    def transport(request):
        payload = json.loads(request.content)
        requests.append(payload)
        assert payload['model'] == 'esmc-6b-2024-12'
        if request.url.path.endswith('/encode'):
            data = {'outputs': {'sequence': [0, 5, 23, 2, 1]}, 'potential_sequence_of_concern': False}
        else:
            assert payload['inputs']['sequence'] == [0, 5, 23, 2, 1]
            assert payload['logits_config']['sequence'] is True
            assert payload['logits_config']['return_mean_embedding'] is True
            assert payload['logits_config']['return_embeddings'] is False
            data = {'logits': {'sequence': torch.arange(180.).reshape(1, 5, 36)}, 'mean_embedding': torch.tensor([[[9., -3., 2.]]]), 'embeddings': None, 'hidden_states': None, 'mean_hidden_state': None, 'sae_outputs': None}
        return httpx.Response(200, content=pickle.dumps(data), headers={'Content-Type': MIMETYPE_ES_PICKLE})
    def factory(settings, model):
        client = ESMCForgeInferenceClient(model=model, token='test-only', url='https://fixture.invalid')
        assert client.max_retry_attempts == 5
        client._client = httpx.Client(transport=httpx.MockTransport(transport))
        clients.append(client)
        return client
    result = create_remote({}, client_factory=factory)('AC', {'model': 'esmc-6b-2024-12'}, SimpleNamespace(embedding=True, logits=True))
    np.testing.assert_array_equal(result.mean, [9., -3., 2.])
    np.testing.assert_array_equal(result.logits, np.arange(180.).reshape(5, 36))
    assert result.tokens[-1] == {'index': 4, 'id': 1, 'name': '<pad>'}
    assert result.model == {'backend': 'biohub', 'id': 'esmc-6b-2024-12'}
    assert result.parameters == {'model': 'esmc-6b-2024-12'}
    assert result.mean_semantics == REMOTE_MEAN
    assert result.columns[35] == {'index': 35}
    assert len(requests) == 2
    assert clients[0]._client.is_closed


def test_saved_float16_overflow_is_rejected_without_success(tmp_path):
    import pytest
    from modules.esmc.formats import write_array
    with np.errstate(over='ignore'), pytest.raises(ValueError, match='saved dtype'):
        write_array(tmp_path, 'overflow', np.array([100000.]), 'float16', {})


def test_requested_embedding_rejects_integer_or_missing_values():
    import pytest
    from esm.sdk.api import ESMProteinTensor, LogitsOutput
    from modules.esmc.adapters import create_remote
    class Client:
        def __init__(self):
            self.closed = False
        def encode(self, protein):
            return ESMProteinTensor(sequence=torch.tensor([0, 5, 2]))
        def logits(self, encoded, config):
            assert config.return_mean_embedding is True
            assert config.sequence is False
            return SimpleNamespace(mean_embedding=[1, 2], logits=None)
        def close(self):
            self.closed = True
    client = Client()
    with pytest.raises(ValueError, match='floating point'):
        create_remote({}, client_factory=lambda *_: client)('A', {}, SimpleNamespace(embedding=True, logits=False))
    assert client.closed


def test_request_without_actual_logits_is_not_silently_successful():
    import pytest
    from modules.esmc.adapters import create_local
    class Model:
        def __call__(self, **_kwargs):
            return SimpleNamespace(last_hidden_state=torch.zeros(1, 3, 2), logits=None)
    from unittest.mock import patch
    with patch('modules.esmc.adapters.load_local', return_value=Model()), pytest.raises(ValueError, match='omitted'):
        create_local({})('A', {}, SimpleNamespace(embedding=False, logits=True))


def test_native_loader_honors_configured_device_before_allocating(tmp_path, monkeypatch):
    from esm.models.esmc.model import EsmcForMaskedLM
    from modules.esmc.adapters import load_local
    calls = []
    class Model:
        def eval(self):
            calls.append('eval')
            return self
        def to(self, _device):
            raise AssertionError('The native loader must allocate on the requested device')
    def load(path, **kwargs):
        assert path == str(tmp_path)
        assert kwargs == {'device': 'cpu', 'local_files_only': True}
        calls.append('load')
        return Model()
    monkeypatch.setattr(EsmcForMaskedLM, 'from_pretrained', load)
    assert isinstance(load_local({'model_path': str(tmp_path), 'device': 'cpu'}), Model)
    assert calls == ['load', 'eval']
