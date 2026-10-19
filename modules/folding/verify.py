"""Run the public prediction/file-delivery flow with an explicit existing environment."""
import argparse
import json
from pathlib import Path

from core.host import Workbench
from protein_workbench_public.module_api import Delivery


def run(configuration, output_root):
    """Return a committed run record; all actual local inference locks inside Adapter."""
    app = Workbench(Path(output_root))
    app.install('modules.folding:module')
    for entry in configuration.get('modules', []):
        app.install(entry)
    for module_id, settings in configuration.get('settings', {}).items():
        app.configure(module_id, settings)
    project = app.create_project('Prediction verification')
    work = app.new_workdir()
    (work / 'sequence.json').write_text(json.dumps({'objects': [{'id': 'verification-input', 'sequence': configuration['sequence']}]}))
    package = app.create_input(project['id'], Delivery('workbench.sequence', 'sequence.json', {'sequence.json': 'sequence.json'}), work)
    app.save_project(project['id'], {'nodes': [{'id': 'predict', 'type': 'workbench.predict', 'inputs': {'sequence': [package['id']]}, 'tools': {'predictor': configuration['tool']}, 'tool_parameters': {'predictor': configuration.get('parameters', {})}}], 'edges': []}, {})
    result = app.start(project['id'])
    if result['status'] != 'succeeded':
        raise RuntimeError(result['nodes']['predict']['diagnostics'])
    output = app.package(result['nodes']['predict']['outputs']['structure'][0])
    with output.open(output.entry) as stream:
        manifest = json.load(stream)
    import gemmi
    obj = manifest['objects'][0]
    with output.open(obj['structure']['file']) as stream:
        text = stream.read().decode()
    structure = gemmi.read_pdb_string(text) if obj['structure']['format'] == 'pdb' else gemmi.make_structure_from_block(gemmi.cif.read_string(text).sole_block())
    if len(structure) != 1 or not any(residue.name for chain in structure[0] for residue in chain):
        raise RuntimeError('Prediction did not deliver a readable nonempty structure')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('configuration', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = run(json.loads(args.configuration.read_text()), args.output)
    print(json.dumps({'run_id': result['id'], 'status': result['status'], 'outputs': result['nodes']['predict']['outputs']}))


if __name__ == '__main__':
    main()
