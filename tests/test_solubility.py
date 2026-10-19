"""Independent sequence evaluation through HTTP and the public Adapter contract."""
import json
from fastapi.testclient import TestClient
from protein_workbench_public.bootstrap import create_application
from tests.test_sequence_io import upload
from tests.run_helpers import wait_response


def test_existing_sequence_evaluation_is_saved_and_reread_without_generation(tmp_path, monkeypatch):
    from modules.solubility import adapters
    calls = []
    def run(command, **kwargs):
        directory = kwargs['cwd']
        calls.append((command, (directory / 'input.fasta').read_text()))
        (directory / 'seq_prediction.txt').write_text('SEQUENCE PREDICTIONS,>item0,113.241,1.000,0.446,7.125\n')
    monkeypatch.setattr(adapters, 'run_worker', run)
    source = {'id': 'original / scientific id', 'sequence': 'ACDEFGHIKLMNPQRSTVWYA',
              'label': 'Research fragment', 'source': {'name': 'original.fa'},
              'positions': [{'sequence_index': index + 1, 'chain': 'Z', 'author_number': index + 12, 'insertion_code': 'A' if index == 0 else ''} for index in range(21)]}
    settings = provider_settings(tmp_path)
    with TestClient(create_application(data_root=tmp_path / 'store')) as client:
        response = client.put('/api/modules/workbench.solubility/settings', json={'settings': settings})
        assert response.status_code == 200, response.text
        project = client.post('/api/projects', json={'name': 'Existing sequence'}).json()['id']
        package = upload(client, project, 'workbench.sequence', {'manifest.json': json.dumps({'objects': [source]}).encode()})
        flow = {'nodes': [{'id': 'evaluate', 'type': 'workbench.evaluate_solubility', 'inputs': {'sequence': [package['id']]}, 'tools': {'evaluator': 'workbench.protein_sol'}, 'tool_parameters': {'evaluator': {'membrane_exclude': False}}}], 'edges': []}
        assert client.put(f'/api/projects/{project}', json={'flow': flow, 'layout': {}}).status_code == 200
        result = wait_response(client, client.post(f'/api/projects/{project}/runs')).json()
        assert result['status'] == 'succeeded', result
        output = result['nodes']['evaluate']['outputs']['evaluation'][0]
    with TestClient(create_application(data_root=tmp_path / 'store')) as client:
        document = client.get(f'/api/packages/{output}/file', params={'key': 'manifest.json'}).json()
        assert document['objects'] == [source]
        evaluation = document['evaluations'][0]
        assert evaluation['object_id'] == source['id']
        assert evaluation['reference'] is None and evaluation['region'] is None
        assert evaluation['method'] == 'Protein-Sol October 2017 sequence prediction'
        assert evaluation['values']['percent_solubility']['value'] == 113.241
        assert evaluation['values']['percent_solubility']['unit'] == 'percent'
        assert evaluation['values']['scaled_solubility']['value'] == 1
        assert evaluation['values']['isoelectric_point']['value'] == 7.125
        assert len(calls) == 1
        assert calls[0][1] == '>item0\nACDEFGHIKLMNPQRSTVWYA\n'
        assert 'original / scientific id' not in ' '.join(calls[0][0])
        assert client.get(f'/api/packages/{output}/file', params={'key': 'tool-output.txt'}).content.startswith(b'SEQUENCE PREDICTIONS,>item0')


def provider_settings(tmp_path):
    root = tmp_path / 'source'
    root.mkdir()
    for name in ('fasta_seq_reformat_export.pl', 'multiple_prediction_wrapper_export.sh', 'profiles_gather_export.pl', 'seq_compositions_perc_pipeline_export.pl', 'seq_props_ALL_export.pl', 'seq_reference_data.txt', 'server_prediction_seq_export.pl', 'ss_propensities.txt'):
        (root / name).write_text('official boundary fixture')
    return {'protein_sol_source': str(root), 'bash': '/bin/bash', 'perl': '/usr/bin/perl'}


