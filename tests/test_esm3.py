"""Public ESM3 SDK translation and persisted generation behavior."""
import json
from types import SimpleNamespace

import pytest


def test_remote_adapter_preserves_condition_tracks_controls_and_natural_outputs(tmp_path):
    import torch
    from esm.sdk.api import ESMProtein
    from modules.esm3.adapters import create_remote
    from modules.esm3.contract import ESM3Request
    captured = []
    class Client:
        def generate(self, protein, config):
            captured.append((protein, config))
            return ESMProtein(sequence='AB', coordinates=torch.ones(2, 37, 3), plddt=torch.tensor([.7, .8]), ptm=torch.tensor(.6))
        def close(self):
            captured.append('closed')
    tool = create_remote({}, client_factory=lambda settings: Client())
    result = tool(ESM3Request('sequence', {'sequence': 'A_', 'coordinates': [{'CA': [1., 2., 3.]}, None], 'secondary_structure': 'H_', 'sasa': [1., None], 'function_annotations': [{'label': 'binding', 'start': 1, 'end': 2}]}), {'num_steps': 2, 'temperature': .3, 'only_compute_backbone_rmsd': True, 'invalid_ids': [4]}, SimpleNamespace(workdir=tmp_path, cancelled=False))
    protein, config = captured[0]
    assert protein.sequence == 'A_'
    assert protein.coordinates[0, 1].tolist() == [1., 2., 3.]
    assert torch.isnan(protein.coordinates[1]).all()
    assert protein.secondary_structure == 'H_'
    assert protein.function_annotations[0].start == 1
    assert config.temperature == .3 and config.num_steps == 2
    assert config.only_compute_backbone_rmsd is True and config.invalid_ids == [4]
    assert config.top_p == 1. and config.temperature_annealing is True
    assert result.tracks['sequence'] == 'AB'
    with (tmp_path / result.values_file).open() as stream:
        values = json.load(stream)
    assert values['metrics']['plddt'] == pytest.approx([.7, .8])
    assert values['metrics']['ptm'] == pytest.approx(.6)
    assert captured[-1] == 'closed'
    with pytest.raises(ValueError, match='seed'):
        tool(ESM3Request('sequence', {'sequence': 'A_'}), {'seed': 9}, SimpleNamespace(workdir=tmp_path, cancelled=False))


def generation_app(tmp_path, monkeypatch):
    from core.host import Workbench
    from protein_workbench_public.module_api import Delivery
    from modules.esm3.contract import ESM3Result
    calls, failure = [], {'at': 1}
    def create(settings):
        def generate(request, parameters, runtime):
            index = len(calls)
            calls.append((request, parameters.copy()))
            if index == failure.get('at'):
                raise ValueError('exhausted SDK attempt limit')
            filename = f'values-{index}.json'
            (runtime.workdir / filename).write_text(json.dumps({'tracks': {'sequence': 'AB'}, 'metrics': {'ptm': .7}}))
            return ESM3Result({'sequence': 'AB'}, filename, parameters, parameters.get('seed'))
        return generate
    monkeypatch.setattr('tests.fixtures.esm3_tool.create', create)
    app = Workbench(tmp_path / 'data')
    app.install('modules.esm3:module')
    app.install('tests.fixtures.esm3_tool:module')
    project = app.create_project('Sequence generation')
    workdir = app.new_workdir()
    document = {'id': 'edited', 'sequence': 'AC', 'positions': [
        {'id': 'p1', 'residue': 'A', 'prompt': 'A', 'fixed': True, 'coordinates': {'CA': [1., 2., 3.]}, 'structure_position': {'structure': 'retained-structure', 'position': {'model': '1', 'chain': 'Q', 'author_number': 92, 'insertion_code': 'B', 'residue_name': 'ALA'}}, 'source': {'object': 'source', 'sequence_index': 1, 'position': {'sequence_index': 1, 'chain': 'Z', 'author_number': 42, 'insertion_code': 'A'}}},
        {'id': 'p2', 'residue': 'C', 'prompt': '_', 'fixed': False, 'coordinates': None}], 'random_operations': []}
    (workdir / 'input.json').write_text(json.dumps(document))
    package = app.create_input(project['id'], Delivery('workbench.sequence_conditions', 'input', {'input': 'input.json'}), workdir)
    flow = {'nodes': [{'id': 'generate', 'type': 'workbench.complete_sequence', 'inputs': {'source': [package['id']]}, 'parameters': {'samples': 3, 'conditions': {'secondary_structure': 'H_', 'sasa': [1., None]}}, 'tools': {'esm3': 'lab.esm3'}, 'tool_parameters': {'esm3': {'num_steps': 2, 'seed': 17}}}], 'edges': []}
    app.save_project(project['id'], flow, {})
    return app, project, flow, calls, failure


