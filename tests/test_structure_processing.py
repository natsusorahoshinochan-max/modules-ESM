"""Structure tasks through the installed module and persisted HTTP packages."""
import json

import gemmi
from fastapi.testclient import TestClient
from protein_workbench_public.bootstrap import create_application
from tests.test_sequence_io import upload
from tests.test_structure_io import research, run


def imported(client, project):
    raw = upload(client, project, 'workbench.structure_file', {
        'manifest.json': json.dumps({'name': 'research.pdb', 'file': 'raw', 'format': 'pdb'}).encode(),
        'raw': research(),
    })
    result = run(client, project, 'workbench.import_structure', {'file': [raw['id']]}, {'models': 7})
    package = result['outputs']['structures'][0]
    obj = client.get(f'/api/packages/{package}/file', params={'key': 'manifest.json'}).json()['objects'][0]
    return package, obj


def test_extract_real_discontinuous_positions_convert_transform_and_reopen(tmp_path):
    with TestClient(create_application(data_root=tmp_path)) as client:
        project = client.post('/api/projects', json={'name': 'Coordinates'}).json()['id']
        original, obj = imported(client, project)
        selection = {'positions': [
            {'chain': 'X', 'author_number': 12, 'insertion_code': 'A'},
            {'chain': 'M', 'author_number': -2, 'insertion_code': ''},
        ]}
        extracted = run(client, project, 'workbench.extract_structure', {'structures': [original]},
                        {'object': obj['id'], 'selection': selection, 'format': 'mmcif'})
        assert extracted['status'] == 'succeeded', extracted
        package = extracted['outputs']['structures'][0]
        fragment = client.get(f'/api/packages/{package}/file', params={'key': 'manifest.json'}).json()['objects'][0]
        result = run(client, project, 'workbench.transform_structure', {'structures': [package]}, {
            'object': fragment['id'], 'selection': {'chains': ['X']}, 'format': 'pdb',
            'rotation': [[0, -1, 0], [1, 0, 0], [0, 0, 1]], 'translation': [10, 20, 30],
        })
        assert result['status'] == 'succeeded', result
        transformed = result['outputs']['structures'][0]
    with TestClient(create_application(data_root=tmp_path)) as client:
        def read(package, key):
            return client.get(f'/api/packages/{package}/file', params={'key': key}).content
        output = json.loads(read(transformed, 'manifest.json'))['objects'][0]
        coordinates = gemmi.read_pdb_string(read(transformed, output['structure']['file']))
        assert coordinates[0].num == 7
        assert coordinates[0].count_atom_sites() == 2
        assert list(coordinates[0]['X'][0][0].pos) == [8, 21, 33]
        assert list(coordinates[0]['M'][0][0].pos) == [7, 8, 9]
        assert str(coordinates[0]['X'][0].seqid) == '12A'
        assert read(transformed, 'original.pdb') == research()
        assert json.loads(read(original, obj['atoms']))[0]['position'] == [1, 2, 3]
        assert output['operation']['kind'] == 'transform'
        assert output['operation']['selection'] == {'chains': ['X']}
        assert fragment['operation']['selection'] == selection


def test_public_operations_resolve_altloc_components_and_leave_input_unchanged():
    from modules.structure_io import atoms, extract, parse, positions, resolve_selection, transform

    structure = parse(research(), 'pdb')
    # Public position selection identifies model as well as author residue identity.
    selection = {'positions': [{'model': 9, 'chain': 'X', 'author_number': 12, 'insertion_code': 'A'}]}
    assert resolve_selection(structure, selection) == [5]
    assert positions(structure)[5] == {
        'model': 9, 'chain': 'X', 'author_number': 12, 'insertion_code': 'A', 'residue_name': 'ALA',
        'atoms': [{'index': 5, 'name': 'CA', 'altloc': '', 'position': [2, 2, 3]}],
    }
    fragment = extract(structure, selection)
    assert len(fragment) == 1 and fragment[0].num == 9
    moved = transform(fragment, [[1, 0, 0], [0, 1, 0], [0, 0, 1]], [-1, 4, 0])
    assert atoms(moved)[0]['position'] == [1, 6, 3]
    assert atoms(fragment)[0]['position'] == [2, 2, 3]
    assert atoms(structure)[5]['position'] == [2, 2, 3]


def test_invalid_selections_and_nonrigid_transforms_fail_with_source_available(tmp_path):
    with TestClient(create_application(data_root=tmp_path)) as client:
        project = client.post('/api/projects', json={'name': 'No repairs'}).json()['id']
        original, obj = imported(client, project)
        for selection in ({'positions': [{'chain': 'X', 'author_number': 12, 'insertion_code': ''}]},
                          {'chains': ['X', 'missing']}, {'atoms': [0, 500]}, {'atoms': []}):
            result = run(client, project, 'workbench.extract_structure', {'structures': [original]},
                         {'object': obj['id'], 'format': 'mmcif', 'selection': selection})
            assert result['status'] == 'failed' and not result.get('outputs'), result
        result = run(client, project, 'workbench.transform_structure', {'structures': [original]}, {
            'object': obj['id'], 'format': 'mmcif', 'rotation': [[2, 0, 0], [0, 1, 0], [0, 0, 1]], 'translation': [0, 0, 0],
        })
        assert result['status'] == 'failed' and 'orthonormal' in str(result['diagnostics']), result
        assert client.get(f'/api/packages/{original}/file', params={'key': 'original.pdb'}).content == research()


def test_public_reader_uses_only_declared_package_files_and_preserves_alternate_atoms(tmp_path):
    from modules.structure_io import atoms, encode, extract, parse, read_structure, resolve_selection, transform

    coordinate = parse(research(), 'pdb')
    del coordinate[1]
    residue = coordinate[0]['X'][0]
    residue[0].altloc = 'A'
    alternate = residue[0].clone()
    alternate.altloc = 'B'
    alternate.pos.x = 5
    residue.add_atom(alternate)
    (tmp_path / 'coordinates.cif').write_bytes(encode(coordinate, 'mmcif'))
    (tmp_path / 'entry.json').write_text(json.dumps({'objects': [
        {'id': 'selected', 'structure': {'file': 'coordinates.cif', 'format': 'mmcif'}},
    ]}))

    class Files:
        entry = 'entry.json'
        format = 'workbench.structure_set'

        def open(self, key):
            return (tmp_path / key).open('rb')

    actual = read_structure(Files(), 'selected')
    selection = {'positions': [{'chain': 'X', 'author_number': 12, 'insertion_code': 'A'}]}
    assert resolve_selection(actual, selection) == [0, 1]
    fragment = extract(actual, selection)
    moved = transform(fragment, [[1, 0, 0], [0, 1, 0], [0, 0, 1]], [1, 0, 0])
    assert [(a['altloc'], a['position']) for a in atoms(moved)] == [('A', [2, 2, 3]), ('B', [6, 2, 3])]
    assert [a['residue_name'] for a in atoms(actual)] == ['ALA', 'ALA', 'LIG', 'ZN', 'HOH', 'DA']
