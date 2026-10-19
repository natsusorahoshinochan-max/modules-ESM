"""Verify one explicitly configured solubility tool through public Workbench APIs."""
import argparse
import json
from pathlib import Path
from time import sleep

from core.host import Workbench
from protein_workbench_public.module_api import Delivery
from .formats import read_evaluations


def run(configuration, output_root):
    app = Workbench(Path(output_root))
    app.install('modules.solubility:module')
    app.configure('workbench.solubility', configuration['settings'])
    project = app.create_project('Existing sequence solubility verification')
    work = app.new_workdir()
    objects = configuration['objects']
    (work / 'input.json').write_text(json.dumps({'objects': objects}))
    package = app.create_input(project['id'], Delivery('workbench.sequence', 'manifest.json', {'manifest.json': 'input.json'}), work)
    app.save_project(project['id'], {'nodes': [{'id': 'evaluate', 'type': 'workbench.evaluate_solubility', 'inputs': {'sequence': [package['id']]}, 'tools': {'evaluator': configuration['tool']}, 'tool_parameters': {'evaluator': configuration.get('parameters', {})}}], 'edges': []}, {})
    result = app.start(project['id'])
    while result['status'] == 'running':
        sleep(.1)
        result = app.get_run(result['id'])
    if result['status'] != 'succeeded':
        raise RuntimeError(result['nodes']['evaluate']['diagnostics'])
    package = app.package(result['nodes']['evaluate']['outputs']['evaluation'][0])
    document = read_evaluations(package)
    if document['objects'] != objects:
        raise RuntimeError('Evaluation changed the supplied sequence objects')
    print(json.dumps({'run_id': result['id'], 'status': result['status'], 'evaluations': document['evaluations'], 'tool': document['tool']}))
    return document


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('configuration', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    run(json.loads(args.configuration.read_text()), args.output)


if __name__ == '__main__':
    main()