def test_public_evaluation_reader_rejects_missing_tool_description_and_output(tmp_path):
    import pytest
    from modules.solubility.formats import read_evaluations
    source = {'id': 's', 'sequence': 'ACDEFGHIKLMNPQRSTVWYA'}
    manifest = {'objects': [source], 'evaluations': [{'object_id': 's', 'reference': None, 'region': None, 'method': 'actual', 'values': {'x': {'value': .4, 'unit': 'fraction', 'meaning': 'actual scale'}}}]}
    class Package:
        entry = 'manifest.json'
        files = ('manifest.json',)
        def open(self, key):
            return __import__('io').BytesIO(json.dumps(manifest).encode())
    with pytest.raises(ValueError, match='tool'):
        read_evaluations(Package())


def test_soluprot_cli_preserves_sequences_threads_mode_and_model_class_mapping(tmp_path):
    import sys
    from types import SimpleNamespace
    from modules.solubility.adapters import create_soluprot
    from modules.solubility.contract import SolubilityRequest
    root = tmp_path / 'port'
    (root / 'soluprot_core').mkdir(parents=True)
    (root / 'soluprot_core/__init__.py').write_text('')
    # A process-boundary provider records the actual CLI, without loading models.
    (root / 'soluprot_core/cli.py').write_text('''import argparse,json,pathlib

def main():
    p=argparse.ArgumentParser()
    for name in ('i_fa','o_csv','tmp_dir','model','usearch','pdb','no_proc'): p.add_argument('--'+name)
    p.add_argument('--no_tmhmm',action='store_true')
    p.add_argument('--check_unknown',action='store_true')
    a=p.parse_args()
    pathlib.Path(a.o_csv).with_suffix('.request.json').write_text(json.dumps(vars(a)))
    pathlib.Path(a.o_csv).write_text('runtime_id,fa_id,soluble\\n0,item1,0.125\\n1,item0,0.875\\n')
    return 0
''')
    model = root / 'model.json'
    model.write_text(json.dumps({'classes': ['soluble', 'insoluble'], 'soluble_class': 'soluble', 'arrays': 'trees.npz'}))
    (root / 'trees.npz').write_bytes(b'not loaded at this seam')
    database = root / 'db.fa'
    database.write_text('>ref\nACD\n')
    work = tmp_path / 'work'
    work.mkdir()
    settings = {'soluprot_source': str(root), 'soluprot_python': sys.executable, 'usearch': '/usr/bin/true', 'soluprot_no_tm_model': str(model), 'soluprot_database': str(database)}
    result = create_soluprot(settings, mode='no_tm')(SolubilityRequest(('ACDEFGHIKLMNPQRSTVWYA', 'YYYYYYYYYYYYYYYYYYYY')), {'threads': 3}, SimpleNamespace(workdir=work, cancelled=False))
    request = json.loads((work / 'solubility-tool/output.request.json').read_text())
    assert request['no_proc'] == '3' and request['check_unknown'] is True
    assert request['no_tmhmm'] is True and request['model'] == str(model)
    assert request['pdb'] == str(database)
    assert (work / 'solubility-tool/input.fasta').read_text() == '>item0\nACDEFGHIKLMNPQRSTVWYA\n>item1\nYYYYYYYYYYYYYYYYYYYY\n'
    assert result.values[0]['soluble_probability']['value'] == .875
    assert result.values[1]['soluble_probability']['value'] == .125
    assert result.context['soluble_class'] == 'soluble'
    assert result.context['classes'] == ['soluble', 'insoluble']


def test_tool_rejection_does_not_call_process_or_change_input(tmp_path, monkeypatch):
    import pytest
    from types import SimpleNamespace
    from modules.solubility import adapters
    from modules.solubility.contract import SolubilityRequest
    def forbidden(*args, **kwargs):
        raise AssertionError('No process may start for unsupported input')
    monkeypatch.setattr(adapters, 'run_worker', forbidden)
    settings = provider_settings(tmp_path)
    runtime = SimpleNamespace(workdir=tmp_path, cancelled=False)
    for sequence in ('ACD', 'ACDEFGHIKLMNPQRSTVWYAX'):
        with pytest.raises(ValueError, match='at least 21'):
            adapters.create_protein_sol(settings)(SolubilityRequest((sequence,)), {}, runtime)
    with pytest.raises(ValueError, match='membrane_exclude'):
        adapters.create_protein_sol(settings)(SolubilityRequest(('A' * 21,)), {'seed': 0}, runtime)
    assert not (tmp_path / 'solubility-tool').exists()


