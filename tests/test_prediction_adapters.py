from types import SimpleNamespace
import pytest
from modules.folding.adapters import create_remote
from modules.folding.contract import PredictionRequest


def test_remote_adapter_passes_sdk_parameters_and_preserves_native_confidence(tmp_path):
    calls = []
    class Protein:
        def to_pdb(self, output):
            output.write('ATOM structure from provider\n')
    class Client:
        def fold(self, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(plddt=[.8, .9, .7], ptm=.75, pae=[[0, 1, 2], [1, 0, 1], [2, 1, 0]], to_protein_chain=lambda: Protein())
        def close(self):
            calls.append('closed')
    def client_factory(**kwargs):
        calls.append(kwargs)
        return Client()
    runtime = SimpleNamespace(workdir=tmp_path, cancelled=False)
    predict = create_remote({'token': 'contract-credential', 'service_url': 'https://configured.invalid'}, client_factory=client_factory, config_factory=lambda **kwargs: kwargs)
    result = predict(PredictionRequest('ACD', 'source'), {'num_sampling_steps': 23, 'lm_mask_pct': .2, 'include_pae': True}, runtime)
    assert calls[0] == {'model': 'esmfold2-fast-2026-05', 'url': 'https://configured.invalid', 'token': 'contract-credential', 'request_timeout': 150}
    assert calls[1]['config']['num_sampling_steps'] == 23
    assert calls[1]['config']['include_pae'] is True
    assert calls[1]['config']['lm_mask_pct'] == .2
    assert 'seed' not in calls[1]['config']
    assert result.plddt == [.8, .9, .7]
    assert result.extras['pae'][0] == [0, 1, 2]
    assert calls[-1] == 'closed'


def test_local_adapter_passes_zero_seed_and_local_sampling_default(tmp_path):
    from modules.folding.local_worker import invoke
    calls = []
    class Builder:
        def fold(self, *args, **kwargs):
            calls.append((args, kwargs))
            return 'provider result'
    result = invoke('model', Builder(), lambda **kwargs: kwargs, lambda **kwargs: kwargs, 'ACD', {'seed': 0})
    assert result == 'provider result'
    assert calls[0][0] == ('model', {'sequences': [{'id': 'A', 'sequence': 'ACD'}]})
    assert calls[0][1]['seed'] == 0
    assert calls[0][1]['num_sampling_steps'] == 200
    assert calls[0][1]['num_diffusion_samples'] == 1


def test_remote_adapter_rejects_seed_before_network_access(tmp_path):
    predict = create_remote({'token': 'configured'})
    with pytest.raises(ValueError, match='seed'):
        predict(PredictionRequest('ACD', 'source'), {'seed': 0}, SimpleNamespace(workdir=tmp_path, cancelled=False))


def test_msa_is_converted_to_official_sdk_object_without_dropping_deletions(tmp_path):
    from modules.folding.adapters import sdk_msa
    observed = []
    class MSA:
        @classmethod
        def from_state_dict(cls, state):
            observed.append(state)
            return 'sdk-msa'
    result = sdk_msa({'sequences': ['ACD', 'A-D'], 'deletions': [[0, 0, 0], [0, 1, 0]]}, msa_type=MSA)
    assert result == 'sdk-msa'
    assert observed == [{'sequences': ['ACD', 'A-D'], 'deletions': [[0, 0, 0], [0, 1, 0]]}]


def test_missing_native_confidence_fails_instead_of_manufacturing_scores(tmp_path):
    predict = create_remote({'token': 'configured'}, client_factory=lambda **kwargs: SimpleNamespace(fold=lambda **kwargs: SimpleNamespace(plddt=None, ptm=.8), close=lambda: None), config_factory=lambda **kwargs: kwargs)
    with pytest.raises(ValueError, match='required pLDDT'):
        predict(PredictionRequest('ACD', 'source'), {}, SimpleNamespace(workdir=tmp_path, cancelled=False))


def test_remote_sdk_unsupported_distogram_is_rejected_before_request(tmp_path):
    predict = create_remote({'token': 'configured'})
    with pytest.raises(ValueError, match='include_distogram'):
        predict(PredictionRequest('ACD', 'source'), {'include_distogram': True}, SimpleNamespace(workdir=tmp_path, cancelled=False))


def test_local_adapter_keeps_relative_virtualenv_executable_absolute_across_worker_cwd(tmp_path, monkeypatch):
    import json
    from modules.folding.adapters import create_local
    executable = tmp_path / 'environment/bin/python'
    executable.parent.mkdir(parents=True)
    executable.write_text('existing executable')
    model = tmp_path / 'model'
    model.mkdir()
    work = tmp_path / 'work'
    work.mkdir()
    (work / 'esmfold2-result.json').write_text(json.dumps({'structure_path': 'output.pdb', 'plddt': [.8], 'ptm': .7}))
    captured = []
    class Process:
        returncode = 0
        def poll(self):
            return 0
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr('subprocess.Popen', lambda command, **kwargs: captured.append((command, kwargs)) or Process())
    result = create_local({'python': 'environment/bin/python', 'model_path': str(model), 'language_model_path': str(model)})(PredictionRequest('A', 'source'), {'seed': 0}, SimpleNamespace(workdir=work, cancelled=False))
    assert captured[0][0][4] == str(executable)
    assert captured[0][0][1:4] == ['-m', 'protein_workbench_public.model_validation', '--']
    assert result.plddt == [.8]


def test_local_worker_failure_reports_concrete_upstream_reason(tmp_path, monkeypatch):
    from modules.folding.adapters import create_local
    class FailedWorker:
        returncode = 1
        def __init__(self, args, **kwargs):
            stream = kwargs.get('stderr')
            if stream is not None:
                stream.write('RuntimeError: model weights are incomplete\n')
                stream.write('Model processes exited; resource released\n')
                stream.flush()
        def poll(self):
            return 1
    monkeypatch.setattr('subprocess.Popen', FailedWorker)
    with pytest.raises(ValueError, match='model weights are incomplete'):
        create_local({'model_path': str(tmp_path), 'language_model_path': str(tmp_path)})(
            PredictionRequest('A', 'source'), {}, SimpleNamespace(workdir=tmp_path, cancelled=False))
