"""Existing geometry evaluation through the installed public application."""
import json
from pathlib import Path
from fastapi.testclient import TestClient
from protein_workbench_public.bootstrap import create_application
from tests.test_sequence_io import upload
from tests.run_helpers import wait_response

PDB = b'''ATOM      1  N   ALA Z  12A      1.000   2.000   3.000  1.00 11.00           N
ATOM      2  CA  ALA Z  12A      2.000   3.000   4.000  1.00 12.00           C
ATOM      3  C   ALA Z  12A      3.000   4.000   5.000  1.00 13.00           C
ATOM      4  O   ALA Z  12A      4.000   5.000   6.000  1.00 14.00           O
ATOM      5  CB  ALA Z  12A      5.000   6.000   7.000  1.00 15.00           C
END
'''


def settings(tmp_path):
    for name in ('simplefold_1.6B.ckpt', 'plddt.ckpt', 'esm2.pt', 'esm2-contact-regression.pt', 'ccd.pkl'):
        (tmp_path / name).touch()
    return {'model_path': str(tmp_path), 'esm2_checkpoint': str(tmp_path / 'esm2.pt'), 'esm2_source': str(tmp_path), 'ccd_path': str(tmp_path / 'ccd.pkl')}


def test_original_geometry_evaluation_survives_save_and_independent_adoption(tmp_path, monkeypatch):
    from modules.simplefold import confidence
    calls = []
    def worker(command, **kwargs):
        payload = json.loads(Path(command[-1]).read_text())
        calls.append(payload)
        assert Path(payload['structure_path']).read_bytes() == PDB
        assert payload['positions'] == [{'chain': 'Z', 'author_number': 12, 'insertion_code': 'A'}]
        (Path(payload['workdir']) / 'simplefold-confidence.json').write_text(json.dumps({'positions': payload['positions'], 'plddt': [.75], 'context': {'backend': 'torch', 'device': 'cpu', 'latent_dtype': 'torch.float32'}}))
    monkeypatch.setattr(confidence, 'run_worker', worker)
    obj = {'id': 'existing-object', 'label': 'Original structure', 'structure': {'file': 'original.pdb', 'format': 'pdb'},
           'confidence': {'plddt': {'file': 'natural.json', 'meaning': 'source generation confidence'}}}
    root = tmp_path / 'store'
    with TestClient(create_application(data_root=root)) as client:
        client.put('/api/modules/workbench.simplefold/settings', json={'settings': settings(tmp_path)}).raise_for_status()
        project = client.post('/api/projects', json={'name': 'Original'}).json()['id']
        package = upload(client, project, 'workbench.prediction', {'manifest.json': json.dumps({'objects': [obj]}).encode(), 'original.pdb': PDB, 'natural.json': b'{"plddt":[0.1]}'})
        flow = {'nodes': [{'id': 'e', 'type': 'workbench.evaluate_structure_confidence', 'inputs': {'structures': [package['id']]}, 'parameters': {'object': obj['id'], 'region': [{'chain': 'Z', 'author_number': 12, 'insertion_code': 'A'}]}, 'tools': {'evaluator': 'workbench.simplefold.confidence'}}], 'edges': []}
        client.put(f'/api/projects/{project}', json={'flow': flow, 'layout': {}}).raise_for_status()
        result = wait_response(client, client.post(f'/api/projects/{project}/runs')).json()
        assert result['status'] == 'succeeded', result
        output = result['nodes']['e']['outputs']['evaluation'][0]
    with TestClient(create_application(data_root=root)) as client:
        document = client.get(f'/api/packages/{output}/file', params={'key': 'manifest.json'}).json()
        assert document['objects'] == [obj]
        assert client.get(f'/api/packages/{output}/file', params={'key': 'original.pdb'}).content == PDB
        assert client.get(f'/api/packages/{output}/file', params={'key': 'natural.json'}).content == b'{"plddt":[0.1]}'
        evaluation, = document['evaluations']
        assert evaluation['object_id'] == obj['id'] and evaluation['reference'] is None
        assert evaluation['region'] == [{'chain': 'Z', 'author_number': 12, 'insertion_code': 'A'}]
        assert evaluation['values']['mean_plddt']['value'] == .75
        assert evaluation['context']['coordinate_scale'] == 16
        assert evaluation['context']['time'] == 1
        assert evaluation['context']['device'] == 'cpu'
        assert evaluation['values']['mean_plddt']['unit'] == 'fraction (0–1)'
        assert 'given structure' in evaluation['method']
        assert client.get(f'/api/packages/{output}/file', params={'key': evaluation['per_position']['file']}).json()['plddt'] == [.75]
        assert len(calls) == 1
        target = client.post('/api/projects', json={'name': 'Independent target'}).json()['id']
        adopted = client.post(f'/api/projects/{target}/adoptions', json={'package_id': output}).json()
        client.delete(f'/api/projects/{project}').raise_for_status()
        client.delete('/api/modules/workbench.structure_confidence').raise_for_status()
        client.delete('/api/modules/workbench.simplefold').raise_for_status()
    from core.host import Workbench
    from modules.structure_confidence.formats import read_evaluations
    saved = read_evaluations(Workbench(root).package(adopted['id']))
    assert saved['objects'] == [obj]
    assert saved['evaluations'][0]['values']['mean_plddt']['value'] == .75


