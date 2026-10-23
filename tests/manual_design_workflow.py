#!/usr/bin/env python3
"""Build/run/verify the real two-template, two-round workflow through public APIs.

No credential is read, supplied, or written by this script. Configure the selected
ESM3 tool in the application before starting the saved project. Build is the
safe default. --run-project starts an existing saved project and waits; the HTTP
server owns calculation independently of this script's lifetime.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import json
import math
from pathlib import Path
import sys
import time
from urllib.error import HTTPError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

REPO = Path(__file__).resolve().parents[1]
COLLECTION = 'workbench.collection'
REFERENCE = 'workbench.reference'
COORDINATE_POSITIONS = [*range(1, 6), *range(31, 37)]


class HTTP:
    def __init__(self, base):
        self.base = base.rstrip('/')

    def request(self, method, path, data=None, *, raw=None):
        headers = {}
        if data is not None:
            raw = json.dumps(data, allow_nan=False).encode()
            headers['Content-Type'] = 'application/json'
        try:
            with urlopen(Request(self.base + path, data=raw, method=method, headers=headers), timeout=60) as response:
                content = response.read()
                return json.loads(content) if content else None
        except HTTPError as error:
            # Application diagnostics only; this client never requests settings.
            raise RuntimeError(f'{method} {path}: {error.code}: {error.read().decode()}') from error

    def upload(self, project, format_name, files):
        upload = self.request('POST', f'/api/projects/{project}/uploads', {})
        route = f"/api/projects/{project}/uploads/{upload['upload_id']}"
        for key, content in files.items():
            self.request('PUT', route + '/files?' + urlencode({'key': key}), raw=content)
        return self.request('POST', route + '/commit', {'format': format_name, 'entry': 'manifest.json', 'files': {key: key for key in files}})

    def file(self, package, key):
        with urlopen(self.base + f'/api/packages/{quote(package)}/file?' + urlencode({'key': key}), timeout=60) as response:
            return response.read()

    def document(self, package):
        info = self.request('GET', '/api/packages/' + quote(package))
        return json.loads(self.file(package, info['entry']))


def edge(source, source_port, target, target_port):
    return {'source': source, 'source_port': source_port, 'target': target, 'target_port': target_port}


def boundary_input(formats, *, many=False, required=True):
    return {'accepts': formats, 'cardinality': 'many' if many else 'one', 'required': required}


def scope_node(kind, identifier, nodes, edges, inputs, outputs, input_bindings, output_bindings, **configuration):
    return {'id': identifier, 'type': 'host.' + kind, 'scope': {
        'inputs': inputs, 'outputs': outputs, 'body': {'nodes': nodes, 'edges': edges},
        'input_bindings': input_bindings, 'output_bindings': output_bindings, **configuration}}


def make_flow(source_ids, reference_id, evaluation, args):
    recipe = {'selection': {'chains': ['A']}, 'tracks': [],
        'operations': [{'kind': 'insert', 'index': 11, 'sequence': '__'}, {'kind': 'delete', 'indices': [27]}],
        'template_conditions': {'fixed_positions': [1, 2, 3, 4, 5], 'coordinate_positions': COORDINATE_POSITIONS, 'atoms': ['N', 'CA', 'C']}}
    filter_parameters = {'conditions': [{'evaluation': evaluation, 'operator': 'ge', 'value': args.threshold}],
        'sort': {'evaluation': evaluation, 'direction': 'descending'}, 'limit': 1}
    controls = {'num_steps': args.sequence_steps, 'temperature': args.temperature, 'temperature_annealing': False,
        'condition_on_coordinates_only': True}
    if args.tool == 'workbench.esm3.local':
        controls['seed'] = args.seed
    inner_nodes = [
        {'id': 'extract', 'type': 'workbench.collection.extract_structures'},
        {'id': 'edit', 'type': 'workbench.edit_sequence', 'parameters': recipe},
        {'id': 'generate', 'type': 'workbench.joint_generation', 'parameters': {'samples': 2,
            'structure_parameters': {'num_steps': args.structure_steps}}, 'tools': {'esm3': args.tool}, 'tool_parameters': {'esm3': controls}},
        {'id': 'structure', 'type': 'workbench.joint_structure', 'parameters': {'chain': 'A', 'start_number': 1}},
        {'id': 'compare', 'type': 'workbench.compare', 'parameters': {'subject_selection': {'chains': ['A']}, 'reference_selection': {'chains': ['A']}}},
        {'id': 'filter', 'type': 'workbench.filter', 'parameters': filter_parameters},
    ]
    inner_edges = [edge('extract', 'structures', 'edit', 'source'), edge('edit', 'edited', 'generate', 'source'),
        edge('generate', 'generated', 'structure', 'generated'), edge('structure', 'structures', 'compare', 'subject'),
        edge('compare', 'comparison', 'filter', 'candidates'), edge('compare', 'comparison', 'filter', 'evaluations')]
    inputs = {'items': boundary_input([COLLECTION], many=True, required=False), 'reference': boundary_input([REFERENCE])}
    outputs = {'result': {'format': COLLECTION, 'cardinality': 'many'}}
    each = scope_node('map', 'each', inner_nodes, inner_edges, deepcopy(inputs), deepcopy(outputs),
        [{'input': 'items', 'node': 'extract', 'port': 'collection'}, {'input': 'reference', 'node': 'compare', 'port': 'reference'}],
        [{'output': 'result', 'node': 'filter', 'port': 'collection'}], item_input='items')
    loop = scope_node('repeat', 'design_rounds', [each,
        {'id': 'round_merge', 'type': 'workbench.collection.merge'}, {'id': 'round_split', 'type': 'workbench.collection.split'}],
        [edge('each', 'result', 'round_merge', 'packages'), edge('round_merge', 'collection', 'round_split', 'collection')], inputs, outputs,
        [{'input': 'items', 'node': 'each', 'port': 'items'}, {'input': 'reference', 'node': 'each', 'port': 'reference'}],
        [{'output': 'result', 'node': 'round_split', 'port': 'items'}], rounds=2, feedback={'items': 'result'})
    loop['inputs'] = {'reference': [reference_id]}
    return {'nodes': [
        {'id': 'initial_merge', 'type': 'workbench.collection.merge', 'inputs': {'packages': source_ids}},
        {'id': 'initial_split', 'type': 'workbench.collection.split'}, loop,
        {'id': 'final_merge', 'type': 'workbench.collection.merge'}],
        'edges': [edge('initial_merge', 'collection', 'initial_split', 'collection'),
            edge('initial_split', 'items', 'design_rounds', 'items'), edge('design_rounds', 'result', 'final_merge', 'packages')]}


def pdb_sequence(content):
    import gemmi
    structure = gemmi.read_pdb_string(content)
    return ''.join(gemmi.find_tabulated_residue(residue.name).one_letter_code for residue in structure[0]['A'] if gemmi.find_tabulated_residue(residue.name).is_amino_acid())


def protein_residues(content, encoding):
    import gemmi
    structure = (gemmi.read_pdb_string(content) if encoding == 'pdb' else
                 gemmi.make_structure_from_block(gemmi.cif.read_string(content.decode()).sole_block()))
    assert len(structure) == 1 and len(structure[0]) == 1
    return [residue for residue in structure[0]['A'] if gemmi.find_tabulated_residue(residue.name).is_amino_acid()]


def build(client, args, output):
    fixtures = args.repo / 'tests/fixtures/real_comparisons'
    records = [json.loads((fixtures / name / 'manifest.json').read_text()) for name in ('round1-candidate1', 'round1-candidate2')]
    sequences = [pdb_sequence((fixtures / name / 'subject.pdb').read_bytes()) for name in ('round1-candidate1', 'round1-candidate2')]
    assert all(len(sequence) == 58 and sequence.startswith('MTYKL') for sequence in sequences), sequences
    project = client.request('POST', '/api/projects', {'name': args.name})
    source_ids = []
    for name, record in zip(('round1-candidate1', 'round1-candidate2'), records, strict=True):
        source = client.upload(project['id'], 'workbench.structure_set', {
            'manifest.json': json.dumps({'objects': [record['subject']]}, ensure_ascii=False).encode(),
            'subject.pdb': (fixtures / name / 'subject.pdb').read_bytes()})
        source_ids.append(source['id'])
    reference_bytes = (fixtures / 'round1-candidate1/reference.pdb').read_bytes()
    assert len(pdb_sequence(reference_bytes)) == 56
    reference = client.upload(project['id'], REFERENCE, {
        'manifest.json': json.dumps({'objects': [records[0]['reference']]}, ensure_ascii=False).encode(),
        'reference.pdb': reference_bytes})
    evaluation = {'metric': 'tm_reference', 'method': records[0]['method'], 'reference': records[0]['reference'], 'region': records[0]['region']}
    flow = make_flow(source_ids, reference['id'], evaluation, args)
    layout = {'initial_merge': {'x': 40, 'y': 80}, 'initial_split': {'x': 600, 'y': 80},
        'design_rounds': {'x': 1160, 'y': 80}, 'final_merge': {'x': 1720, 'y': 80}}
    client.request('PUT', f"/api/projects/{project['id']}", {'flow': flow, 'layout': layout})
    plan = {'project_id': project['id'], 'source_packages': source_ids, 'reference_package': reference['id'],
        'reference_object': records[0]['reference'], 'source_sequences': sequences, 'tool': args.tool,
        'rounds': 2, 'initial_templates': 2, 'samples_per_template': 2, 'limit_per_template': 1, 'threshold': args.threshold,
        'expected_lengths': [59, 60], 'fixed_sequence': 'MTYKL', 'coordinate_positions_after_edit': COORDINATE_POSITIONS,
        'scientific_call_budget_if_each_template_survives': {'sequence_generate': 8, 'structure_generate': 8, 'tm_align': 8},
        'empty_selection': 'No thresholds are relaxed. Empty selections remove that template from next-round input.'}
    (output / 'plan.json').write_text(json.dumps(plan, indent=2, ensure_ascii=False))
    (output / 'flow.json').write_text(json.dumps(flow, indent=2, ensure_ascii=False))
    print(json.dumps({'action': 'built', 'project_id': project['id'], 'output': str(output), 'model_calls_started': 0}), flush=True)
    return project['id']


def collection_ids(client, packages):
    return [item['object']['id'] for package in packages for item in client.document(package)['items']]


def output_package(run, node, port):
    packages = run['nodes'][node]['outputs'][port]
    assert len(packages) == 1, (node, port, packages)
    return packages[0]


def verify(client, run, output):
    from modules.structure_io.target import read_target
    assert run['status'] == 'succeeded', {'status': run['status'], 'failures': {
        key: state.get('diagnostics') for key, state in run['nodes'].items() if state['status'] != 'succeeded'}}
    flow = run['flow']
    loop = next(node for node in flow['nodes'] if node['id'] == 'design_rounds')
    each_spec = next(node for node in loop['scope']['body']['nodes'] if node['id'] == 'each')
    filter_parameters = next(node for node in each_spec['scope']['body']['nodes'] if node['id'] == 'filter')['parameters']
    threshold = filter_parameters['conditions'][0]['value']
    reference_package = loop['inputs']['reference'][0]
    reference_bytes = client.file(reference_package, 'reference.pdb')
    expected_inputs = run['nodes']['initial_split']['outputs']['items']
    assert len(expected_inputs) == 2
    rounds = run['scopes']['design_rounds']['iterations']
    assert len(rounds) == 2, rounds
    report = {'run_id': run['id'], 'project_id': run['project_id'], 'status': run['status'], 'threshold': threshold,
        'rounds': [], 'successful_sequence_stages': 0, 'successful_structure_stages': 0, 'actual_comparisons': 0}
    for number, round_record in enumerate(rounds, 1):
        each_id = round_record['nodes']['each']
        items = run['scopes'][each_id]['iterations']
        assert len(items) == len(expected_inputs), (number, len(items), len(expected_inputs))
        summary = {'round': number, 'input_objects': collection_ids(client, expected_inputs), 'templates': []}
        expected_selected = []
        for ordinal, (item, expected_package) in enumerate(zip(items, expected_inputs, strict=True), 1):
            nodes = item['nodes']
            assert run['calls'][nodes['extract']]['inputs']['collection'] == [expected_package]
            assert run['calls'][nodes['compare']]['inputs']['reference'] == [reference_package]
            edited_id = output_package(run, nodes['edit'], 'edited')
            edited = client.document(edited_id)
            target_bytes = client.file(edited_id, edited['target']['file'])
            target = read_target(target_bytes)
            expected_length = 58 + number
            assert len(target['sequence']) == expected_length and len(edited['sequence']) == expected_length
            assert edited['sequence'].startswith('MTYKL')
            assert edited['conditions']['sequence'] == [{'position': i + 1, 'residue': letter} for i, letter in enumerate('MTYKL')]
            assert edited['conditions']['coordinates'] == [{'position': i, 'atoms': ['N', 'CA', 'C']} for i in COORDINATE_POSITIONS]
            assert target['positions'][11]['atoms'] == {} and target['positions'][12]['atoms'] == {}
            template_id = output_package(run, nodes['extract'], 'structures')
            template = client.document(template_id)['objects'][0]['structure']
            source_residues = protein_residues(client.file(template_id, template['file']), template['format'])
            correspondence = list(range(len(source_residues)))
            correspondence[11:11] = [None, None]
            del correspondence[26]
            assert len(correspondence) == expected_length
            for position in COORDINATE_POSITIONS:
                original = source_residues[correspondence[position - 1]]
                for atom_name in ('N', 'CA', 'C'):
                    atoms = [atom for atom in original if atom.name == atom_name]
                    assert len(atoms) == 1
                    actual = target['positions'][position - 1]['atoms'][atom_name]
                    expected = [atoms[0].pos.x, atoms[0].pos.y, atoms[0].pos.z]
                    assert all(math.isclose(a, b, abs_tol=1e-6, rel_tol=0) for a, b in zip(actual, expected, strict=True))
            generated_id = output_package(run, nodes['generate'], 'generated')
            generated = client.document(generated_id)
            assert generated['batch']['completed'] == 2 and generated['batch']['total'] == 2
            assert generated['pending_sequence'] is None and len(generated['objects']) == 2
            for candidate in generated['objects']:
                assert len(candidate['sequence']) == expected_length and candidate['sequence'].startswith('MTYKL')
                assert candidate['sequence_stage']['sequence'] == candidate['sequence']
                assert candidate['coordinate_role'] == 'generated_structure' and candidate['structure']['format'] == 'mmcif'
                assert candidate['generation']['conditions'] == edited['conditions']
                assert client.file(generated_id, candidate['generation']['target']['file']) == target_bytes
                import gemmi
                actual_residues = protein_residues(client.file(generated_id, candidate['structure']['file']), 'mmcif')
                assert ''.join(gemmi.find_tabulated_residue(residue.name).one_letter_code for residue in actual_residues) == candidate['sequence']
            structure_document = client.document(output_package(run, nodes['structure'], 'structures'))
            expected_candidate_ids = [obj['id'] for obj in structure_document['objects']]
            assert expected_candidate_ids == [obj['id'] for obj in generated['objects']]
            comparisons = run['nodes'][nodes['compare']]['outputs']['comparison']
            assert len(comparisons) == 2
            scored = []
            for package in comparisons:
                comparison = client.document(package)
                assert comparison['reference'] == filter_parameters['sort']['evaluation']['reference']
                assert comparison['method'] == filter_parameters['sort']['evaluation']['method']
                assert comparison['region'] == filter_parameters['sort']['evaluation']['region']
                assert client.file(package, comparison['reference']['structure']['file']) == reference_bytes
                scored.append({'id': comparison['subject']['id'], 'tm_reference': comparison['metrics']['tm_reference']['value'],
                    'rmsd': comparison['metrics']['rmsd']['value'], 'package': package})
            assert [row['id'] for row in scored] == expected_candidate_ids
            # Independent expected order: raw comparison values, stable descending sort,
            # threshold before quantity limit. No filtering implementation is imported.
            eligible = [row for row in scored if row['tm_reference'] >= threshold]
            expected = [row['id'] for row in sorted(eligible, key=lambda row: -row['tm_reference'])[:1]]
            selected = collection_ids(client, run['nodes'][nodes['filter']]['outputs']['collection'])
            assert selected == expected, {'round': number, 'item': ordinal, 'scores': scored, 'expected': expected, 'selected': selected}
            expected_selected.extend(selected)
            summary['templates'].append({'item': ordinal, 'input_package': expected_package, 'target_length': expected_length,
                'edited_package': edited_id, 'generation_node': nodes['generate'], 'scores': scored, 'selected': selected,
                'coordinate_conditions_checked_against_input': len(COORDINATE_POSITIONS),
                'generated_target_files_equal_edit': True, 'actual_structure_sequences_checked': 2})
            report['successful_sequence_stages'] += 2
            report['successful_structure_stages'] += 2
            report['actual_comparisons'] += 2
        feedback = run['nodes'][round_record['nodes']['round_split']]['outputs']['items']
        assert collection_ids(client, feedback) == expected_selected
        expected_inputs = feedback
        summary['output_objects'] = expected_selected
        report['rounds'].append(summary)
    final = run['nodes']['final_merge']['outputs']['collection']
    report['final_objects'] = collection_ids(client, final)
    report['final_collection'] = final[0]
    assert report['final_objects'] == report['rounds'][-1]['output_objects']
    report['two_templates_survived_each_round'] = all(len(row['templates']) == 2 and len(row['output_objects']) == 2 for row in report['rounds'])
    (output / 'verification.json').write_text(json.dumps(report, indent=2, ensure_ascii=False))
    print(json.dumps({'action': 'verified', 'run_id': run['id'], 'verification': str(output / 'verification.json'),
        'final_objects': report['final_objects'], 'two_templates_survived_each_round': report['two_templates_survived_each_round'],
        'successful_sequence_stages': report['successful_sequence_stages'], 'successful_structure_stages': report['successful_structure_stages'],
        'actual_comparisons': report['actual_comparisons']}), flush=True)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url', default='http://127.0.0.1:8017')
    parser.add_argument('--repo', type=Path, default=REPO)
    parser.add_argument('--output', type=Path, required=True)
    action = parser.add_mutually_exclusive_group()
    action.add_argument('--build-only', action='store_true')
    action.add_argument('--run-project', metavar='PROJECT_ID')
    action.add_argument('--verify-run', metavar='RUN_ID')
    parser.add_argument('--name', default='Real two-template two-round design')
    parser.add_argument('--tool', default='workbench.esm3.biohub')
    parser.add_argument('--threshold', type=float, default=.1)
    parser.add_argument('--sequence-steps', type=int, default=2)
    parser.add_argument('--structure-steps', type=int, default=4)
    parser.add_argument('--temperature', type=float, default=.5)
    parser.add_argument('--seed', type=int, default=181)
    args = parser.parse_args()
    sys.path.insert(0, str(args.repo))
    args.output.mkdir(parents=True, exist_ok=True)
    client = HTTP(args.base_url)
    if args.verify_run:
        run = client.request('GET', '/api/runs/' + quote(args.verify_run))
    elif args.run_project:
        run = client.request('POST', f'/api/projects/{quote(args.run_project)}/runs')
        (args.output / 'start.json').write_text(json.dumps(run, indent=2, ensure_ascii=False))
        print(json.dumps({'action': 'started', 'project_id': args.run_project, 'run_id': run['id']}), flush=True)
        previous = None
        while run['status'] == 'running':
            statuses = {key: state['status'] for key, state in run['nodes'].items()}
            if statuses != previous:
                print(json.dumps({'run_id': run['id'], 'nodes': statuses}), flush=True)
                previous = statuses
            time.sleep(2)
            run = client.request('GET', '/api/runs/' + quote(run['id']))
    else:
        build(client, args, args.output)
        return
    (args.output / 'run.json').write_text(json.dumps(run, indent=2, ensure_ascii=False))
    verify(client, run, args.output)


if __name__ == '__main__':
    main()
