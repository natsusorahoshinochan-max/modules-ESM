"""Joint generation through the public application, files and ESM3 slot."""
import json

import pytest

from protein_workbench_public.module_api import Delivery
from tests.run_helpers import wait_run


def joint_app(tmp_path, monkeypatch):
    from core.host import Workbench
    from modules.esm3.contract import ESM3Result
    calls, failure = [], {'structure': True}
    def create(settings):
        def generate(request, parameters, runtime):
            calls.append((request, parameters.copy()))
            if request.track == 'structure' and failure.get('structure') or failure.get('at') == len(calls):
                raise RuntimeError('exhausted SDK attempts')
            sequence = failure.get('sequence', 'AX') if request.track == 'sequence' else request.tracks['sequence']
            tracks = {'sequence': sequence, 'coordinates': [[[None, None, None]] * 37, [[None, None, None]] * 37]}
            if request.track == 'structure':
                tracks['coordinates'][0][1] = [4., 5., 6.]
            if request.track == 'structure' and failure.get('omit_coordinates'):
                tracks.pop('coordinates')
            filename = f'values-{len(calls)}.json'
            (runtime.workdir / filename).write_text(json.dumps({'tracks': tracks, 'metrics': {'ptm': [.7], 'pae': [[[1., 2.], [3., 4.]]]}}))
            return ESM3Result({'sequence': sequence}, filename, parameters, parameters.get('seed'))
        return generate
    monkeypatch.setattr('tests.fixtures.esm3_tool.create', create)
    app = Workbench(tmp_path / 'data')
    app.install('modules.esm3:module')
    app.install('modules.joint_generation:module')
    app.install('tests.fixtures.esm3_tool:module')
    project = app.create_project('Joint generation')
    workdir = app.new_workdir()
    document = {'id': 'edited', 'sequence': 'AC', 'positions': [
        {'id': 'fixed', 'residue': 'A', 'prompt': 'A', 'fixed': True, 'coordinates': {'CA': [1., 2., 3.]}, 'structure_position': {'structure': 'input-structure', 'position': {'model': '1', 'chain': 'Q', 'author_number': 92, 'insertion_code': 'B', 'residue_name': 'ALA'}}},
        {'id': 'variable', 'residue': 'C', 'prompt': '_', 'fixed': False, 'coordinates': None}], 'random_operations': []}
    (workdir / 'input.json').write_text(json.dumps(document))
    package = app.create_input(project['id'], Delivery('workbench.sequence_conditions', 'input', {'input': 'input.json'}), workdir)
    flow = {'nodes': [{'id': 'joint', 'type': 'workbench.joint_generation', 'inputs': {'source': [package['id']]}, 'parameters': {'samples': 2, 'conditions': {'secondary_structure': 'H_'}}, 'tools': {'esm3': 'lab.esm3'}, 'tool_parameters': {'esm3': {'num_steps': 2, 'seed': 0}}}], 'edges': []}
    app.save_project(project['id'], flow, {})
    return app, project, flow, calls, failure


