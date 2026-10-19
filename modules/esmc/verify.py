"""Verify actual ESMC values through the public run, commit and reread path."""
import argparse
import json
from pathlib import Path
from time import sleep

import numpy as np
from core.host import Workbench
from protein_workbench_public.module_api import Delivery
from .formats import read_manifest, read_array


def run(configuration, output_root):
    app = Workbench(Path(output_root))
    app.install('modules.esmc:module')
    app.configure('workbench.esmc', configuration['settings'])
    project = app.create_project('ESMC verification')
    work = app.new_workdir()
    (work / 'sequence.json').write_text(json.dumps({'objects': [{'id': 'verification-input', 'sequence': configuration['sequence']}]}))
    package = app.create_input(project['id'], Delivery('workbench.sequence', 'manifest.json', {'manifest.json': 'sequence.json'}), work)
    app.save_project(project['id'], {'nodes': [{'id': 'represent', 'type': 'workbench.represent', 'inputs': {'sequence': [package['id']]}, 'tools': {'representation': configuration['tool']}, 'parameters': {'outputs': 'both', 'dtype': 'float32'}, 'tool_parameters': {'representation': configuration.get('parameters', {})}}], 'edges': []}, {})
    result = app.start(project['id'])
    while result['status'] == 'running':
        sleep(.1)
        result = app.get_run(result['id'])
    if result['status'] != 'succeeded':
        raise RuntimeError(result['nodes']['represent']['diagnostics'])
    app = Workbench(Path(output_root))
    output = app.package(result['nodes']['represent']['outputs']['representation'][0])
    obj = read_manifest(output)['objects'][0]
    summary = {'status': result['status'], 'run_id': result['id'], 'package': output.id, 'tool': configuration['tool'], 'model': configuration.get('parameters', {}).get('model', 'configured local HF'), 'token_count': len(obj['tokens']), 'residue_count': len(configuration['sequence']), 'unnamed_logit_columns': [column['index'] for column in obj['logits']['columns'] if 'name' not in column]}
    for field in ('mean_embedding', 'logits'):
        values = read_array(output, obj[field])
        if not values.size or not np.isfinite(values).all():
            raise RuntimeError(f'No readable finite {field} values')
        summary[field] = {'shape': list(values.shape), 'first_values': values.reshape(-1)[:8].tolist(), 'semantics': obj[field]['semantics'], 'files': obj[field]['pages']}
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('configuration', type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(run(json.loads(args.configuration.read_text()), args.output)))


if __name__ == '__main__':
    main()
