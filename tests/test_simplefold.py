from types import SimpleNamespace

import pytest

from modules.folding.contract import PredictionRequest


def test_simplefold_independently_declares_prediction_slot_and_rejects_foreign_parameters(tmp_path):
    from modules.simplefold import module
    tool, = module().tools
    assert tool.slot == 'workbench.predict.structure'
    assert tool.parameters['defaults']['tau'] == .1
    assert tool.parameters['defaults']['plddt'] is False
    with pytest.raises(ValueError, match='num_loops'):
        tool.create({})(PredictionRequest('ACD', 'input'), {'num_loops': 1}, SimpleNamespace(workdir=tmp_path, cancelled=False))


@pytest.mark.parametrize('with_confidence', [False, True])
def test_selected_simplefold_configuration_persists_actual_optional_confidence(tmp_path, monkeypatch, with_confidence):
    import json
    import subprocess
    from pathlib import Path
    from core.host import Workbench
    from protein_workbench_public.module_api import Delivery
    resources = tmp_path / 'models'
    resources.mkdir()
    for name in ('simplefold_100M.ckpt', 'esm2.pt', 'esm2-contact-regression.pt', 'ccd.pkl', 'simplefold_1.6B.ckpt', 'plddt.ckpt'):
        (resources / name).touch()
    class Worker:
        returncode = 0
        def __init__(self, args, **kwargs):
            payload = json.loads(Path(args[-1]).read_text())
            assert payload['parameters']['seed'] == 0
            assert payload['parameters']['num_steps'] == 7
            work = Path(payload['workdir'])
            (work / 'simplefold.pdb').write_text('ATOM      1  CA  ALA A   1       0.000   0.000   0.000  1.00100.00           C\nEND\n')
            native = {'structure_path': 'simplefold.pdb', 'structure_format': 'pdb'}
            if payload['parameters']['plddt']:
                native['plddt'] = [.73]
            (work / 'simplefold-result.json').write_text(json.dumps(native))
        def poll(self):
            return 0
    monkeypatch.setattr(subprocess, 'Popen', Worker)
    app = Workbench(tmp_path / 'app')
    app.install('modules.folding:module')
    app.install('modules.simplefold:module')
    app.configure('workbench.simplefold', {'model_path': str(resources), 'esm2_source': str(resources), 'esm2_checkpoint': str(resources / 'esm2.pt'), 'ccd_path': str(resources / 'ccd.pkl')})
    project = app.create_project('SimpleFold selection')
    work = app.new_workdir()
    (work / 'sequence.json').write_text(json.dumps({'objects': [{'id': 'input', 'sequence': 'A'}]}))
    package = app.create_input(project['id'], Delivery('workbench.sequence', 'sequence.json', {'sequence.json': 'sequence.json'}), work)
    app.save_project(project['id'], {'nodes': [{'id': 'predict', 'type': 'workbench.predict', 'inputs': {'sequence': [package['id']]}, 'tools': {'predictor': 'workbench.simplefold.local'}, 'tool_parameters': {'predictor': {'seed': 0, 'num_steps': 7, 'output_format': 'pdb', 'plddt': with_confidence}}}], 'edges': []}, {})
    result = app.start(project['id'])
    assert result['status'] == 'succeeded', result
    output = app.package(result['nodes']['predict']['outputs']['structure'][0])
    with output.open(output.entry) as stream:
        manifest = json.load(stream)
    assert manifest['tool']['id'] == 'workbench.simplefold.local'
    if with_confidence:
        with output.open('confidence.json') as stream:
            assert json.load(stream) == {'plddt': [.73]}
        assert 'ptm' not in manifest['objects'][0]['confidence']
    else:
        assert 'confidence' not in manifest['objects'][0]
        assert 'confidence.json' not in output.files
    with output.open('structure.pdb') as stream:
        assert b'100.00' in stream.read()


@pytest.mark.parametrize('parameters', [{'num_steps': 0}, {'seed': -1}, {'tau': float('nan')}, {'plddt': 'false'}, {'output_format': 'xyz'}, {'backend': 'mlx'}])
def test_simplefold_rejects_invalid_configuration_before_loading_models(tmp_path, parameters):
    from modules.simplefold import module
    with pytest.raises(ValueError):
        module().tools[0].create({})(PredictionRequest('ACD', 'input'), parameters, SimpleNamespace(workdir=tmp_path, cancelled=False))


def test_simplefold_worker_failure_reports_upstream_reason(tmp_path, monkeypatch):
    from modules.simplefold import create
    for name in ('simplefold_100M.ckpt', 'esm2.pt', 'esm2-contact-regression.pt', 'ccd.pkl'):
        (tmp_path / name).touch()
    class FailedWorker:
        returncode = 1
        def __init__(self, args, **kwargs):
            stream = kwargs.get('stderr')
            if stream is not None:
                stream.write('Traceback:\nRuntimeError: checkpoint dimensions do not match\n')
                stream.flush()
        def poll(self):
            return 1
    monkeypatch.setattr('subprocess.Popen', FailedWorker)
    settings = {'model_path': str(tmp_path), 'esm2_source': str(tmp_path), 'esm2_checkpoint': str(tmp_path / 'esm2.pt'), 'ccd_path': str(tmp_path / 'ccd.pkl')}
    with pytest.raises(ValueError, match='checkpoint dimensions do not match'):
        create(settings)(PredictionRequest('ACD', 'input'), {}, SimpleNamespace(workdir=tmp_path, cancelled=False))
