"""Public comparison execution seam for direct and explicit-conversion consumers.

Consumers may construct StructureInput using their own documented format reader.
This module never imports the prediction producer or follows a source run.
"""
from dataclasses import dataclass
import json
import math
from uuid import uuid4

import gemmi
import numpy as np
from tmtools import tm_align

from protein_workbench_public.module_api import Delivery, Outcome


@dataclass(frozen=True)
class StructureInput:
    object_id: str
    content: bytes
    format: str
    sequence: str | None = None
    label: str | None = None
    generation: dict | None = None


def _read(package, *, prediction):
    with package.open(package.entry) as stream:
        document = json.load(stream)
    objects = document.get('objects') if isinstance(document, dict) else None
    if not isinstance(objects, list) or len(objects) != 1 or not isinstance(objects[0], dict):
        raise ValueError('Comparison requires exactly one structure object per input package')
    obj = objects[0]
    if not isinstance(obj.get('id'), str) or not obj['id']:
        raise ValueError('Structure object id is required')
    structure = obj.get('structure')
    if not isinstance(structure, dict) or structure.get('format') not in ('pdb', 'mmcif') or not isinstance(structure.get('file'), str):
        raise ValueError('Structure must name a package PDB or mmCIF file')
    sequence = obj.get('sequence')
    if prediction and (not isinstance(sequence, str) or not sequence):
        raise ValueError('Prediction sequence is required for complete residue correspondence')
    if not prediction and set(obj) - {'id', 'label', 'structure'}:
        raise ValueError('Reference input accepts an independent structure and optional label')
    if prediction and not isinstance(document.get('tool'), dict):
        raise ValueError('Prediction tool metadata is required')
    with package.open(structure['file']) as stream:
        content = stream.read()
    return StructureInput(obj['id'], content, structure['format'], sequence if prediction else None,
                          obj.get('label'), {'tool': document['tool']} if prediction else None)


def read_prediction(package):
    """Read workbench.prediction from its published format, without producer code."""
    if package.format != 'workbench.prediction':
        raise ValueError('Expected workbench.prediction input')
    return _read(package, prediction=True)


def read_reference(package):
    """Read an independently uploaded workbench.reference package."""
    if package.format != 'workbench.reference':
        raise ValueError('Expected workbench.reference input')
    return _read(package, prediction=False)


_AMINO = {'ALA': 'A', 'ARG': 'R', 'ASN': 'N', 'ASP': 'D', 'CYS': 'C', 'GLN': 'Q', 'GLU': 'E',
          'GLY': 'G', 'HIS': 'H', 'ILE': 'I', 'LEU': 'L', 'LYS': 'K', 'MET': 'M', 'PHE': 'F',
          'PRO': 'P', 'SER': 'S', 'THR': 'T', 'TRP': 'W', 'TYR': 'Y', 'VAL': 'V'}


def _parse(source):
    if not isinstance(source.object_id, str) or not source.object_id:
        raise ValueError('Structure object id is required')
    if source.format == 'pdb':
        structure = gemmi.read_pdb_string(source.content)
    elif source.format == 'mmcif':
        document = gemmi.cif.read_string(source.content.decode('utf-8'))
        if len(document) != 1:
            raise ValueError('Select a single structure data block before comparison')
        structure = gemmi.make_structure_from_block(document.sole_block())
    else:
        raise ValueError('Comparison supports PDB and mmCIF structures')
    if len(structure) != 1:
        raise ValueError('Select one conformation before comparison; multiple or missing models are unsupported')
    structure.setup_entities()
    atoms, chains = [], []
    for chain in structure[0]:
        positions, coords, sequence = [], [], ''
        seen = set()
        for residue in chain:
            identity = {'chain': chain.name, 'author_number': residue.seqid.num,
                        'insertion_code': residue.seqid.icode.strip()}
            info = gemmi.find_tabulated_residue(residue.name)
            if info.kind in (gemmi.ResidueKind.RNA, gemmi.ResidueKind.DNA):
                raise ValueError('TM-align comparison does not support nucleic acid components')
            polymer = residue.entity_type == gemmi.EntityType.Polymer
            protein = polymer and residue.name in _AMINO
            if polymer and not protein:
                raise ValueError(f'Unsupported protein residue {residue.name} at {identity}')
            for atom in residue:
                coordinate = [atom.pos.x, atom.pos.y, atom.pos.z]
                if not all(math.isfinite(value) for value in coordinate):
                    raise ValueError(f'Nonfinite atom coordinate at {identity}')
                atoms.append({**identity, 'residue_name': residue.name, 'atom_name': atom.name,
                              'element': atom.element.name, 'altloc': atom.altloc.strip('\x00 '),
                              'component': 'protein' if protein else 'other', 'position': coordinate})
            if not protein:
                continue
            key = (chain.name, residue.seqid.num, residue.seqid.icode)
            if key in seen:
                raise ValueError(f'Ambiguous repeated protein residue position {identity}')
            seen.add(key)
            ca = [atom for atom in residue if atom.name == 'CA']
            if len(ca) != 1 or ca[0].altloc not in ('\x00', ' '):
                raise ValueError(f'Every protein residue requires one unambiguous CA atom: {identity}')
            sequence += _AMINO[residue.name]
            positions.append(identity)
            coords.append([ca[0].pos.x, ca[0].pos.y, ca[0].pos.z])
        if positions:
            subchain = chain.get_polymer().subchain_id()
            entity = next((item for item in structure.entities if subchain in item.subchains), None)
            if entity is not None and entity.full_sequence:
                declared = ''.join(_AMINO.get(name, '?') for name in entity.full_sequence)
                if declared != sequence:
                    raise ValueError('Structure has unresolved polymer residues or incomplete sequence correspondence')
            chains.append((sequence, positions, coords))
    if len(chains) != 1:
        raise ValueError('TM-align comparison requires exactly one protein chain per structure; no automatic chain pairing')
    sequence, positions, coords = chains[0]
    if len(coords) < 3:
        raise ValueError('TM-align requires at least three protein residues per structure')
    if source.sequence is not None and source.sequence != sequence:
        raise ValueError('Prediction sequence and complete structure residue correspondence disagree')
    return sequence, positions, np.asarray(coords, dtype=np.float64), atoms


