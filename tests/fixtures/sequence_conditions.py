"""Explicit current public-format fixtures; no legacy reader."""
from copy import deepcopy
import json
from modules.structure_io.target import write_target


def condition_files(document):
    manifest = deepcopy(document)
    target = []; fixed = []; coordinates = []
    for index, row in enumerate(manifest['positions'], 1):
        xyz = row.pop('coordinates')
        all_atoms = row.pop('_target_atoms', {}).copy()
        all_atoms.update(xyz or {})
        target.append({'residue':row['residue'], 'atoms':all_atoms, **row.get('target_author', {})})
        if row['fixed']:
            fixed.append({'position':index, 'residue':row['residue']})
        if xyz:
            coordinates.append({'position':index, 'atoms':list(xyz)})
    manifest['target'] = {'file':'target.cif', 'format':'mmcif', 'chain':'A'}
    manifest['conditions'] = {'sequence':fixed, 'coordinates':coordinates}
    return {'edited.json':json.dumps(manifest).encode(), 'target.cif':write_target(target)}


def assert_manifest(document, actual):
    expected = json.loads(condition_files(document)['edited.json'])
    assert actual == expected
