"""Structure tasks through the installed module and persisted HTTP packages."""
import json

import gemmi
import pytest
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


def test_selected_rigid_transform_rotates_anisotropic_displacement_with_coordinates(tmp_path):
    from modules.structure_io import encode, parse, transform

    raw = gemmi.read_pdb_string(research())
    del raw[1]
    for chain in raw[0]:
        chain[0][0].aniso = gemmi.SMat33f(.01, .02, .03, .004, .005, .006)
    original = raw.make_mmcif_document().as_string().encode()
    source_file = tmp_path / 'source.cif'
    source_file.write_bytes(original)
    source = parse(source_file.read_bytes(), 'mmcif')
    rotation = [[0, -1, 0], [1, 0, 0], [0, 0, 1]]
    moved = transform(source, rotation, [10, 20, 30], {'chains': ['X']})
    def tensor(atom):
        return list(atom.aniso.elements_pdb())
    for encoding in ('mmcif', 'pdb'):
        actual = parse(encode(moved, encoding), encoding)
        assert list(actual[0]['X'][0][0].pos) == [8, 21, 33]
        assert tensor(actual[0]['X'][0][0]) == pytest.approx([.02, .01, .03, -.004, -.006, .005], abs=1e-7)
        assert list(actual[0]['M'][0][0].pos) == [7, 8, 9]
        assert tensor(actual[0]['M'][0][0]) == pytest.approx([.01, .02, .03, .004, .005, .006], abs=1e-7)
    translated = transform(source, [[1, 0, 0], [0, 1, 0], [0, 0, 1]], [3, 2, 1], {'chains': ['X']})
    assert tensor(translated[0]['X'][0][0]) == tensor(source[0]['X'][0][0])
    assert list(source[0]['X'][0][0].pos) == [1, 2, 3]
    assert tensor(source[0]['X'][0][0]) == pytest.approx([.01, .02, .03, .004, .005, .006])
    assert source_file.read_bytes() == original


def test_extracted_polymer_declares_only_selected_positions_for_independent_comparison(tmp_path):
    from tests.test_comparison import pdb

    original = b'SEQRES   1 X    5  ALA ALA ALA ALA ALA\n' + pdb()
    with TestClient(create_application(data_root=tmp_path)) as client:
        project = client.post('/api/projects', json={'name': 'Fragment sequence'}).json()['id']
        raw = upload(client, project, 'workbench.structure_file', {
            'manifest.json': json.dumps({'name': 'source.pdb', 'file': 'raw', 'format': 'pdb'}).encode(), 'raw': original,
        })
        imported_result = run(client, project, 'workbench.import_structure', {'file': [raw['id']]}, {'models': 1})
        source = imported_result['outputs']['structures'][0]
        obj = client.get(f'/api/packages/{source}/file', params={'key': 'manifest.json'}).json()['objects'][0]
        fragment = run(client, project, 'workbench.extract_structure', {'structures': [source]}, {
            'object': obj['id'], 'format': 'mmcif', 'selection': {'atoms': [0, 2, 4]},
        })
        assert fragment['status'] == 'succeeded', fragment
        package = fragment['outputs']['structures'][0]
        result = client.get(f'/api/packages/{package}/file', params={'key': 'manifest.json'}).json()['objects'][0]
        content = client.get(f'/api/packages/{package}/file', params={'key': result['structure']['file']}).content
        actual = gemmi.make_structure_from_block(gemmi.cif.read_string(content.decode()).sole_block())
        assert [list(entity.full_sequence) for entity in actual.entities] == [['ALA', 'ALA', 'ALA']]
        assert [str(residue.seqid) for residue in actual[0]['X']] == ['12', '14', '20']
        assert [residue.label_seq for residue in actual[0]['X']] == [1, 2, 3]
        compared = run(client, project, 'workbench.compare', {'subject': [package], 'reference': [package]}, {})
        assert compared['status'] == 'succeeded', compared
        assert client.get(f'/api/packages/{package}/file', params={'key': 'original.pdb'}).content == original
        converted = run(client, project, 'workbench.export_structure', {'structures': [source]}, {'object': obj['id'], 'format': 'mmcif'})
        output = converted['outputs']['structures'][0]
        full = client.get(f'/api/packages/{output}/file', params={'key': 'manifest.json'}).json()['objects'][0]
        content = client.get(f'/api/packages/{output}/file', params={'key': full['structure']['file']}).content
        full_structure = gemmi.make_structure_from_block(gemmi.cif.read_string(content.decode()).sole_block())
        assert [list(entity.full_sequence) for entity in full_structure.entities] == [['ALA'] * 5]