def test_sequence_phase_survives_structure_failure_and_continues_original_call(tmp_path, monkeypatch):
    app, project, flow, calls, failure = joint_app(tmp_path, monkeypatch)
    first = wait_run(app, app.start(project['id']))
    assert first['status'] == 'failed', first
    assert [request.track for request, _ in calls] == ['sequence', 'structure']
    assert calls[0][0].tracks['sequence'] == 'A_'
    assert calls[1][0].tracks == {'sequence': 'AX', 'secondary_structure': 'H_', 'coordinates': [{'CA': [1., 2., 3.]}, None]}
    package = app.package(first['nodes']['joint']['outputs']['generated'][0])
    with package.open(package.entry) as stream:
        partial = json.load(stream)
    pending = partial['pending_sequence']
    assert partial['batch'] == {'completed': 0, 'total': 2, 'status': 'failed', 'sequence_completed': 1}
    assert partial['objects'] == [] and pending['sequence'] == 'AX'
    assert pending['positions'][0]['structure_position']['position']['insertion_code'] == 'B'
    with package.open(pending['native']['file']) as stream:
        assert json.load(stream)['metrics']['ptm'] == [.7]
    flow['nodes'][0]['tool_parameters']['esm3']['seed'] = 99
    app.save_project(project['id'], flow, {})
    failure.clear()
    resumed = wait_run(app, app.continue_run(first['id'], 'joint'))
    assert resumed['status'] == 'succeeded', resumed
    assert [request.track for request, _ in calls] == ['sequence', 'structure', 'structure', 'sequence', 'structure']
    assert calls[2][1]['seed'] == 0
    assert calls[2][0] == calls[1][0]
    package = app.package(resumed['nodes']['joint']['outputs']['generated'][0])
    with package.open(package.entry) as stream:
        complete = json.load(stream)
    assert complete['objects'][0]['sequence_stage'] == pending
    assert len(complete['objects']) == 2 and complete['pending_sequence'] is None
    assert complete['objects'][0]['generation']['sequence_object'] == pending['id']
    target = app.create_project('Independent reader')
    adopted = app.adopt(target['id'], package.id)
    app.delete_project(project['id'])
    app.uninstall('workbench.joint_generation')
    app.uninstall('workbench.esm3')
    independent = app.package(adopted['id'])
    with independent.open(complete['objects'][0]['native']['file']) as stream:
        native = json.load(stream)
    assert native['tracks']['coordinates'][0][1] == [4., 5., 6.]
    assert native['tracks']['coordinates'][1][1] == [None, None, None]
    assert native['metrics']['pae'] == [[[1., 2.], [3., 4.]]]


def test_failed_reception_cannot_accept_sequence_phase_progress(tmp_path, monkeypatch):
    import os
    app, project, _, calls, failure = joint_app(tmp_path, monkeypatch)
    sync = os.fsync
    monkeypatch.setattr(os, 'fsync', lambda _: (_ for _ in ()).throw(OSError('disk full')))
    first = wait_run(app, app.start(project['id']))
    assert first['status'] == 'failed'
    assert first['nodes']['joint']['outputs'] == {}
    assert first['nodes']['joint']['continuation'] is None
    monkeypatch.setattr(os, 'fsync', sync)
    failure.clear()
    continued = wait_run(app, app.continue_run(first['id'], 'joint'))
    assert continued['status'] == 'succeeded', continued
    assert [request.track for request, _ in calls] == ['sequence', 'structure', 'sequence', 'structure', 'sequence', 'structure']


def test_explicit_stage_conversion_uses_existing_sequence_consumer_after_producer_uninstall(tmp_path, monkeypatch):
    app, project, _, _, failure = joint_app(tmp_path, monkeypatch)
    failure.clear()
    result = wait_run(app, app.start(project['id']))
    package_id = result['nodes']['joint']['outputs']['generated'][0]
    consumer = app.create_project('Stage conversion')
    adopted = app.adopt(consumer['id'], package_id)
    # Explicitly choose sequence stage; native X must fail canonical conversion.
    flow = {'nodes': [
        {'id': 'stage', 'type': 'workbench.joint_to_esm3', 'inputs': {'generated': [adopted['id']]}, 'parameters': {'stage': 'sequence'}},
        {'id': 'sequence', 'type': 'workbench.esm3_sequence'}],
        'edges': [{'source': 'stage', 'source_port': 'generated', 'target': 'sequence', 'target_port': 'generated'}]}
    app.save_project(consumer['id'], flow, {})
    converted = wait_run(app, app.start(consumer['id']))
    assert converted['nodes']['stage']['status'] == 'succeeded', converted
    assert converted['nodes']['sequence']['status'] == 'failed', converted
    native = app.package(converted['nodes']['stage']['outputs']['generated'][0])
    app.delete_project(project['id'])
    app.uninstall('workbench.joint_generation')
    with native.open(native.entry) as stream:
        document = json.load(stream)
    assert document['objects'][0]['sequence'] == 'AX'
    with native.open(document['objects'][0]['native']['file']) as stream:
        assert json.load(stream)['metrics']['ptm'] == [.7]


