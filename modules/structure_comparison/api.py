"""Public comparison execution seam for direct and explicit-conversion consumers.

Consumers may construct StructureInput using their own documented format reader.
This module never imports the prediction producer or follows a source run.
"""
from dataclasses import dataclass
import json
from uuid import uuid4

import gemmi
import numpy as np
from tmtools import tm_align

from protein_workbench_public.module_api import Delivery, Outcome
# Voluntary public reuse; installation requires structure_io in protein-workbench.
from modules.structure_io import parse, resolve_selection


@dataclass(frozen=True)
class StructureInput:
    object_id: str
    content: bytes
    format: str
    sequence: str | None = None
    label: str | None = None
    generation: dict | None = None


def read_comparison_inputs(package):
    """Read every explicitly supplied object from a supported file package."""
    if package.format not in ('workbench.prediction', 'workbench.structure_set', 'workbench.reference'):
        raise ValueError('Expected prediction, structure_set or reference input')
    with package.open(package.entry) as stream:
        document = json.load(stream)
    objects = document.get('objects') if isinstance(document, dict) else None
    if not isinstance(objects, list) or any(not isinstance(obj, dict) for obj in objects):
        raise ValueError('Comparison requires explicit structure objects')
    identities, result = set(), []
    prediction = package.format == 'workbench.prediction'
    if prediction and not isinstance(document.get('tool'), dict):
        raise ValueError('Prediction tool metadata is required')
    for obj in objects:
        identity = obj.get('id')
        if not isinstance(identity, str) or not identity or identity in identities:
            raise ValueError('Structure object identities must be nonempty and unique in each package')
        identities.add(identity)
        structure = obj.get('structure')
        if not isinstance(structure, dict) or structure.get('format') not in ('pdb', 'mmcif') or structure.get('file') not in package.files:
            raise ValueError('Structure must name a declared package PDB or mmCIF file')
        sequence = obj.get('sequence')
        if prediction and (not isinstance(sequence, str) or not sequence):
            raise ValueError('Prediction sequence is required for complete residue correspondence')
        if sequence is not None and (not isinstance(sequence, str) or not sequence):
            raise ValueError('Supplied structure sequence must be a nonempty string')
        if package.format == 'workbench.reference' and set(obj) - {'id', 'label', 'structure'}:
            raise ValueError('Reference input accepts an independent structure and optional label')
        with package.open(structure['file']) as stream:
            content = stream.read()
        generation = {'tool': document['tool'], **({'input': obj['input']} if 'input' in obj else {})} if prediction else None
        result.append(StructureInput(identity, content, structure['format'], sequence, obj.get('label'), generation))
    return result


def read_comparison_input(package):
    """Read one explicitly selected reference or one converted-format subject."""
    objects = read_comparison_inputs(package)
    if len(objects) != 1:
        raise ValueError('Comparison reference requires exactly one structure object; explicitly select one collection object')
    return objects[0]


def read_prediction(package):
    """Read one prediction through its published format, without producer code."""
    if package.format != 'workbench.prediction':
        raise ValueError('Expected workbench.prediction input')
    return read_comparison_input(package)


def read_reference(package):
    """Read an independently uploaded workbench.reference package."""
    if package.format != 'workbench.reference':
        raise ValueError('Expected workbench.reference input')
    return read_comparison_input(package)


def read_structure_set(package):
    """Read one explicit structure_set object for public execution reuse."""
    if package.format != 'workbench.structure_set':
        raise ValueError('Expected workbench.structure_set input')
    return read_comparison_input(package)


_AMINO = {'ALA': 'A', 'ARG': 'R', 'ASN': 'N', 'ASP': 'D', 'CYS': 'C', 'GLN': 'Q', 'GLU': 'E',
          'GLY': 'G', 'HIS': 'H', 'ILE': 'I', 'LEU': 'L', 'LYS': 'K', 'MET': 'M', 'PHE': 'F',
          'PRO': 'P', 'SER': 'S', 'THR': 'T', 'TRP': 'W', 'TYR': 'Y', 'VAL': 'V'}


