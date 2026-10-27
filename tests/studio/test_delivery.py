"""Acceptance tests for the confirmed direct-edit contract, independent of the archive."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from modules.sequence_edit import edit
from modules.sequence_edit.target_delivery import read_document
from protein_workbench_public.module_api import Call


class Package:
    format = 'workbench.protein'
    entry = 'edited.json'

    def __init__(self, result, root):
        self.root = root
        self.mapping = result.outputs['edited'].files
        self.files = tuple(self.mapping)

    def open(self, key):
        return (self.root / self.mapping[key]).open('rb')


def run(tmp_path, parameters, source=None):
    root = tmp_path / str(len(list(tmp_path.iterdir())))
    root.mkdir()
    result = edit(Call(inputs={'source': (source,)} if source else {}, parameters=parameters, settings={}), SimpleNamespace(workdir=root, cancelled=False))
    return result, Package(result, root), root


def test_delete_restore_keeps_all_tracks_and_filters_all_outputs(tmp_path):
    result, initial, _ = run(tmp_path, {'sequence': 'ACD', 'operations': [
        {'kind': 'update', 'indices': [2], 'changes': {'coordinates': {'CA': [1., 2., 3.]}, 'secondary_structure': 'H', 'sasa': 12., 'function_annotations': ['site']}},
    ]})
    before = read_document(initial)
    target = before['positions'][1]
    _, deleted, root = run(tmp_path, {'operation': {'kind': 'delete', 'positions': [target['id']]}}, initial)
    editor = read_document(deleted)
    assert len(editor['positions']) == 3
    assert editor['positions'][1]['deleted'] is True
    assert editor['positions'][1]['coordinates'] == {'CA': [1., 2., 3.]}
    assert editor['baseline'] == before['baseline']
    manifest = json.loads((root / 'edited.json').read_text())
    assert len(manifest['positions']) == 2
    assert manifest['tracks']['sequence'] == ['A', 'D']
    assert 'baseline' not in manifest
    for track in ['sequence', 'coordinates', 'secondary_structure', 'sasa', 'function_annotations']:
        obj = json.loads((root / f'{track}.json').read_text())['objects'][0]
        assert len(obj['positions']) == 2
    _, restored, _ = run(tmp_path, {'operation': {'kind': 'update', 'positions': [target['id']], 'changes': {'residue': 'G'}}}, deleted)
    row = read_document(restored)['positions'][1]
    assert row['deleted'] is False
    assert row['residue'] == 'G'
    for track in ['coordinates', 'secondary_structure', 'sasa', 'function_annotations']:
        assert row[track] == target[track]


def test_replace_rows_persists_new_empty_positions_and_independent_changes(tmp_path):
    _, package, _ = run(tmp_path, {'sequence': 'AXUOBJZ'})
    original = read_document(package)
    rows = [{key: row[key] for key in ['id','residue','coordinates','secondary_structure','sasa','function_annotations']} | {'deleted': False} for row in original['positions']]
    rows[0]['residue'] = None
    rows[1]['sasa'] = 42
    rows[2]['secondary_structure'] = 'E'
    rows.insert(1, dict(id='new-position', residue=None, coordinates=None, secondary_structure=None, sasa=None, function_annotations=[], deleted=False))
    _, output, _ = run(tmp_path, {'operation': {'kind': 'replace_rows', 'rows': rows}}, package)
    reopened = read_document(output)
    assert reopened['baseline'] == original['baseline']
    assert 'new-position' not in reopened['baseline']
    assert reopened['positions'][1]['coordinates'] is None
    assert reopened['positions'][2]['residue'] == 'X'
    assert reopened['positions'][2]['sasa'] == 42
    assert reopened['positions'][3]['secondary_structure'] == 'E'


def test_deleted_only_document_cannot_be_delivered_as_valid_protein(tmp_path):
    _, package, _ = run(tmp_path, {'sequence': 'A'})
    with pytest.raises(ValueError, match='有效位置'):
        run(tmp_path, {'operation': {'kind': 'delete', 'indices': [1]}}, package)


def test_replace_cannot_discard_original_rows(tmp_path):
    _, package, _ = run(tmp_path, {'sequence': 'AC'})
    with pytest.raises(ValueError, match='Keep removed rows'):
        run(tmp_path, {'operation': {'kind': 'replace_rows', 'rows': []}}, package)


@pytest.mark.parametrize('file_format', ['pdb', 'mmcif'])
def test_real_import_edit_reopen_and_export_preserves_original_and_alignment(tmp_path, file_format):
    import io
    import gemmi
    from modules.structure_io import import_structure
    from modules.structure_io.target import read_target

    original = Path('tests/fixtures/real_comparisons/round2-candidate1/reference.pdb').read_bytes()
    if file_format == 'mmcif':
        structure = gemmi.read_pdb_string(original.decode())
        structure.setup_entities()
        structure.assign_label_seq_id()
        original = structure.make_mmcif_document().as_string().encode()

    class FileInput:
        entry = 'file.json'
        def open(self, key):
            return io.BytesIO(json.dumps({'name': 'reference', 'file': 'input', 'format': file_format}).encode() if key == self.entry else original)

    import_root = tmp_path / 'import'
    import_root.mkdir()
    imported = import_structure(Call(inputs={'file': (FileInput(),)}, parameters={'models': 1}, settings={}), SimpleNamespace(workdir=import_root, cancelled=False))
    delivery = imported.outputs['structures'][0]
    class StructureInput:
        format = delivery.format
        entry = delivery.entry
        files = tuple(delivery.files)
        def open(self, key):
            return (import_root / delivery.files[key]).open('rb')

    _, package, _ = run(tmp_path, {'selection': {'chains': ['A']}}, StructureInput())
    before = read_document(package)
    assert len(before['positions']) == 56
    rows = before['positions']
    result, edited, root = run(tmp_path, {'operations': [
        {'kind': 'update', 'positions': [rows[1]['id'], rows[2]['id'], rows[3]['id']], 'changes': {'function_annotations': ['region']}},
        {'kind': 'delete', 'positions': [rows[2]['id']]},
        {'kind': 'update', 'positions': [rows[4]['id']], 'changes': {'residue': None}},
        {'kind': 'insert', 'index': 10, 'sequence': '_'},
    ]}, package)
    reopened = read_document(edited)
    assert len(reopened['positions']) == 57
    assert reopened['baseline'] == before['baseline']
    assert reopened['positions'][2]['deleted']
    assert reopened['positions'][4]['coordinates'] == before['positions'][4]['coordinates']
    manifest = json.loads((root / 'edited.json').read_text())
    assert len(manifest['positions']) == 56
    assert manifest['tracks']['function_annotations'] == [{'label': 'region', 'start': 2, 'end': 3}]
    assert manifest['tracks']['sequence'][3] is None
    assert manifest['tracks']['coordinates'][9] is None
    current = read_target((root / 'target.cif').read_bytes(), chain='A')['positions']
    assert len(current) == 56
    assert current[9]['atoms'] == {}
    assert current[3]['atoms'] == rows[4]['coordinates']
    retained_key = next(key for key in edited.files if key.endswith('original.pdb' if file_format == 'pdb' else 'original.cif'))
    with edited.open(retained_key) as reader:
        assert reader.read() == original
    for track in ['sequence', 'coordinates', 'secondary_structure', 'sasa', 'function_annotations']:
        obj = json.loads((root / result.outputs[track].entry).read_text())['objects'][0]
        assert [row['id'] for row in obj['positions']] == [row['id'] for row in manifest['positions']]