def test_selected_export_splits_shared_polymer_entities_and_preserves_other_components(tmp_path):
    from tests.test_comparison import pdb

    structure = gemmi.read_pdb_string(pdb())
    other = structure[0]['X'].clone()
    other.name = 'Y'
    structure[0].add_chain(other)
    polymer = gemmi.Entity('shared')
    polymer.entity_type = gemmi.EntityType.Polymer
    polymer.polymer_type = gemmi.PolymerType.PeptideL
    polymer.subchains = ['Xp', 'Yp']
    polymer.full_sequence = ['ALA'] * 5
    structure.entities.append(polymer)
    for chain_name in ('X', 'Y'):
        for index, residue in enumerate(structure[0][chain_name], 1):
            residue.subchain = chain_name + 'p'
            residue.entity_id = 'shared'
            residue.entity_type = gemmi.EntityType.Polymer
            residue.label_seq = index
    water = gemmi.Entity('water')
    water.entity_type = gemmi.EntityType.Water
    water.subchains = ['Ww']
    structure.entities.append(water)
    structure[0]['W'][0].subchain = 'Ww'
    structure[0]['W'][0].entity_id = 'water'
    structure[0]['W'][0].entity_type = gemmi.EntityType.Water
    original = structure.make_mmcif_document().as_string().encode()
    with TestClient(create_application(data_root=tmp_path)) as client:
        project = client.post('/api/projects', json={'name': 'Shared entity fragments'}).json()['id']
        raw = upload(client, project, 'workbench.structure_file', {
            'manifest.json': json.dumps({'name': 'shared.cif', 'file': 'raw', 'format': 'mmcif'}).encode(), 'raw': original,
        })
        result = run(client, project, 'workbench.import_structure', {'file': [raw['id']]}, {'models': 1})
        source = result['outputs']['structures'][0]
        obj = client.get(f'/api/packages/{source}/file', params={'key': 'manifest.json'}).json()['objects'][0]
        for encoding in ('mmcif', 'pdb'):
            exported = run(client, project, 'workbench.export_structure', {'structures': [source]}, {
                'object': obj['id'], 'format': encoding, 'atoms': [0, 2, 4, 5, 6, 7],
            })
            assert exported['status'] == 'succeeded', exported
            output = exported['outputs']['structures'][0]
            selected = client.get(f'/api/packages/{output}/file', params={'key': 'manifest.json'}).json()['objects'][0]
            content = client.get(f'/api/packages/{output}/file', params={'key': selected['structure']['file']}).content
            actual = gemmi.read_pdb_string(content) if encoding == 'pdb' else gemmi.make_structure_from_block(gemmi.cif.read_string(content.decode()).sole_block())
            polymers = [entity for entity in actual.entities if entity.entity_type == gemmi.EntityType.Polymer]
            assert sorted(len(entity.full_sequence) for entity in polymers) == [2, 3]
            assert [str(residue.seqid) for residue in actual[0]['X']] == ['12', '14', '20']
            assert [str(residue.seqid) for residue in actual[0]['Y']] == ['12', '12A']
            assert actual[0]['W'][0].name == 'HOH' and actual[0].count_atom_sites() == 6
            if encoding == 'mmcif':
                assert [residue.label_seq for residue in actual[0]['X']] == [1, 2, 3]
                assert [residue.label_seq for residue in actual[0]['Y']] == [1, 2]
                assert actual[0]['X'][0].entity_id != actual[0]['Y'][0].entity_id
                assert actual[0]['W'][0].entity_type == gemmi.EntityType.Water
            assert client.get(f'/api/packages/{output}/file', params={'key': 'original.cif'}).content == original
    assert list(structure.entities[0].full_sequence) == ['ALA'] * 5
    assert [residue.label_seq for residue in structure[0]['X']] == [1, 2, 3, 4, 5]


def test_fragment_keeps_microheterogeneous_components_at_one_local_sequence_position():
    from modules.structure_io import encode, extract, parse

    source = parse(research(), 'pdb')
    del source[1]
    first = source[0]['X'][0]
    first.entity_type = gemmi.EntityType.Polymer
    first.entity_id = 'polymer'
    first.subchain = 'Xp'
    first.label_seq = 4
    first[0].altloc = 'A'
    alternative = first.clone()
    alternative.name = 'SER'
    alternative[0].altloc = 'B'
    source[0]['X'].add_residue(alternative)
    entity = gemmi.Entity('polymer')
    entity.entity_type = gemmi.EntityType.Polymer
    entity.polymer_type = gemmi.PolymerType.PeptideL
    entity.subchains = ['Xp']
    entity.full_sequence = ['GLY', 'GLY', 'GLY', 'ALA,SER']
    source.entities.append(entity)
    fragment = extract(source, {'chains': ['X']})
    actual = parse(encode(fragment, 'mmcif'), 'mmcif')
    assert list(actual.entities[0].full_sequence) == ['ALA,SER']
    assert [(residue.name, str(residue.seqid), residue.label_seq, residue[0].altloc) for residue in actual[0]['X']] == [
        ('ALA', '12A', 1, 'A'), ('SER', '12A', 1, 'B'),
    ]
    assert list(source.entities[0].full_sequence) == ['GLY', 'GLY', 'GLY', 'ALA,SER']
    assert source[0]['X'][0].label_seq == 4


def test_extract_rejects_unbound_mmcif_polymer_declaration_without_guessing_membership():
    from modules.structure_io import extract, parse
    from tests.test_comparison import pdb

    source = gemmi.read_pdb_string(b'SEQRES   1 X    5  ALA ALA ALA ALA ALA\n' + pdb())
    source.entities[0].name = 'unbound'
    actual = parse(source.make_mmcif_document().as_string().encode(), 'mmcif')
    with pytest.raises(ValueError, match='cannot associate an unbound polymer entity'):
        extract(actual, {'atoms': [0, 1, 2]})
    assert list(actual.entities[0].full_sequence) == ['ALA'] * 5


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