def test_simplefold_projects_every_original_atom_without_sampling(tmp_path, monkeypatch):
    import sys
    import pytest
    from modules.simplefold.confidence_worker import prepare_geometry, evaluate_geometry
    # Use fixed upstream parser/featurizer, isolating only heavy model feature/head calls.
    simplefold = pytest.importorskip('simplefold')
    monkeypatch.syspath_prepend(str(Path(simplefold.__file__).resolve().parent))
    (tmp_path / 'input.pdb').write_bytes(PDB)
    payload = {'structure_path': str(tmp_path / 'input.pdb'), 'structure_format': 'pdb', 'positions': [{'chain': 'Z', 'author_number': 12, 'insertion_code': 'A'}], 'workdir': str(tmp_path),
               'settings': {'ccd_path': str(tmp_path / 'ccd.pkl')}}
    import pickle
    from rdkit import Chem
    mol = Chem.MolFromSmiles('N[C@@H](C)C(=O)O')
    for atom, name in zip(mol.GetAtoms(), ('N', 'CA', 'CB', 'C', 'O', 'OXT'), strict=True):
        atom.SetProp('name', name)
    conformer = Chem.Conformer(mol.GetNumAtoms())
    conformer.SetProp('name', 'Ideal')
    for i in range(mol.GetNumAtoms()):
        conformer.SetAtomPosition(i, (i, i % 2, 0))
    mol.AddConformer(conformer)
    Chem.SetDefaultPickleProperties(Chem.PropertyPickleOptions.AllProps)
    (tmp_path / 'ccd.pkl').write_bytes(pickle.dumps({'ALA': mol}))
    batch, positions = prepare_geometry(payload)
    assert positions == payload['positions']
    import torch
    assert batch['coords'].shape == (1, 1, 32, 3)
    # Source coordinates are known literals; tokenizer order is N,CA,C,O,CB.
    assert batch['coords'][0, 0, :5].tolist() == [[-2, -2, -2], [-1, -1, -1], [0, 0, 0], [1, 1, 1], [2, 2, 2]]
    assert batch['coords'][0, 0, 5:].count_nonzero() == 0
    seen = []
    def latent(coords, t, feats):
        seen.append((coords.tolist(), t.tolist()))
        return {'latent': torch.ones(1, 1, 2), 'predict_velocity': None}
    def head(latent, feats):
        return {'plddt': torch.tensor([[.75]])}
    result = evaluate_geometry({'coords': batch['coords'][:, :, :5].squeeze(1) / 16}, latent, head)
    assert result == [.75]
    assert seen == [([[[-.125, -.125, -.125], [-.0625, -.0625, -.0625], [0, 0, 0], [.0625, .0625, .0625], [.125, .125, .125]]], [1.0])]
    (tmp_path / 'input.pdb').write_bytes(b'\n'.join(line for line in PDB.splitlines() if not line.startswith(b'ATOM      5')) + b'\n')
    with pytest.raises(ValueError, match='component|protein|atom'):
        prepare_geometry(payload)
    import gemmi
    original = gemmi.read_pdb_string(PDB)
    second = original[0][0].clone()
    second.name = 'Y'
    second[0].seqid = gemmi.SeqId(28, 'B')
    original[0].add_chain(second)
    (tmp_path / 'input.cif').write_text(original.make_mmcif_document().as_string())
    payload.update(structure_path=str(tmp_path / 'input.cif'), structure_format='mmcif', positions=[{'chain': 'Z', 'author_number': 12, 'insertion_code': 'A'}, {'chain': 'Y', 'author_number': 28, 'insertion_code': 'B'}])
    batch, mapped = prepare_geometry(payload)
    assert mapped == payload['positions']
    assert batch['aa_seq'] == ['A:A']
    assert batch['atom_pad_mask'].sum().item() == 10