def test_application_generation_preserves_edit_correspondence_and_continues_fixed_call(tmp_path, monkeypatch):
    from tests.run_helpers import wait_run
    app, project, flow, calls, failure = generation_app(tmp_path, monkeypatch)
    first = wait_run(app, app.start(project['id']))
    assert first['status'] == 'failed', first
    assert len(calls) == 2
    assert calls[0][0].tracks['sequence'] == 'A_'
    assert calls[0][0].tracks['coordinates'] == [{'CA': [1., 2., 3.]}, None]
    assert calls[0][0].tracks['secondary_structure'] == 'H_'
    package = app.package(first['nodes']['generate']['outputs']['generated'][0])
    with package.open(package.entry) as stream:
        partial = json.load(stream)
    obj = partial['objects'][0]
    assert obj['sequence'] == 'AB'
    assert obj['positions'][0]['edit_position'] == 'p1'
    assert obj['positions'][0]['source']['position']['insertion_code'] == 'A'
    assert obj['positions'][0]['structure_position']['position']['author_number'] == 92
    assert obj['positions'][0]['structure_position']['position']['insertion_code'] == 'B'
    with package.open(obj['native']['file']) as stream:
        assert json.load(stream)['metrics']['ptm'] == .7
    flow['nodes'][0]['tool_parameters']['esm3']['seed'] = 999
    app.save_project(project['id'], flow, {})
    failure.clear()
    resumed = wait_run(app, app.continue_run(first['id'], 'generate'))
    assert resumed['status'] == 'succeeded', resumed
    assert len(calls) == 4 and calls[2][1]['seed'] == 17
    package = app.package(resumed['nodes']['generate']['outputs']['generated'][0])
    with package.open(package.entry) as stream:
        complete = json.load(stream)
    assert complete['objects'][0] == obj
    assert len({row['id'] for row in complete['objects']}) == 3
    adopted_project = app.create_project('Consumer')
    adopted = app.adopt(adopted_project['id'], package.id)
    app.delete_project(project['id'])
    app.uninstall('workbench.esm3')
    consumer = app.package(adopted['id'])
    with consumer.open(obj['native']['file']) as stream:
        assert json.load(stream)['tracks']['sequence'] == 'AB'


