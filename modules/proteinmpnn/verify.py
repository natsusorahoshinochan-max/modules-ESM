"""Run one explicit existing ProteinMPNN configuration through the application."""
import argparse
import json
from pathlib import Path
import shutil
from time import sleep

from core.host import Workbench
from protein_workbench_public.module_api import Delivery


def run(configuration, output):
    app = Workbench(output)
    app.install('modules.structure_io:module')
    app.install('modules.proteinmpnn:module')
    app.install('modules.generation:module')
    app.configure('workbench.proteinmpnn', configuration['settings'])
    project = app.create_project('ProteinMPNN verification')
    work = app.new_workdir()
    source = Path(configuration['structure'])
    shutil.copyfile(source, work / 'coordinates')
    encoding = configuration.get('format', 'pdb')
    (work / 'input.json').write_text(json.dumps({'name': source.name, 'file': 'coordinates', 'format': encoding}))
    package = app.create_input(project['id'], Delivery('workbench.structure_file', 'manifest', {'manifest': 'input.json', 'coordinates': 'coordinates'}), work)
    flow = {'nodes': [
        {'id': 'import', 'type': 'workbench.import_structure', 'inputs': {'file': [package['id']]}, 'parameters': {'models': configuration.get('model', 1)}},
        {'id': 'design', 'type': 'workbench.design_backbone', 'tools': {'mpnn': 'workbench.proteinmpnn.local'}, 'tool_parameters': {'mpnn': configuration.get('parameters', {})}}],
        'edges': [{'source': 'import', 'source_port': 'structures', 'target': 'design', 'target_port': 'structure'}]}
    app.save_project(project['id'], flow, {})
    result = app.start(project['id'])
    while result['status'] == 'running':
        sleep(.1)
        result = app.get_run(result['id'])
    if result['status'] != 'succeeded':
        raise RuntimeError({key: value['diagnostics'] for key, value in result['nodes'].items()})
    package = app.package(result['nodes']['design']['outputs']['design'][0])
    with package.open(package.entry) as stream:
        document = json.load(stream)
    print(json.dumps({'run_id': result['id'], 'status': result['status'], 'objects': [
        {'chain_lengths': {chain: len(sequence) for chain, sequence in obj['chains'].items()}, 'score': obj['design']['score'], 'global_score': obj['design']['global_score'],
         'actual_seed': obj['tool']['actual_seed'], 'positions': len(obj['positions'])} for obj in document['objects']]}))
    return document


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('configuration', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    run(json.loads(args.configuration.read_text()), args.output)
