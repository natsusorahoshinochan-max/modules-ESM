"""User-visible structure-to-template and complete target file handoff."""
import json
import gemmi
from fastapi.testclient import TestClient
from protein_workbench_public.bootstrap import create_application
from modules.structure_io.target import read_target, write_target
from tests.test_sequence_io import upload
from tests.test_editor_interactions import preview


def test_complete_target_retains_insertions_without_atoms_and_actual_author_numbers():
    target = write_target([
        {'residue':'A', 'author_number':12, 'insertion_code':'A', 'author_chain':'X', 'atoms':{'N':[1,2,3], 'CA':[4,5,6]}},
        {'residue':'_', 'atoms':{}},
        {'residue':'C', 'author_number':30, 'author_chain':'X', 'atoms':{'CA':[7,8,9]}},
    ])
    actual = read_target(target)
    assert actual['sequence'] == 'AXC'
    assert [row['author_number'] for row in actual['positions']] == [12, None, 30]
    assert actual['positions'][0]['insertion_code'] == 'A'
    assert actual['positions'][1]['atoms'] == {}
    # Independent standard mmCIF reader sees the whole polymer and only real atoms.
    block = gemmi.cif.read_string(target.decode()).sole_block()
    assert list(block.find_values('_entity_poly_seq.num')) == ['1','2','3']
    assert list(block.find_values('_atom_site.label_seq_id')) == ['1','1','3']
    assert list(block.find_values('_atom_site.auth_seq_id')) == ['12','12','30']


def test_structure_regions_build_edit_and_reopen_without_manual_mapping(tmp_path):
    pdb = (b'ATOM      1  N   ALA X  12A      1.000   2.000   3.000  1.00 80.00           N  \n'
           b'ATOM      2  CA  ALA X  12A      2.000   2.000   3.000  1.00 80.00           C  \n'
           b'ATOM      3  CA  GLY X  13       4.000   2.000   3.000  1.00 80.00           C  \n'
           b'ATOM      4  CA  CYS X  30       7.000   8.000   9.000  1.00 80.00           C  \n'
           b'HETATM    5 ZN    ZN M  -2       7.000   8.000   9.000  1.00 20.00          ZN  \nEND\n')
    with TestClient(create_application(data_root=tmp_path)) as client:
        project = client.post('/api/projects', json={'name':'Structure template'}).json()['id']
        source = upload(client, project, 'workbench.structure_set', {'manifest.json':json.dumps({'objects':[{'id':'actual','structure':{'file':'original.pdb','format':'pdb'}}]}).encode(), 'original.pdb':pdb})
        token, initial = preview(client, project, {'object':'actual','selection':{'chains':['X']},'regions':'12A,30','tracks':['coordinates'],'atoms':['CA']}, {'source':[source['id']]})
        assert initial['sequence'] == 'AC'
        assert all(row['prompt'] == '_' for row in initial['positions'])
        assert [row['coordinates'] for row in initial['positions']] == [{'CA':[2,2,3]},{'CA':[7,8,9]}]
        assert initial['positions'][0]['_target_atoms']['N'] == [1,2,3]
        accepted = client.post(f'/api/interactions/{token}/accept',json={'output':'edited'}).json()
        token, edited = preview(client, project, {'operation':{'kind':'insert','index':1,'sequence':'__'}}, {'source':[accepted['id']]})
        second = client.post(f'/api/interactions/{token}/accept',json={'output':'edited'}).json()
        token, deleted = preview(client, project, {'operation':{'kind':'delete','positions':[edited['positions'][2]['id']]}}, {'source':[second['id']]})
        final = client.post(f'/api/interactions/{token}/accept',json={'output':'edited'}).json()
        entry = client.get(f"/api/packages/{final['id']}/file",params={'key':'edited.json'}).json()
        assert all('coordinates' not in row for row in entry['positions'])
        assert entry['conditions']['coordinates'] == [{'position':1,'atoms':['CA']},{'position':3,'atoms':['CA']}]
        actual = read_target(client.get(f"/api/packages/{final['id']}/file",params={'key':entry['target']['file']}).content)
        assert actual['sequence'] == 'AXC'
        assert actual['positions'][0]['atoms']['N'] == [1,2,3]
        assert actual['positions'][1]['atoms'] == {}
        assert actual['positions'][2]['author_number'] == 30
        original = entry['structures'][0]['files']['original.pdb']
        assert client.get(f"/api/packages/{final['id']}/file",params={'key':original}).content == pdb
        target_project = client.post('/api/projects',json={'name':'Independent'}).json()['id']
        copied = client.post(f'/api/projects/{target_project}/adoptions',json={'package_id':final['id']}).json()
        client.delete(f'/api/projects/{project}').raise_for_status()
        _, reopened = preview(client, target_project, {}, {'source':[copied['id']]})
        assert reopened == deleted