def _aligned_positions(alignment, sequence, positions):
    if alignment.replace('-', '') != sequence:
        raise ValueError('TM-align returned incomplete residue correspondence')
    cursor, aligned = 0, []
    for letter in alignment:
        aligned.append(None if letter == '-' else positions[cursor])
        cursor += letter != '-'
    return aligned


def compare(subject: StructureInput, reference: StructureInput, runtime):
    """Align complete supported structures and deliver a self-contained overlay.

Returns Outcome on output ``comparison``. See FORMAT.md for exact method scope,
normalizations, preserved inputs, alignment positions and transform convention.
"""
    if runtime.cancelled:
        return Outcome(status='cancelled')
    sx, px, x, ax = _parse(subject)
    sy, py, y, ay = _parse(reference)
    result = tm_align(x, y, sx, sy)
    if runtime.cancelled:
        return Outcome(status='cancelled')
    rotation, translation = np.asarray(result.u), np.asarray(result.t)
    aligned_pair_count = sum(a != '-' and b != '-' for a, b in zip(result.seqxA, result.seqyA, strict=True))
    for atom in ax:
        atom['position'] = (np.asarray(atom['position']) @ rotation.T + translation).tolist()
    folder = runtime.workdir / uuid4().hex
    folder.mkdir()
    files = {}

    def write(key, content):
        (folder / key).write_bytes(content)
        files[key] = str((folder / key).relative_to(runtime.workdir))

    def describe(source, side):
        key = side + ('.pdb' if source.format == 'pdb' else '.cif')
        write(key, source.content)
        obj = {'id': source.object_id, 'structure': {'file': key, 'format': source.format}}
        if source.sequence is not None:
            obj['sequence'] = source.sequence
        if source.label is not None:
            obj['label'] = source.label
        if source.generation is not None:
            obj['generation'] = source.generation
        return obj

    manifest = {
        'id': uuid4().hex,
        'subject': describe(subject, 'subject'), 'reference': describe(reference, 'reference'),
        'method': {'name': 'TM-align', 'tmtools': '0.3.0', 'algorithm': '20210224',
                   'scope': 'complete single protein chain C-alpha alignment; other retained components excluded from metrics', 'parameters': {}},
        'metrics': {
            'tm_subject': {'value': float(result.tm_norm_chain1), 'normalization': 'subject protein residue count', 'normalization_length': len(x), 'unit': 'dimensionless'},
            'tm_reference': {'value': float(result.tm_norm_chain2), 'normalization': 'reference protein residue count', 'normalization_length': len(y), 'unit': 'dimensionless'},
            'rmsd': {'value': float(result.rmsd), 'unit': 'angstrom', 'scope': 'TM-align aligned C-alpha pairs', 'aligned_pair_count': aligned_pair_count},
        },
        'alignment': {'subject_sequence': result.seqxA, 'reference_sequence': result.seqyA, 'markers': result.seqM,
                      'subject_positions': _aligned_positions(result.seqxA, sx, px),
                      'reference_positions': _aligned_positions(result.seqyA, sy, py)},
        'transform': {'direction': 'subject to reference', 'convention': 'row coordinates: x @ rotation.T + translation',
                      'rotation': rotation.tolist(), 'translation': translation.tolist()},
        'overlay': 'overlay.json',
    }
    write('overlay.json', json.dumps({'subject': ax, 'reference': ay}, allow_nan=False).encode())
    write('manifest.json', json.dumps(manifest, allow_nan=False).encode())
    return Outcome(outputs={'comparison': [Delivery('workbench.comparison', 'manifest.json', files)]})