def test_completed_samples_accumulate_and_sequence_failure_stops_unstarted_requests(tmp_path, monkeypatch):
    app, project, _, calls, failure = joint_app(tmp_path, monkeypatch)
    failure.clear()
    failure['at'] = 3
    first = wait_run(app, app.start(project['id']))
    assert first['status'] == 'failed', first
    package = app.package(first['nodes']['joint']['outputs']['generated'][0])
    with package.open(package.entry) as stream:
        partial = json.load(stream)
    original = partial['objects'][0]
    assert partial['batch']['completed'] == 1 and partial['pending_sequence'] is None
    assert [request.track for request, _ in calls] == ['sequence', 'structure', 'sequence']
    failure.clear()
    resumed = wait_run(app, app.continue_run(first['id'], 'joint'))
    assert resumed['status'] == 'succeeded', resumed
    assert [request.track for request, _ in calls] == ['sequence', 'structure', 'sequence', 'sequence', 'structure']
    package = app.package(resumed['nodes']['joint']['outputs']['generated'][0])
    with package.open(package.entry) as stream:
        complete = json.load(stream)
    assert complete['objects'][0] == original
    assert complete['objects'][1]['id'] != original['id']


def test_both_phases_reach_actual_sdk_with_explicit_controls_and_preserve_native_axes(tmp_path, monkeypatch):
    import torch
    from esm.sdk.api import ESMProtein
    from modules.esm3.adapters import create_remote
    app, project, flow, _, _ = joint_app(tmp_path, monkeypatch)
    flow['nodes'][0]['parameters']['samples'] = 1
    flow['nodes'][0]['parameters']['structure_parameters'] = {'temperature': .25, 'num_steps': 1, 'only_compute_backbone_rmsd': True}
    flow['nodes'][0]['tool_parameters']['esm3'] = {'num_steps': 2, 'temperature': .8, 'condition_on_coordinates_only': False}
    app.save_project(project['id'], flow, {})
    calls = []
    class Client:
        def generate(self, protein, config):
            calls.append((protein, config))
            coords = torch.full((2, 37, 3), float('nan'))
            coords[0, 1] = torch.tensor([8., 9., 10.])
            return ESMProtein(sequence='AC', coordinates=coords, plddt=torch.tensor([.4, .8]), ptm=torch.tensor([.6]), pae=torch.ones(1, 4, 4))
        def close(self):
            pass
    monkeypatch.setattr('tests.fixtures.esm3_tool.create', lambda settings: create_remote(settings, client_factory=lambda _: Client()))
    result = wait_run(app, app.start(project['id']))
    assert result['status'] == 'succeeded', result
    assert len(calls) == 2
    assert calls[0][0].sequence == 'A_' and calls[1][0].sequence == 'AC'
    assert calls[1][0].coordinates[0, 1].tolist() == [1., 2., 3.]
    assert torch.isnan(calls[1][0].coordinates[1]).all()
    assert calls[1][0].secondary_structure == 'H_'
    assert calls[0][1].track == 'sequence' and calls[0][1].temperature == .8
    assert calls[1][1].track == 'structure' and calls[1][1].temperature == .25
    assert calls[1][1].only_compute_backbone_rmsd is True
    assert calls[1][1].condition_on_coordinates_only is False
    package = app.package(result['nodes']['joint']['outputs']['generated'][0])
    with package.open(package.entry) as stream:
        manifest = json.load(stream)
    obj = manifest['objects'][0]
    assert obj['tool']['actual_seed'] is None
    with package.open(obj['native']['file']) as stream:
        native = json.load(stream)
    assert native['tracks']['coordinates'][0][1] == [8., 9., 10.]
    assert len(native['metrics']['pae'][0]) == 4
    assert native['metrics']['plddt'] == pytest.approx([.4, .8])