def test_local_native_worker_uses_literal_seed_and_keeps_raw_decoder_axes(tmp_path):
    import torch
    from esm.sdk.api import ESMProtein
    from modules.esm3.worker import run
    from modules.esm3.adapters import parameters_for
    payload = {'settings': {'device': 'cpu'}, 'track': 'sequence', 'tracks': {'sequence': 'A_'}, 'parameters': parameters_for({'seed': 0, 'num_steps': 2}, local=True), 'output': str(tmp_path / 'result.json')}
    random_values = []
    class Model:
        def generate(self, protein, config):
            random_values.append(torch.rand(1).item())
            assert protein.sequence == 'A_'
            return ESMProtein(sequence='AX', coordinates=torch.full((2, 37, 3), float('nan')), plddt=torch.tensor([.4, .8]), ptm=torch.tensor([.6]), pae=torch.ones(1, 4, 4))
    def load(settings):
        torch.rand(5)  # Checkpoint construction must not advance sampling RNG.
        return Model()
    run(payload, model_loader=load)
    first = json.loads((tmp_path / 'result.json').read_text())
    run(payload, model_loader=load)
    assert random_values == pytest.approx([.49625658988952637, .49625658988952637])
    assert first['actual_seed'] == 0
    values = json.loads((tmp_path / first['values_file']).read_text())
    assert values['metrics']['plddt'] == pytest.approx([.4, .8])
    assert values['metrics']['ptm'] == pytest.approx([.6])
    assert len(values['metrics']['pae'][0]) == 4
    assert values['tracks']['coordinates'][0][0] == [None, None, None]


@pytest.mark.parametrize('tracks,parameters,match', [
    ({'sequence': 'A_', 'coordinates': [{'CA': [1, 2, 3], 'ZN': [1, 2, 3]}, None]}, {}, 'atom37'),
    ({'sequence': 'A_', 'secondary_structure': 'H'}, {}, 'every input'),
    ({'sequence': 'AJ'}, {}, 'unsupported'),
    ({'sequence': 'A_'}, {'top_p': 0}, 'top_p'),
    ({'sequence': 'A_'}, {'track': 'structure'}, 'Unsupported'),
])
def test_remote_unsupported_conditions_stop_without_tool_call(tmp_path, tracks, parameters, match):
    from modules.esm3.adapters import create_remote
    from modules.esm3.contract import ESM3Request
    tool = create_remote({}, client_factory=lambda _: pytest.fail('Unsupported input reached provider'))
    with pytest.raises(ValueError, match=match):
        tool(ESM3Request('sequence', tracks), parameters, SimpleNamespace(workdir=tmp_path, cancelled=False))


def test_delivery_failure_does_not_advance_generation_progress(tmp_path, monkeypatch):
    import os
    from tests.run_helpers import wait_run
    app, project, _, calls, failure = generation_app(tmp_path, monkeypatch)
    failure.clear()
    sync = os.fsync
    monkeypatch.setattr(os, 'fsync', lambda _: (_ for _ in ()).throw(OSError('disk full')))
    first = wait_run(app, app.start(project['id']))
    assert first['status'] == 'failed'
    assert first['nodes']['generate']['outputs'] == {}
    assert first['nodes']['generate']['continuation'] is None
    monkeypatch.setattr(os, 'fsync', sync)
    resumed = wait_run(app, app.continue_run(first['id'], 'generate'))
    assert resumed['status'] == 'succeeded', resumed
    assert len(calls) == 6


def test_explicit_conversion_rejects_extended_residues_and_selects_native_chain(tmp_path):
    from core.host import Workbench
    from protein_workbench_public.module_api import Delivery
    from tests.run_helpers import wait_run
    app = Workbench(tmp_path / 'data')
    app.install('modules.esm3:module')
    project = app.create_project('Conversion')
    workdir = app.new_workdir()
    (workdir / 'input.json').write_text(json.dumps({'objects': [{'id': 'generated', 'sequence': 'AB|CD', 'positions': [{'sequence_index': i, 'source': {'position': {'sequence_index': i, 'chain': 'Z', 'author_number': i * 2 + 10, 'insertion_code': 'A' if i == 4 else ''}}} for i in range(1, 6)]}]}))
    package = app.create_input(project['id'], Delivery('workbench.esm3_generation', 'input', {'input': 'input.json'}), workdir)
    flow = {'nodes': [{'id': 'convert', 'type': 'workbench.esm3_sequence', 'inputs': {'generated': [package['id']]}}], 'edges': []}
    app.save_project(project['id'], flow, {})
    missing = wait_run(app, app.start(project['id']))
    assert missing['status'] == 'failed'
    flow['nodes'][0]['parameters'] = {'chain_index': 0}
    app.save_project(project['id'], flow, {})
    extended = wait_run(app, app.start(project['id']))
    assert extended['status'] == 'failed'
    flow['nodes'][0]['parameters'] = {'chain_index': 1}
    app.save_project(project['id'], flow, {})
    converted = wait_run(app, app.start(project['id']))
    assert converted['status'] == 'succeeded', converted
    output = app.package(converted['nodes']['convert']['outputs']['sequence'][0])
    with output.open(output.entry) as stream:
        obj = json.load(stream)['objects'][0]
        assert obj['sequence'] == 'CD'
        assert obj['positions'][0] == {'sequence_index': 1, 'chain': 'Z', 'author_number': 18, 'insertion_code': 'A'}