def test_independent_reader_rejects_inconsistent_mean_and_adopted_values(tmp_path):
    import io
    import pytest
    from modules.structure_confidence.formats import read_evaluations
    position = {'chain': 'Z', 'author_number': 12, 'insertion_code': 'A'}
    manifest = {'objects': [{'id': 'original', 'structure': {'file': 'original.pdb', 'format': 'pdb'}}], 'evaluations': [{'object_id': 'original', 'reference': None, 'region': [position], 'origin': 'independent_existing_geometry', 'method': 'Actual method', 'per_position': {'file': 'scores.json', 'unit': 'fraction (0–1)'}, 'values': {'mean_plddt': {'value': 3, 'unit': 'fraction (0–1)', 'meaning': 'Mean'}}}]}
    class Package:
        entry = 'manifest.json'
        files = ('manifest.json', 'original.pdb', 'scores.json')
        def open(self, key):
            return io.BytesIO({'manifest.json': json.dumps(manifest).encode(), 'original.pdb': PDB, 'scores.json': json.dumps({'positions': [position], 'plddt': [.75]}).encode()}[key])
    with pytest.raises(ValueError, match='mean'):
        read_evaluations(Package())


def test_prepare_exposes_actual_residue_selection_without_changing_source(tmp_path):
    from core.host import Workbench
    from protein_workbench_public.module_api import Delivery
    from tests.run_helpers import wait_run
    app = Workbench(tmp_path / 'app')
    app.install('modules.structure_confidence:module')
    project = app.create_project('Prepare confidence')
    work = app.new_workdir()
    obj = {'id': 'original', 'structure': {'file': 'original.pdb', 'format': 'pdb'}}
    (work / 'manifest.json').write_text(json.dumps({'objects': [obj]}))
    (work / 'original.pdb').write_bytes(PDB)
    pkg = app.create_input(project['id'], Delivery('workbench.prediction', 'manifest.json', {'manifest.json': 'manifest.json', 'original.pdb': 'original.pdb'}), work)
    app.save_project(project['id'], {'nodes': [{'id': 'p', 'type': 'workbench.prepare_structure_confidence', 'inputs': {'structures': [pkg['id']]}, 'parameters': {'object': 'original'}}], 'edges': []}, {})
    result = wait_run(app, app.start(project['id']))
    assert result['status'] == 'succeeded', result
    output = app.package(result['nodes']['p']['outputs']['prepared'][0])
    with output.open(output.entry) as reader:
        document = json.load(reader)
    assert document['objects'] == [obj]
    with output.open(document['confidence_positions']['original']) as reader:
        assert json.load(reader) == [{'chain': 'Z', 'author_number': 12, 'insertion_code': 'A'}]
    with output.open('original.pdb') as reader:
        assert reader.read() == PDB