@pytest.mark.parametrize('unsupported', ['seed', 'atoms'])
def test_unsupported_remote_input_stops_before_provider(tmp_path, monkeypatch, unsupported):
    from modules.esm3.adapters import create_remote
    app, project, flow, _, _ = joint_app(tmp_path, monkeypatch)
    if unsupported == 'atoms':
        flow['nodes'][0]['tool_parameters']['esm3'].pop('seed')
        original = app.package(flow['nodes'][0]['inputs']['source'][0])
        with original.open(original.entry) as stream:
            document = json.load(stream)
        document['positions'][0]['coordinates']['ZN'] = [4., 5., 6.]
        workdir = app.new_workdir()
        (workdir / 'input.json').write_text(json.dumps(document))
        package = app.create_input(project['id'], Delivery('workbench.sequence_conditions', 'input', {'input': 'input.json'}), workdir)
        flow['nodes'][0]['inputs']['source'] = [package['id']]
    monkeypatch.setattr('tests.fixtures.esm3_tool.create', lambda settings: create_remote(settings, client_factory=lambda _: pytest.fail('Unsupported whole input reached provider')))
    app.save_project(project['id'], flow, {})
    result = wait_run(app, app.start(project['id']))
    assert result['status'] == 'failed'
    assert result['nodes']['joint']['outputs'] == {'generated': []}
    assert result['nodes']['joint']['continuation'] == {'completed': 0, 'sequence_ready': False}
    assert ('seed' if unsupported == 'seed' else 'atom37') in result['nodes']['joint']['diagnostics'][0]


def test_missing_structure_output_retains_only_successful_sequence_phase(tmp_path, monkeypatch):
    app, project, flow, calls, failure = joint_app(tmp_path, monkeypatch)
    failure.clear()
    failure['omit_coordinates'] = True
    first = wait_run(app, app.start(project['id']))
    assert first['status'] == 'failed', first
    assert 'actual native atom37 coordinates' in first['nodes']['joint']['diagnostics'][0]
    package = app.package(first['nodes']['joint']['outputs']['generated'][0])
    with package.open(package.entry) as stream:
        partial = json.load(stream)
    assert partial['objects'] == [] and partial['pending_sequence']['sequence'] == 'AX'
    assert len(package.files) == 2  # only accepted sequence file and manifest
    failure.clear()
    resumed = wait_run(app, app.continue_run(first['id'], 'joint'))
    assert resumed['status'] == 'succeeded', resumed
    assert [request.track for request, _ in calls] == ['sequence', 'structure', 'structure', 'sequence', 'structure']


def test_explicit_structure_conversion_reaches_structure_view_and_both_export_formats(tmp_path):
    from core.host import Workbench
    from modules.structure_io import read_structure, atoms
    app = Workbench(tmp_path / 'data')
    app.install('modules.joint_generation:module')
    app.install('modules.structure_io:module')
    project = app.create_project('Native structure conversion')
    workdir = app.new_workdir()
    coords = [[[None, None, None] for _ in range(37)] for _ in range(2)]
    coords[0][1] = [1.125, 2.25, 3.5]
    coords[1][1] = [4.125, 5.25, 6.5]
    native = {'tracks': {'sequence': 'AC', 'coordinates': coords}, 'metrics': {'ptm': .8}}
    original = {'id': 'actual-generated', 'sequence': 'AC', 'positions': [{'sequence_index': 1, 'edit_position': 'original-a', 'source': {'object': 'input-sequence', 'sequence_index': 4, 'position': {'chain': 'Z', 'author_number': 42, 'insertion_code': 'A'}}, 'structure_position': {'structure': 'input-structure', 'position': {'model': '1', 'chain': 'K', 'author_number': 92, 'insertion_code': 'B', 'residue_name': 'ALA'}}}, {'sequence_index': 2, 'edit_position': 'inserted-c'}], 'native': {'file': 'native.json'}, 'generation': {'input': 'editing', 'sample': 1, 'sequence_object': 'actual-sequence'}, 'tool': {'parameters': {'seed': 0}, 'actual_seed': 0}, 'sequence_stage': {'id': 'actual-sequence', 'sequence': 'AC', 'native': {'file': 'sequence.json'}}}
    manifest = {'objects': [original], 'pending_sequence': None, 'batch': {'completed': 1, 'sequence_completed': 1, 'total': 1, 'status': 'succeeded'}, 'tool': {'id': 'workbench.esm3.local', 'parameters': {'seed': 0}, 'structure_parameters': {}}}
    for key, value in [('input.json', manifest), ('native.json', native), ('sequence.json', {'tracks': {'sequence': 'AC'}, 'metrics': {}})]:
        (workdir / key).write_text(json.dumps(value))
    package = app.create_input(project['id'], Delivery('workbench.joint_generation', 'input.json', {key: key for key in ('input.json', 'native.json', 'sequence.json')}), workdir)
    flow = {'nodes': [{'id': 'convert', 'type': 'workbench.joint_structure', 'inputs': {'generated': [package['id']]}, 'parameters': {'chain': 'Q', 'start_number': 17}}], 'edges': []}
    app.save_project(project['id'], flow, {})
    result = wait_run(app, app.start(project['id']))
    assert result['status'] == 'succeeded', result
    output = app.package(result['nodes']['convert']['outputs']['structures'][0])
    with output.open(output.entry) as stream:
        converted = json.load(stream)
    obj = converted['objects'][0]
    assert obj['id'] == original['id'] and obj['source_object'] == original
    assert obj['native_positions'][0] == {'sequence_index': 1, 'original_position': original['positions'][0], 'position': {'model': 1, 'chain': 'Q', 'author_number': 17, 'insertion_code': '', 'residue_name': 'ALA'}}
    structure = read_structure(output, obj['id'])
    assert all(atom.occ == 1.0 and atom.b_iso == 0.0 for chain in structure[0] for residue in chain for atom in residue)
    view = atoms(structure)
    assert [(row['chain'], row['author_number'], row['atom_name']) for row in view] == [('Q', 17, 'CA'), ('Q', 18, 'CA')]
    assert view[0]['position'] == [1.125, 2.25, 3.5]
    assert 'confidence' not in obj
    flow = {'nodes': [{'id': encoding, 'type': 'workbench.export_structure', 'inputs': {'structures': [output.id]}, 'parameters': {'object': obj['id'], 'format': encoding}} for encoding in ('pdb', 'mmcif')], 'edges': []}
    app.save_project(project['id'], flow, {})
    exported = wait_run(app, app.start(project['id']))
    assert exported['status'] == 'succeeded', exported
    target = app.create_project('Independent structure consumer')
    adopted = app.adopt(target['id'], output.id)
    app.delete_project(project['id'])
    app.uninstall('workbench.joint_generation')
    independent = app.package(adopted['id'])
    assert len(atoms(read_structure(independent, obj['id']))) == 2
    with independent.open('native.json') as stream:
        assert json.load(stream)['metrics']['ptm'] == .8