def test_plain_sequence_rejects_extra_components_before_generation(tmp_path, monkeypatch):
    from protein_workbench_public.module_api import Call
    from modules.esm3 import execute
    class Package:
        format = 'workbench.sequence'
        entry = 'input'
        def open(self, key):
            import io
            return io.StringIO(json.dumps({'objects': [{'id': 'protein', 'sequence': 'AC', 'ligand': 'ZN'}]}))
    with pytest.raises(ValueError, match='components'):
        execute(Call({'source': (Package(),)}, {}, {}, tools={'esm3': lambda *args: pytest.fail('Unsupported components were dropped')}), SimpleNamespace(workdir=tmp_path, cancelled=False))


def test_public_local_adapter_runs_native_worker_and_owns_only_public_files(tmp_path, monkeypatch):
    from esm.sdk.api import ESMProtein
    from modules.esm3.adapters import create_local
    from modules.esm3.contract import ESM3Request
    from modules.esm3.worker import run
    seen = []
    class Model:
        def generate(self, protein, config):
            assert config.track == 'structure'
            assert config.num_steps == 2 and config.condition_on_coordinates_only is False
            return ESMProtein(sequence=protein.sequence)
    def launch(command, **kwargs):
        payload = json.loads(__import__('pathlib').Path(command[-1]).read_text())
        assert 'token' not in payload['settings']
        assert kwargs['label'] == 'ESM3 local generation'
        assert kwargs['cancelled']() is False
        seen.append(payload)
        run(payload, model_loader=lambda settings: Model())
    monkeypatch.setattr('modules.esm3.adapters.run_worker', launch)
    result = create_local({'model_path': str(tmp_path), 'token': 'never-stage-credential'})(ESM3Request('structure', {'sequence': 'AC'}), {'num_steps': 2, 'seed': 17, 'condition_on_coordinates_only': False}, SimpleNamespace(workdir=tmp_path, cancelled=False))
    assert result.actual_seed == 17 and len(seen) == 1
    assert result.parameters['condition_on_coordinates_only'] is False
    assert (tmp_path / result.values_file).is_file()


def test_local_adapter_keeps_native_sasa_tokens_without_changing_numeric_condition(tmp_path, monkeypatch):
    from modules.esm3.adapters import create_local
    from modules.esm3.contract import ESM3Request
    from modules.esm3.worker import run
    from esm.sdk.api import ESMProtein
    class Model:
        def generate(self, protein, config):
            assert protein.sasa == ['<motif>', 12.5]
            return ESMProtein(sequence='AC', sasa=protein.sasa)
    def launch(command, **kwargs):
        from pathlib import Path
        run(json.loads(Path(command[-1]).read_text()), model_loader=lambda settings: Model())
    monkeypatch.setattr('modules.esm3.adapters.run_worker', launch)
    result = create_local({})(ESM3Request('sequence', {'sequence': 'A_', 'sasa': ['<motif>', 12.5]}), {'num_steps': 2}, SimpleNamespace(workdir=tmp_path, cancelled=False))
    assert result.tracks['sasa'] == ['<motif>', 12.5]