def test_missing_or_duplicate_tool_rows_fail_before_delivery(tmp_path, monkeypatch):
    import pytest
    from types import SimpleNamespace
    from modules.solubility import adapters
    from modules.solubility.contract import SolubilityRequest
    settings = provider_settings(tmp_path)
    def run(command, **kwargs):
        (kwargs['cwd'] / 'seq_prediction.txt').write_text('SEQUENCE PREDICTIONS,>item0,10,.1,.446,6\n')
    monkeypatch.setattr(adapters, 'run_worker', run)
    with pytest.raises(ValueError, match='every supplied sequence'):
        adapters.create_protein_sol(settings)(SolubilityRequest(('A' * 21, 'C' * 21)), {}, SimpleNamespace(workdir=tmp_path, cancelled=False))


def test_evaluation_references_files_and_objects_after_cross_project_adoption(tmp_path, monkeypatch):
    import io
    from modules.solubility import adapters
    from modules.solubility.formats import read_evaluations
    def run(command, **kwargs):
        assert command[-2:] == ['YES', 'no']
        (kwargs['cwd'] / 'seq_prediction.txt').write_text('SEQUENCE PREDICTIONS,>item0,52.5,.438,.446,5.7\n')
    monkeypatch.setattr(adapters, 'run_worker', run)
    settings = provider_settings(tmp_path)
    with TestClient(create_application(data_root=tmp_path / 'store')) as client:
        client.put('/api/modules/workbench.solubility/settings', json={'settings': settings}).raise_for_status()
        project = client.post('/api/projects', json={'name': 'Source'}).json()['id']
        sequence = {'id': 'research-id', 'sequence': 'ACDEFGHIKLMNPQRSTVWYA'}
        package = upload(client, project, 'workbench.sequence', {'manifest.json': json.dumps({'objects': [sequence]}).encode()})
        flow = {'nodes': [{'id': 'e', 'type': 'workbench.evaluate_solubility', 'inputs': {'sequence': [package['id']]}, 'tools': {'evaluator': 'workbench.protein_sol'}, 'tool_parameters': {'evaluator': {'membrane_exclude': True}}}], 'edges': []}
        client.put(f'/api/projects/{project}', json={'flow': flow, 'layout': {}}).raise_for_status()
        run = wait_response(client, client.post(f'/api/projects/{project}/runs')).json()
        output = run['nodes']['e']['outputs']['evaluation'][0]
        target = client.post('/api/projects', json={'name': 'Independent analysis'}).json()['id']
        adopted = client.post(f'/api/projects/{target}/adoptions', json={'package_id': output})
        assert adopted.status_code == 200, adopted.text
        output = adopted.json()['id']
        client.delete(f'/api/projects/{project}').raise_for_status()
        client.put('/api/modules/workbench.solubility/enabled', json={'enabled': False}).raise_for_status()
        metadata = client.get(f'/api/packages/{output}').json()
        class Package:
            entry = metadata['entry']
            files = metadata['files']
            def open(self, key):
                response = client.get(f'/api/packages/{output}/file', params={'key': key})
                response.raise_for_status()
                return io.BytesIO(response.content)
        # An independently authored filter can read the documented bytes directly.
        with Package().open(Package.entry) as stream:
            independent = json.load(stream)
        selected = [row['object_id'] for row in independent['evaluations'] if row['values']['scaled_solubility']['value'] > .4]
        assert selected == ['research-id']
        document = read_evaluations(Package())
        assert document['objects'] == [sequence]
        assert document['evaluations'][0]['values']['scaled_solubility']['value'] == .438
        assert document['tool']['parameters'] == {'membrane_exclude': True, 'histidine_charged': False}