def test_selected_simplefold_rejects_unsupported_complete_input_before_worker(tmp_path, monkeypatch):
    import pytest
    from types import SimpleNamespace
    from modules.simplefold import confidence
    from modules.structure_confidence.contract import ConfidenceRequest
    def unexpected(*args, **kwargs):
        raise AssertionError('Unsupported geometry must not invoke model worker')
    monkeypatch.setattr(confidence, 'run_worker', unexpected)
    original = tmp_path / 'input.pdb'
    original.write_bytes(PDB.replace(b'END\n', b'HETATM    6 ZN    ZN  X  99       9.000   8.000   7.000  1.00 10.00          ZN\nEND\n'))
    request = ConfidenceRequest(str(original), 'pdb', ({'chain': 'Z', 'author_number': 12, 'insertion_code': 'A'},))
    with pytest.raises(ValueError, match='component'):
        confidence.create({})(request, {}, SimpleNamespace(workdir=tmp_path, cancelled=False))
    assert original.read_bytes() == PDB.replace(b'END\n', b'HETATM    6 ZN    ZN  X  99       9.000   8.000   7.000  1.00 10.00          ZN\nEND\n')


def test_discontinuous_region_reads_complete_geometry_and_only_selects_reported_values(tmp_path, monkeypatch):
    from core.host import Workbench
    from protein_workbench_public.module_api import Delivery, Module, Tool
    from modules.structure_confidence.contract import ConfidenceResult, SLOT
    from modules.structure_confidence.formats import read_evaluations
    from tests.run_helpers import wait_run
    import modules.structure_confidence
    calls = []
    def factory(settings):
        def evaluate(request, parameters, runtime):
            calls.append(request)
            assert Path(request.structure_path).read_bytes() == complete
            return ConfidenceResult(request.positions, (.2, .8, .4), method='Known original-geometry evaluator')
        return evaluate
    def provider():
        return Module('test.geometry', 'Contract geometry evaluator', tools=(Tool('test.geometry.confidence', 'Contract evaluator', SLOT, factory),))
    # Use the normal public installation seam for an independent tool author.
    import sys, types
    implementation = types.ModuleType('confidence_contract_provider')
    implementation.module = provider
    monkeypatch.setitem(sys.modules, implementation.__name__, implementation)
    app = Workbench(tmp_path / 'app')
    app.install('modules.structure_confidence:module')
    app.install('confidence_contract_provider:module')
    project = app.create_project('Explicit region')
    work = app.new_workdir()
    complete = b''.join(PDB.replace(b'END\n', b'').replace(b'Z  12A', value) for value in (b'Z  12A', b'Z  18 ', b'Z  19 ')) + b'END\n'
    obj = {'id': 'existing', 'structure': {'file': 'original.pdb', 'format': 'pdb'}}
    (work / 'manifest.json').write_text(json.dumps({'objects': [obj]}))
    (work / 'original.pdb').write_bytes(complete)
    package = app.create_input(project['id'], Delivery('workbench.structure_set', 'manifest.json', {'manifest.json': 'manifest.json', 'original.pdb': 'original.pdb'}), work)
    region = [{'chain': 'Z', 'author_number': 12, 'insertion_code': 'A'}, {'chain': 'Z', 'author_number': 19, 'insertion_code': ''}]
    app.save_project(project['id'], {'nodes': [{'id': 'e', 'type': 'workbench.evaluate_structure_confidence', 'inputs': {'structures': [package['id']]}, 'parameters': {'object': 'existing', 'region': region}, 'tools': {'evaluator': 'test.geometry.confidence'}}], 'edges': []}, {})
    result = wait_run(app, app.start(project['id']))
    assert result['status'] == 'succeeded', result
    output = app.package(result['nodes']['e']['outputs']['evaluation'][0])
    manifest = read_evaluations(output)
    evaluation, = manifest['evaluations']
    assert evaluation['method'] == 'Known original-geometry evaluator'
    assert evaluation['region'] == region
    assert abs(evaluation['values']['mean_plddt']['value'] - .3) < 1e-12
    with output.open(evaluation['per_position']['file']) as reader:
        assert json.load(reader) == {'positions': region, 'plddt': [.2, .4]}
    assert len(calls[0].positions) == 3

    # Missing actual positions stop before another external call; the input stays intact.
    flow = app.get_project(project['id'])['flow']
    flow['nodes'][0]['parameters']['region'] = [{'chain': 'missing', 'author_number': 99, 'insertion_code': ''}]
    app.save_project(project['id'], flow, {})
    failure = wait_run(app, app.start(project['id']))
    assert failure['status'] == 'failed'
    assert len(calls) == 1
    with app.package(package['id']).open('original.pdb') as reader:
        assert reader.read() == complete
