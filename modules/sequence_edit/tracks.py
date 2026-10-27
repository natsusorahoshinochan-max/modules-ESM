"""Public standalone Studio track formats; each object carries its own positions."""
from copy import deepcopy
import json
import math

from modules.sequence_io.formats import ALPHABET, read_sequences, sequence_values

TRACK_FORMATS = {'sequence': 'workbench.sequence', 'coordinates': 'workbench.coordinates',
                 'secondary_structure': 'workbench.secondary_structure', 'sasa': 'workbench.sasa',
                 'function_annotations': 'workbench.function_annotations'}

TRACK_NAMES = {
    'sequence': {'zh-CN': '序列', 'en': 'Sequence'},
    'coordinates': {'zh-CN': '三维坐标', 'en': '3D coordinates'},
    'secondary_structure': {'zh-CN': '二级结构', 'en': 'Secondary structure'},
    'sasa': {'zh-CN': 'SASA', 'en': 'SASA'},
    'function_annotations': {'zh-CN': '功能注释', 'en': 'Annotations'},
}

def read_track(package, track):
    """Read a declared track independently of the producer or editor history."""
    if package.format != TRACK_FORMATS[track]:
        raise ValueError(f'Expected {TRACK_FORMATS[track]} for {track}')
    if track == 'sequence':
        return [{**obj, 'values': sequence_values(obj['sequence']),
                 'positions': deepcopy(obj.get('positions', [{'sequence_index': i + 1} for i in range(len(obj['sequence']))]))}
                for obj in read_sequences(package)]
    with package.open(package.entry) as stream:
        document = json.load(stream)
    objects = document.get('objects') if isinstance(document, dict) else None
    if not isinstance(objects, list) or not objects:
        raise ValueError(f'{track} requires a nonempty object list')
    seen = set()
    for obj in objects:
        if not isinstance(obj, dict) or not isinstance(obj.get('id'), str) or not obj['id'] or obj['id'] in seen:
            raise ValueError('Track objects require distinct identities')
        seen.add(obj['id'])
        positions, values = obj.get('positions'), obj.get('values')
        if not isinstance(positions, list) or not positions or any(not isinstance(row, dict) or type(row.get('sequence_index')) is not int or row.get('sequence_index') != i + 1 for i, row in enumerate(positions)):
            raise ValueError('Track positions must cover one explicit ordered object')
        identifiers = [row.get('id') for row in positions]
        if any(value is not None for value in identifiers) and (any(not isinstance(value, str) or not value for value in identifiers) or len(set(identifiers)) != len(identifiers)):
            raise ValueError('Track position ids must be unique and complete')
        size = len(positions)
        if not isinstance(values, list) or (track != 'function_annotations' and len(values) != size):
            raise ValueError(f'{track} must cover its declared positions')
        for value in values:
            if value is None and track != 'function_annotations':
                continue
            if track == 'secondary_structure':
                if not isinstance(value, str) or len(value) != 1 or value not in 'GHITEBSC':
                    raise ValueError('Secondary structure requires DSSP8 values or null')
            elif track == 'sasa':
                if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
                    raise ValueError('SASA requires nonnegative finite square-angstrom values or null')
            elif track == 'coordinates':
                if not isinstance(value, dict) or not value or any(not isinstance(name, str) or not name or not isinstance(xyz, list) or len(xyz) != 3 or any(type(x) not in (int, float) or not math.isfinite(x) for x in xyz) for name, xyz in value.items()):
                    raise ValueError('Coordinates require actual named atoms and finite XYZ values in angstroms')
            elif not isinstance(value, dict) or set(value) != {'label', 'start', 'end'} or not isinstance(value['label'], str) or not value['label'].strip() or type(value['start']) is not int or type(value['end']) is not int or not 1 <= value['start'] <= value['end'] <= size:
                raise ValueError('Annotations require a label and explicit inclusive position interval')
        if track == 'coordinates':
            residues = obj.get('residues')
            if not isinstance(residues, list) or len(residues) != size:
                raise ValueError('Coordinates require residue identities for all positions')
            if any(residue is not None and (not isinstance(residue, str) or len(residue) != 1 or residue not in ALPHABET) for residue in residues):
                raise ValueError('Coordinate residues require supported single letters or null')
    return objects