def test_reusable_template_recipe_uses_each_new_objects_current_positions(tmp_path):
    from tests.fixtures.sequence_conditions import condition_files
    from tests.test_structure_conditions import PDB
    with TestClient(create_application(data_root=tmp_path)) as client:
        project = client.post('/api/projects',json={'name':'Repeated template recipe'}).json()['id']
        # Both independent objects have fresh package/object/edit identities.
        results = []
        recipe = {'selection':{'chains':['X']},'tracks':[],
                  'operations':[{'kind':'insert','index':1,'sequence':'__'}, {'kind':'delete','indices':[3]}],
                  'template_conditions':{'fixed_positions':[1], 'coordinate_positions':[1], 'atoms':['CA']}}
        for identity in ('first', 'second'):
            package = upload(client,project,'workbench.structure_set',{'manifest.json':json.dumps({'objects':[{'id':identity,'structure':{'file':'model.pdb','format':'pdb'}}]}).encode(),'model.pdb':PDB})
            token, document = preview(client,project,recipe,{'source':[package['id']]})
            result = client.post(f'/api/interactions/{token}/accept',json={'output':'edited'}).json()
            manifest = client.get(f"/api/packages/{result['id']}/file",params={'key':'edited.json'}).json()
            assert document['sequence'] == 'A_'
            assert manifest['conditions'] == {'sequence':[{'position':1,'residue':'A'}], 'coordinates':[{'position':1,'atoms':['CA']}]}
            assert document['positions'][1]['coordinates'] is None
            results.append(document)
        assert results[0]['id'] != results[1]['id']
        assert {row['id'] for row in results[0]['positions']}.isdisjoint(row['id'] for row in results[1]['positions'])


def test_complete_source_mmcif_keeps_unobserved_polymer_positions(tmp_path):
    content = write_target([
        {'residue':'A','author_number':12,'author_chain':'X','atoms':{'CA':[1,2,3]}},
        {'residue':'G','author_number':13,'author_chain':'X','atoms':{}},
        {'residue':'C','author_number':30,'author_chain':'X','atoms':{'CA':[7,8,9]}},
    ])
    with TestClient(create_application(data_root=tmp_path)) as client:
        project = client.post('/api/projects',json={'name':'Unobserved polymer positions'}).json()['id']
        package = upload(client,project,'workbench.structure_set',{'manifest.json':json.dumps({'objects':[{'id':'complete','structure':{'file':'model.cif','format':'mmcif'}}]}).encode(),'model.cif':content})
        token, document = preview(client,project,{'selection':{'chains':['X']}},{'source':[package['id']]})
        assert document['sequence'] == 'AGC'
        assert document['positions'][1]['coordinates'] is None
        assert document['positions'][1]['target_author']['author_number'] == 13
        assert document['positions'][1]['source']['label_position'] == {'chain':'A','position':2}
        result = client.post(f'/api/interactions/{token}/accept',json={'output':'edited'}).json()
        target = read_target(client.get(f"/api/packages/{result['id']}/file",params={'key':'target.cif'}).content)
        assert target['positions'][1]['atoms'] == {}
        assert target['sequence'] == 'AGC'


def test_import_transform_and_full_export_preserve_unobserved_author_regions(tmp_path):
    from tests.test_structure_io import run
    content = write_target([
        {'residue':'A','author_number':12,'author_chain':'X','atoms':{'CA':[1,2,3]}},
        {'residue':'G','author_number':13,'author_chain':'X','atoms':{}},
        {'residue':'C','author_number':30,'author_chain':'X','atoms':{'CA':[7,8,9]}},
    ])
    with TestClient(create_application(data_root=tmp_path)) as client:
        project = client.post('/api/projects',json={'name':'Import complete correspondence'}).json()['id']
        uploaded = upload(client,project,'workbench.structure_file',{'manifest.json':json.dumps({'name':'complete.cif','file':'raw.cif','format':'mmcif'}).encode(),'raw.cif':content})
        imported = run(client,project,'workbench.import_structure',{'file':[uploaded['id']]},{'models':'all'})
        assert imported['status'] == 'succeeded'
        current = imported['outputs']['structures'][0]
        for operation in (None, 'workbench.transform_structure', 'workbench.export_structure'):
            obj = client.get(f'/api/packages/{current}/file',params={'key':'manifest.json'}).json()['objects'][0]
            if operation:
                parameters = {'object':obj['id'],'format':'mmcif'}
                if operation == 'workbench.transform_structure':
                    parameters.update(rotation=[[1,0,0],[0,1,0],[0,0,1]],translation=[3,0,0])
                outcome = run(client,project,operation,{'structures':[current]},parameters)
                assert outcome['status'] == 'succeeded', outcome
                current = outcome['outputs']['structures'][0]
            token, document = preview(client,project,{'selection':{'chains':['X']},'regions':'13','tracks':[]},{'source':[current]})
            assert document['sequence'] == 'G'
            assert document['positions'][0]['target_author']['author_number'] == 13
            assert document['positions'][0]['coordinates'] is None
            client.delete(f'/api/interactions/{token}').raise_for_status()