def _parse(source, selection=None):
    if not isinstance(source.object_id, str) or not source.object_id:
        raise ValueError('Structure object id is required')
    structure = parse(source.content, source.format)
    if len(structure) != 1:
        raise ValueError('Select one conformation before comparison; multiple or missing models are unsupported')
    if selection is not None:
        if not isinstance(selection, dict) or set(selection) not in ({'chains'}, {'positions'}):
            raise ValueError('Comparison selection requires chains or actual residue positions')
        if 'chains' in selection and (not isinstance(selection['chains'], list) or len(selection['chains']) != 1):
            raise ValueError('TM-align comparison requires exactly one selected chain per structure')
        if 'positions' in selection:
            if not isinstance(selection['positions'], list):
                raise ValueError('Comparison positions must be a nonempty list of actual residue positions')
            if any(not isinstance(p, dict) or set(p) != {'chain', 'author_number', 'insertion_code'} for p in selection['positions']):
                raise ValueError('Comparison positions require actual chain, author_number and insertion_code')
            keys = [json.dumps(p, sort_keys=True) for p in selection['positions']]
            if len(set(keys)) != len(keys):
                raise ValueError('Comparison residue positions must be unique')
    chosen_atoms = set(resolve_selection(structure, selection))
    structure.setup_entities()
    atoms, residues, all_sequence = [], [], ''
    selected_components = set()
    index = 0
    for chain in structure[0]:
        chain_sequence = ''
        for residue in chain:
            identity = {'chain': chain.name, 'author_number': residue.seqid.num,
                        'insertion_code': residue.seqid.icode.strip()}
            polymer = residue.entity_type == gemmi.EntityType.Polymer
            protein = polymer and residue.name in _AMINO
            selected = any(i in chosen_atoms for i in range(index, index + len(residue)))
            if protein:
                all_sequence += _AMINO[residue.name]
                chain_sequence += _AMINO[residue.name]
            for atom in residue:
                atoms.append({**identity, 'residue_name': residue.name, 'atom_name': atom.name,
                              'element': atom.element.name, 'altloc': atom.altloc.strip('\x00 '),
                              'component': 'protein' if protein else 'other',
                              'position': [atom.pos.x, atom.pos.y, atom.pos.z]})
                index += 1
            if not selected:
                continue
            info = gemmi.find_tabulated_residue(residue.name)
            if info.kind in (gemmi.ResidueKind.RNA, gemmi.ResidueKind.DNA):
                raise ValueError('TM-align comparison does not support nucleic acid components in its selected scope')
            if polymer and not protein:
                raise ValueError(f'Unsupported protein residue {residue.name} at {identity}')
            if not protein:
                if selection is not None and 'positions' in selection:
                    raise ValueError(f'Comparison position is not a canonical protein residue: {identity}')
                continue
            key = (chain.name, residue.seqid.num, residue.seqid.icode)
            if key in selected_components:
                raise ValueError(f'Ambiguous repeated protein residue position {identity}')
            selected_components.add(key)
            ca = [atom for atom in residue if atom.name == 'CA']
            if len(ca) != 1 or ca[0].altloc not in ('\x00', ' '):
                raise ValueError(f'Every selected protein residue requires one unambiguous CA atom: {identity}')
            residues.append((_AMINO[residue.name], identity, [ca[0].pos.x, ca[0].pos.y, ca[0].pos.z]))
        if chain_sequence and (selection is None or ('chains' in selection and chain.name in selection['chains'])):
            subchain = chain.get_polymer().subchain_id()
            entity = next((item for item in structure.entities if subchain in item.subchains), None)
            if entity is not None and entity.full_sequence:
                declared = ''.join(_AMINO.get(name, '?') for name in entity.full_sequence)
                if declared != chain_sequence:
                    raise ValueError('Structure has unresolved polymer residues or incomplete sequence correspondence')
    if len({p['chain'] for _, p, _ in residues}) != 1:
        raise ValueError('TM-align comparison requires exactly one protein chain in each selected scope; select a chain explicitly')
    if len(residues) < 3:
        raise ValueError('TM-align requires at least three protein residues per selected scope')
    if source.sequence is not None and source.sequence != all_sequence:
        raise ValueError('Prediction sequence and complete structure residue correspondence disagree')
    sequence = ''.join(letter for letter, _, _ in residues)
    positions = [p for _, p, _ in residues]
    coords = np.asarray([c for _, _, c in residues], dtype=np.float64)
    return sequence, positions, coords, atoms


def comparison_parameters(parameters):
    """Validate the public selection parameters shared by both comparison nodes."""
    if set(parameters) - {'subject_selection', 'reference_selection'}:
        raise ValueError('Comparison parameters are subject_selection and reference_selection')
    return {name: parameters.get(name) for name in ('subject_selection', 'reference_selection')}


def _aligned_positions(alignment, sequence, positions):
    if alignment.replace('-', '') != sequence:
        raise ValueError('TM-align returned incomplete residue correspondence')
    cursor, aligned = 0, []
    for letter in alignment:
        aligned.append(None if letter == '-' else positions[cursor])
        cursor += letter != '-'
    return aligned


def compare(subject: StructureInput, reference: StructureInput, runtime, *, subject_selection=None, reference_selection=None):
    """Align selected protein streams and deliver a complete self-contained overlay.

Returns Outcome on output ``comparison``. See FORMAT.md for exact method scope,
normalizations, preserved inputs, alignment positions and transform convention.
"""
    if runtime.cancelled:
        return Outcome(status='cancelled')
    sx, px, x, ax = _parse(subject, subject_selection)
    sy, py, y, ay = _parse(reference, reference_selection)
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
        'region': {'subject': subject_selection, 'reference': reference_selection},
        'method': {'name': 'TM-align', 'tmtools': '0.3.0', 'algorithm': '20210224',
                   'scope': 'selected single protein chain C-alpha alignment; complete original structures retained, other components excluded from metrics', 'parameters': {}},
        'metrics': {
            'tm_subject': {'value': float(result.tm_norm_chain1), 'normalization': 'selected subject protein residue count', 'normalization_length': len(x), 'unit': 'dimensionless'},
            'tm_reference': {'value': float(result.tm_norm_chain2), 'normalization': 'selected reference protein residue count', 'normalization_length': len(y), 'unit': 'dimensionless'},
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