@pytest.mark.parametrize('sequence,missing,match', [('AX', False, 'canonical single chain'), ('AC|D', False, 'canonical single chain'), ('AC', True, 'no finite atoms')])
def test_structure_conversion_refuses_unrepresentable_native_results_without_changing_them(tmp_path, sequence, missing, match):
    from core.host import Workbench
    app = Workbench(tmp_path / 'data')
    app.install('modules.joint_generation:module')
    project = app.create_project('Explicit conversion limits')
    workdir = app.new_workdir()
    coords = [[[None, None, None] for _ in range(37)] for _ in sequence]
    for index, row in enumerate(coords):
        if not missing or index == 0:
            row[1] = [float(index), 2., 3.]
    native = {'tracks': {'sequence': sequence, 'coordinates': coords}, 'metrics': {'ptm': .8}}
    obj = {'id': 'native', 'sequence': sequence, 'positions': [{'sequence_index': index + 1} for index in range(len(sequence))], 'native': {'file': 'native.json'}}
    manifest = {'objects': [obj], 'pending_sequence': None, 'tool': {'id': 'actual-generator', 'parameters': {}}}
    (workdir / 'manifest.json').write_text(json.dumps(manifest))
    (workdir / 'native.json').write_text(json.dumps(native))
    package = app.create_input(project['id'], Delivery('workbench.joint_generation', 'manifest.json', {'manifest.json': 'manifest.json', 'native.json': 'native.json'}), workdir)
    flow = {'nodes': [{'id': 'convert', 'type': 'workbench.joint_structure', 'inputs': {'generated': [package['id']]}, 'parameters': {'chain': 'Q', 'start_number': 17}}], 'edges': []}
    app.save_project(project['id'], flow, {})
    result = wait_run(app, app.start(project['id']))
    assert result['status'] == 'failed'
    assert match in result['nodes']['convert']['diagnostics'][0]
    assert not any(result['nodes']['convert']['outputs'].values())
    with app.package(package['id']).open('native.json') as stream:
        assert json.load(stream) == native
