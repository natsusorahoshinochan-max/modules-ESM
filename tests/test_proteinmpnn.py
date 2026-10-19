"""ProteinMPNN public adapter and persisted application behavior."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest


def backbone(path):
    rows = []
    serial = 0
    for chain, number, insertion, residue, x in [('B', 42, '', 'ALA', 0), ('B', 42, 'A', 'CYS', 4), ('A', 9, '', 'ASP', 8)]:
        for atom, dx, element in [('N', 0, 'N'), ('CA', 1, 'C'), ('C', 2, 'C'), ('O', 3, 'O')]:
            serial += 1
            rows.append(f'ATOM  {serial:5d} {atom:^4s} {residue} {chain}{number:4d}{insertion:1s}   {x+dx:8.3f}{0:8.3f}{0:8.3f}{1:6.2f}{20:6.2f}          {element:>2s}')
    path.write_text('\n'.join(rows) + '\nEND\n')


def test_public_adapter_maps_real_numbering_and_passes_native_parameters(tmp_path, monkeypatch):
    from modules.proteinmpnn.adapters import create_local
    from modules.proteinmpnn.contract import MPNNRequest
    backbone(tmp_path / 'input.pdb')
    captured = []
    def worker(command, **kwargs):
        payload = json.loads(Path(command[-1]).read_text())
        captured.append(payload)
        Path(payload['output']).write_text(json.dumps({'samples': [{'chains': {'B': 'AC', 'A': 'D'}, 'score': 1.25, 'global_score': 2.5, 'residue_nll': {'B': [1., 2.], 'A': [4.]}, 'design_mask': {'B': [1., 0.], 'A': [0.]}, 'coordinate_mask': {'B': [1., 1.], 'A': [1.]}}] * 2, 'actual_seed': 17}))
    monkeypatch.setattr('modules.proteinmpnn.adapters.run_worker', worker)
    runtime = SimpleNamespace(workdir=tmp_path, cancelled=False)
    result = create_local({'source': str(tmp_path), 'weights': str(tmp_path)})(MPNNRequest('input.pdb', 'pdb'), {'seed': 17, 'designed_chains': ['B'], 'fixed_positions': {'B': [2]}, 'num_seq_per_target': 2, 'batch_size': 2}, runtime)
    assert result.positions == [
        {'chain': 'B', 'author_number': 42, 'insertion_code': '', 'tool_position': 1},
        {'chain': 'B', 'author_number': 42, 'insertion_code': 'A', 'tool_position': 2},
        {'chain': 'A', 'author_number': 9, 'insertion_code': '', 'tool_position': 1}]
    assert captured[0]['parameters']['fixed_positions'] == {'B': [2]}
    assert captured[0]['parameters']['omit_AAs'] == 'X'
    assert captured[0]['parameters']['num_seq_per_target'] == 2
    assert captured[0]['entry']['seq_chain_B'] == 'AC'
    assert result.samples[0]['score'] == 1.25


@pytest.mark.parametrize('parameters, match', [({'num_seq_per_target': 3, 'batch_size': 2}, 'divisible'), ({'seed': True}, 'seed'), ({'seed': -1}, 'seed'), ({'unknown': 1}, 'Unsupported'), ({'fixed_positions': {'B': [3]}}, 'position'), ({'designed_chains': ['missing']}, 'chain'), ({'sampling_temp': [0]}, 'sampling_temp')])
def test_adapter_rejects_invalid_native_controls_before_external_call(tmp_path, monkeypatch, parameters, match):
    from modules.proteinmpnn.adapters import create_local
    from modules.proteinmpnn.contract import MPNNRequest
    backbone(tmp_path / 'input.pdb')
    def unexpected(*args, **kwargs):
        pytest.fail('Invalid input reached the external tool')
    monkeypatch.setattr('modules.proteinmpnn.adapters.run_worker', unexpected)
    with pytest.raises(ValueError, match=match):
        create_local({})(MPNNRequest('input.pdb', 'pdb'), parameters, SimpleNamespace(workdir=tmp_path, cancelled=False))


def test_independent_score_requires_complete_chain_correspondence(tmp_path, monkeypatch):
    from modules.proteinmpnn.adapters import create_local
    from modules.proteinmpnn.contract import MPNNRequest
    backbone(tmp_path / 'input.pdb')
    monkeypatch.setattr('modules.proteinmpnn.adapters.run_worker', lambda *a, **k: pytest.fail('Incomplete sequence reached tool'))
    with pytest.raises(ValueError, match='complete'):
        create_local({})(MPNNRequest('input.pdb', 'pdb', {'A': 'D', 'B': 'A'}), {}, SimpleNamespace(workdir=tmp_path, cancelled=False))


def test_native_worker_preserves_masks_batches_all_rng_and_sample_decoding_order(tmp_path):
    """Real upstream tensor preparation, isolated model compute at its external boundary."""
    import os
    import sys
    source = Path(os.environ.get('PROTEINMPNN_TEST_SOURCE', Path(__file__).resolve().parents[1] / 'repositories/ProteinMPNN'))
    if not (source / 'protein_mpnn_utils.py').is_file():
        pytest.skip('Configure PROTEINMPNN_TEST_SOURCE for the pinned upstream tensor contract')
    stub = tmp_path / 'provider'
    stub.mkdir()
    (stub / 'protein_mpnn_utils.py').write_text('''import importlib.util, random
import numpy as np
import torch
spec = importlib.util.spec_from_file_location('upstream', SOURCE)
u = importlib.util.module_from_spec(spec)
spec.loader.exec_module(u)
tied_featurize = u.tied_featurize
_scores = u._scores
class ProteinMPNN:
    def __init__(self, **kw):
        assert kw['k_neighbors'] == 48
    def load_state_dict(self, state): pass
    def to(self, device): return self
    def eval(self): return self
    def sample(self, X, noise, S, chain_M, chain_encoding, residue_idx, **kw):
        assert noise.shape == (2, 3)
        assert kw['chain_M_pos'][0].tolist() == [1., 0., 1.]
        assert abs(random.random() - 0.5219839097124932) < 1e-12
        assert abs(np.random.random() - 0.2946650026871097) < 1e-12
        return {'S': S, 'decoding_order': torch.tensor([[2, 1, 0], [2, 1, 0]])}
    def __call__(self, X, S, mask, chain_M, residue_idx, chain_encoding, noise, **kw):
        assert chain_M[0].tolist() == [1., 0., 0.]
        assert kw['use_input_decoding_order'] is True
        assert kw['decoding_order'][0].tolist() == [2, 1, 0]
        return -torch.tensor([1., 2., 3.]).reshape(1, 3, 1).expand(2, 3, 21)
'''.replace('SOURCE', repr(str(source / 'protein_mpnn_utils.py'))))
    import torch
    weights = tmp_path / 'weights' / 'vanilla_model_weights'
    weights.mkdir(parents=True)
    torch.save({'num_edges': 48, 'model_state_dict': {}}, weights / 'v_48_020.pt')
    from modules.proteinmpnn.adapters import create_local
    from modules.proteinmpnn.contract import MPNNRequest
    backbone(tmp_path / 'input.pdb')
    result = create_local({'source': str(stub), 'weights': str(tmp_path / 'weights'), 'python': sys.executable})(
        MPNNRequest('input.pdb', 'pdb'), {'seed': 17, 'designed_chains': ['B'], 'fixed_positions': {'B': [2]}, 'num_seq_per_target': 2, 'batch_size': 2}, SimpleNamespace(workdir=tmp_path, cancelled=False))
    assert len(result.samples) == 2
    assert result.actual_seed == 17
    assert result.samples[0]['chains'] == {'B': 'AC', 'A': 'D'}
    assert result.samples[0]['score'] == 1.
    assert result.samples[0]['global_score'] == 2.
    assert result.samples[0]['residue_nll'] == {'B': [1., 2.], 'A': [3.]}


def design_app(tmp_path, monkeypatch):
    from core.host import Workbench
    from modules.proteinmpnn.contract import MPNNResult
    from modules.proteinmpnn.adapters import prepare_structure
    from protein_workbench_public.module_api import Delivery
    calls, failure = [], {'at': 1}
    def create(settings):
        def tool(request, parameters, runtime):
            index = len(calls)
            calls.append((request, dict(parameters)))
            if index == failure.get('at'):
                raise ValueError('exhausted native request')
            _, positions = prepare_structure(request, runtime.workdir)
            return MPNNResult(positions, [{'chains': {'B': 'AC', 'A': 'D'}, 'score': 1.5, 'global_score': 2.5, 'residue_nll': {'B': [1., 2.], 'A': [3.]}, 'design_mask': {'B': [1., 1.], 'A': [1.]}, 'coordinate_mask': {'B': [1., 1.], 'A': [1.]}}], request.random_seed, parameters)
        return tool
    monkeypatch.setattr('tests.fixtures.mpnn_tool.create', create)
    app = Workbench(tmp_path / 'data')
    app.install('modules.proteinmpnn:module')
    app.install('tests.fixtures.mpnn_tool:module')
    project = app.create_project('MPNN')
    workdir = app.new_workdir()
    backbone(workdir / 'structure.pdb')
    (workdir / 'input.json').write_text(json.dumps({'objects': [{'id': str(i), 'structure': {'file': 'structure.pdb', 'format': 'pdb'}} for i in range(3)]}))
    pkg = app.create_input(project['id'], Delivery('workbench.structure_set', 'manifest', {'manifest': 'input.json', 'structure.pdb': 'structure.pdb'}), workdir)
    flow = {'nodes': [{'id': 'design', 'type': 'workbench.design_backbone', 'inputs': {'structure': [pkg['id']]}, 'tools': {'mpnn': 'lab.mpnn'}, 'tool_parameters': {'mpnn': {'seed': 0}}}], 'edges': []}
    app.save_project(project['id'], flow, {})
    return app, project, flow, calls, failure


def test_application_batch_stops_retains_partial_and_continues_fixed_call(tmp_path, monkeypatch):
    from tests.run_helpers import wait_run
    app, project, flow, calls, failure = design_app(tmp_path, monkeypatch)
    first = wait_run(app, app.start(project['id']))
    assert first['status'] == 'failed'
    assert len(calls) == 2
    package = app.package(first['nodes']['design']['outputs']['design'][0])
    with package.open(package.entry) as stream:
        partial = json.load(stream)
    assert len(partial['objects']) == 1
    assert partial['objects'][0]['sequence'] == 'ACD'
    assert partial['objects'][0]['positions'][1]['insertion_code'] == 'A'
    assert partial['objects'][0]['design']['score'] == 1.5
    with package.open(partial['objects'][0]['backbone']['structure']['file']) as stream:
        assert stream.read().startswith(b'ATOM')
    flow['nodes'][0]['tool_parameters']['mpnn']['seed'] = 99
    app.save_project(project['id'], flow, {})
    failure.clear()
    resumed = wait_run(app, app.continue_run(first['id'], 'design'))
    assert resumed['status'] == 'succeeded', resumed
    assert len(calls) == 4
    assert calls[1][0].random_seed == calls[2][0].random_seed
    assert calls[2][1] == {'seed': 0}
    package = app.package(resumed['nodes']['design']['outputs']['design'][0])
    with package.open(package.entry) as stream:
        completed = json.load(stream)
    assert len(completed['objects']) == 3
    assert completed['objects'][0] == partial['objects'][0]
    archive = app.export_package(package.id)
    assert archive.is_file()
    archive.unlink()


def test_seed_zero_uses_fixed_request_seed_and_missing_samples_fail(tmp_path, monkeypatch):
    from modules.proteinmpnn.adapters import create_local
    from modules.proteinmpnn.contract import MPNNRequest
    backbone(tmp_path / 'input.pdb')
    payloads = []
    def worker(command, **kwargs):
        payload = json.loads(Path(command[-1]).read_text())
        payloads.append(payload)
        Path(payload['output']).write_text(json.dumps({'actual_seed': payload['actual_seed'], 'samples': []}))
    monkeypatch.setattr('modules.proteinmpnn.adapters.run_worker', worker)
    with pytest.raises(ValueError, match='sample count'):
        create_local({})(MPNNRequest('input.pdb', 'pdb', random_seed=0), {'seed': 0}, SimpleNamespace(workdir=tmp_path, cancelled=False))
    assert payloads[0]['actual_seed'] == 0
    assert payloads[0]['parameters']['seed'] == 0


def test_failed_delivery_does_not_commit_private_batch_progress(tmp_path, monkeypatch):
    import os
    from tests.run_helpers import wait_run
    app, project, _, calls, failure = design_app(tmp_path, monkeypatch)
    failure.clear()
    sync = os.fsync
    monkeypatch.setattr(os, 'fsync', lambda fd: (_ for _ in ()).throw(OSError('disk full')))
    failed = wait_run(app, app.start(project['id']))
    assert failed['status'] == 'failed'
    assert failed['nodes']['design']['outputs'] == {}
    assert failed['nodes']['design']['continuation'] is None
    monkeypatch.setattr(os, 'fsync', sync)
    completed = wait_run(app, app.continue_run(failed['id'], 'design'))
    assert completed['status'] == 'succeeded', completed
    assert len(calls) == 6


def test_complete_scoring_uses_supplied_sequence_and_both_native_masks(tmp_path):
    import os
    import sys
    import torch
    from modules.proteinmpnn.adapters import create_local
    from modules.proteinmpnn.contract import MPNNRequest
    source = Path(os.environ.get('PROTEINMPNN_TEST_SOURCE', Path(__file__).resolve().parents[1] / 'repositories/ProteinMPNN'))
    if not (source / 'protein_mpnn_utils.py').is_file():
        pytest.skip('Configure PROTEINMPNN_TEST_SOURCE for the pinned upstream tensor contract')
    stub = tmp_path / 'source'; stub.mkdir()
    (stub / 'protein_mpnn_utils.py').write_text('''import importlib.util, torch
spec = importlib.util.spec_from_file_location('native', SOURCE)
u = importlib.util.module_from_spec(spec); spec.loader.exec_module(u)
tied_featurize = u.tied_featurize
_scores = u._scores
class ProteinMPNN:
    def __init__(self, **kwargs): pass
    def load_state_dict(self, state): pass
    def to(self, device): pass
    def eval(self): pass
    def __call__(self, X, S, mask, chain_M, residue_idx, chain_encoding, noise, **kwargs):
        assert not kwargs
        assert torch.initial_seed() == 17
        assert S.tolist() == [[4, 5, 6]]
        assert chain_M.tolist() == [[1., 0., 0.]]
        assert mask.tolist() == [[1., 1., 1.]]
        return -torch.tensor([1., 2., 3.]).reshape(1,3,1).expand(1,3,21)
'''.replace('SOURCE', repr(str(source / 'protein_mpnn_utils.py'))))
    weights = tmp_path / 'weights' / 'vanilla_model_weights'; weights.mkdir(parents=True)
    torch.save({'num_edges': 48, 'model_state_dict': {}}, weights / 'v_48_020.pt')
    backbone(tmp_path / 'input.pdb')
    result = create_local({'source': str(stub), 'weights': str(weights.parent), 'python': sys.executable})(
        MPNNRequest('input.pdb', 'pdb', {'B': 'FG', 'A': 'H'}), {'seed': 17, 'designed_chains': ['B'], 'fixed_positions': {'B': [2]}}, SimpleNamespace(workdir=tmp_path, cancelled=False))
    assert result.samples[0]['chains'] == {'B': 'FG', 'A': 'H'}
    assert result.samples[0]['score'] == 1.
    assert result.samples[0]['global_score'] == 2.
    assert result.samples[0]['temperature'] is None
    assert 'sampling_probabilities' not in result.samples[0]


def test_adapter_reads_mmcif_actual_author_chain_and_refuses_truncated_insertion_code(tmp_path, monkeypatch):
    import gemmi
    from modules.proteinmpnn.adapters import create_local
    from modules.proteinmpnn.contract import MPNNRequest
    backbone(tmp_path / 'input.pdb')
    structure = gemmi.read_structure(str(tmp_path / 'input.pdb'))
    structure[0][0].name = 'Beta'
    doc = structure.make_mmcif_document()
    block = doc.sole_block()
    code = block.find_values('_atom_site.pdbx_PDB_ins_code')
    for i, value in enumerate(code):
        if value == 'A':
            code[i] = 'AB'
    (tmp_path / 'input.cif').write_text(doc.as_string())
    monkeypatch.setattr('modules.proteinmpnn.adapters.run_worker', lambda *a, **k: pytest.fail('Truncated correspondence reached tool'))
    with pytest.raises(ValueError, match='insertion code'):
        create_local({})(MPNNRequest('input.cif', 'mmcif'), {}, SimpleNamespace(workdir=tmp_path, cancelled=False))


def test_generated_sequence_output_drives_existing_prediction_consumer(tmp_path, monkeypatch):
    from modules.folding.contract import PredictionResult
    from tests.run_helpers import wait_run
    app, project, flow, calls, failure = design_app(tmp_path, monkeypatch)
    failure.clear()
    predicted = []
    def factory(settings):
        def predict(request, parameters, runtime):
            predicted.append(request.sequence)
            (runtime.workdir / 'predicted.pdb').write_text('ATOM')
            return PredictionResult('predicted.pdb')
        return predict
    monkeypatch.setattr('tests.fixtures.prediction_tool.create', factory)
    app.install('modules.folding:module')
    app.install('tests.fixtures.prediction_tool:module')
    flow['nodes'].append({'id': 'fold', 'type': 'workbench.predict', 'tools': {'predictor': 'lab.external'}})
    flow['edges'].append({'source': 'design', 'source_port': 'sequence', 'target': 'fold', 'target_port': 'sequence'})
    app.save_project(project['id'], flow, {})
    run = wait_run(app, app.start(project['id']))
    assert run['status'] == 'succeeded', run['nodes']
    assert predicted == ['ACD'] * 3


def test_design_package_remains_independent_after_adoption_and_producer_uninstall(tmp_path, monkeypatch):
    from core.host import Workbench
    from tests.run_helpers import wait_run
    app, project, _, calls, failure = design_app(tmp_path, monkeypatch)
    failure.clear()
    run = wait_run(app, app.start(project['id']))
    original = app.package(run['nodes']['design']['outputs']['design'][0])
    target = app.create_project('Independent reader')
    adopted = app.adopt(target['id'], original.id)
    app.delete_project(project['id'])
    app.uninstall('workbench.proteinmpnn')
    independent = Workbench(tmp_path / 'data').package(adopted['id'])
    with independent.open(independent.entry) as stream:
        document = json.load(stream)
    assert document['objects'][0]['design']['global_score'] == 2.5
    assert document['objects'][0]['positions'][1] == {'chain': 'B', 'author_number': 42, 'insertion_code': 'A', 'tool_position': 2}
    with independent.open(document['objects'][0]['backbone']['structure']['file']) as stream:
        assert b'ALA B  42' in stream.read()
    for key in independent.files:
        with independent.open(key) as stream:
            assert stream.read()