def test_full_soluprot_passes_tmhmm_without_switching_models(tmp_path, monkeypatch):
    import sys
    from types import SimpleNamespace
    from modules.solubility import adapters
    from modules.solubility.contract import SolubilityRequest
    root = tmp_path / 'port'
    (root / 'soluprot_core').mkdir(parents=True)
    (root / 'soluprot_core/cli.py').write_text('fixed source boundary')
    (root / 'trees.npz').write_bytes(b'arrays')
    (root / 'model.json').write_text(json.dumps({'classes': [1, 0], 'soluble_class': 1, 'arrays': 'trees.npz'}))
    (root / 'db.fa').write_text('>r\nACD\n')
    def run(command, **kwargs):
        assert '--no_tmhmm' not in command
        assert command[command.index('--tmhmm') + 1] == '/usr/bin/true'
        assert command[command.index('--model') + 1] == str(root / 'model.json')
        assert command[command.index('--no_proc') + 1] == '1'
        assert (kwargs['cwd'] / 'perl').is_symlink()
        (kwargs['cwd'] / 'output.csv').write_text('runtime_id,fa_id,soluble\n0,item0,.625\n')
    monkeypatch.setattr(adapters, 'run_worker', run)
    settings = {'soluprot_source': str(root), 'soluprot_python': sys.executable, 'usearch': '/usr/bin/true', 'tmhmm': '/usr/bin/true', 'perl': '/usr/bin/perl', 'soluprot_full_model': str(root / 'model.json'), 'soluprot_database': str(root / 'db.fa')}
    result = adapters.create_soluprot(settings, mode='full')(SolubilityRequest(('A' * 20,)), {}, SimpleNamespace(workdir=tmp_path, cancelled=False))
    assert result.method == 'SoluProt maintained port · full'
    assert result.values[0]['soluble_probability']['value'] == .625
    assert result.context['classes'] == [1, 0] and result.context['soluble_class'] == 1


def test_same_saved_input_starts_new_evaluations_and_incomplete_positions_fail(tmp_path, monkeypatch):
    from modules.solubility import adapters
    calls = []
    def run(command, **kwargs):
        calls.append(command)
        (kwargs['cwd'] / 'seq_prediction.txt').write_text('SEQUENCE PREDICTIONS,>item0,52.5,.438,.446,5.7\n')
    monkeypatch.setattr(adapters, 'run_worker', run)
    settings = provider_settings(tmp_path)
    with TestClient(create_application(data_root=tmp_path / 'store')) as client:
        client.put('/api/modules/workbench.solubility/settings', json={'settings': settings}).raise_for_status()
        project = client.post('/api/projects', json={'name': 'Repeat explicitly'}).json()['id']
        sequence = {'id': 'one', 'sequence': 'A' * 21}
        package = upload(client, project, 'workbench.sequence', {'manifest.json': json.dumps({'objects': [sequence]}).encode()})
        node = {'id': 'e', 'type': 'workbench.evaluate_solubility', 'inputs': {'sequence': [package['id']]}, 'tools': {'evaluator': 'workbench.protein_sol'}}
        client.put(f'/api/projects/{project}', json={'flow': {'nodes': [node], 'edges': []}, 'layout': {}}).raise_for_status()
        runs = [wait_response(client, client.post(f'/api/projects/{project}/runs')).json() for _ in range(2)]
        assert all(run['status'] == 'succeeded' for run in runs)
        assert runs[0]['nodes']['e']['outputs'] != runs[1]['nodes']['e']['outputs']
        assert len(calls) == 2
        sequence['positions'] = [{'sequence_index': 1}]
        content = json.dumps({'objects': [sequence]}).encode()
        invalid = upload(client, project, 'workbench.sequence', {'manifest.json': content})
        node['inputs']['sequence'] = [invalid['id']]
        client.put(f'/api/projects/{project}', json={'flow': {'nodes': [node], 'edges': []}, 'layout': {}}).raise_for_status()
        failed = wait_response(client, client.post(f'/api/projects/{project}/runs')).json()
        assert failed['status'] == 'failed'
        assert 'positions must cover every sequence residue' in str(failed['nodes']['e']['diagnostics'])
        assert len(calls) == 2
        assert client.get(f"/api/packages/{invalid['id']}/file", params={'key': 'manifest.json'}).content == content


def test_protein_sol_passes_histidine_charge_option_using_actual_script_control(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from modules.solubility import adapters
    from modules.solubility.contract import SolubilityRequest
    settings = provider_settings(tmp_path)
    def run(command, **kwargs):
        assert command[-2:] == ['NO', 'yes']
        assert 'export his_charged=$5' in command[2]
        assert 'unset motifneutral extra_output' in command[2]
        (kwargs['cwd'] / 'seq_prediction.txt').write_text('SEQUENCE PREDICTIONS,>item0,52.5,.438,.446,5.7\n')
    monkeypatch.setattr(adapters, 'run_worker', run)
    result = adapters.create_protein_sol(settings)(SolubilityRequest(('ACDEFGHIKLMNPQRSTVWYA',)), {'histidine_charged': True}, SimpleNamespace(workdir=tmp_path, cancelled=False))
    assert result.parameters == {'membrane_exclude': False, 'histidine_charged': True}
