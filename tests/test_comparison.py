import json

import gemmi
import numpy as np
import pytest
from fastapi.testclient import TestClient

from protein_workbench_public.bootstrap import create_application


POINTS = [(0, 0, 0), (3, 0, 0), (3, 4, 0), (3, 4, 5), (1, 2, 6)]


def pdb(points=POINTS, *, missing_ca=False, extra_chain=False):
    lines = []
    for index, (x, y, z) in enumerate(points):
        number, insertion = [(12, ' '), (12, 'A'), (14, ' '), (16, ' '), (20, ' ')][index]
        atom = 'N' if missing_ca and index == 2 else 'CA'
        lines.append(f'ATOM  {index+1:5d} {atom:^4s} ALA X{number:4d}{insertion}   {x:8.3f}{y:8.3f}{z:8.3f}  1.00 80.00           C  ')
    lines.append('HETATM    8  O   HOH W   3      10.000  11.000  12.000  1.00 20.00           O  ')
    if extra_chain:
        lines.append('ATOM     10  CA  ALA Y   1       1.000   2.000   3.000  1.00 80.00           C  ')
    return ('\n'.join(lines) + '\nEND\n').encode()


def upload(client, project, format, manifest, content, key):
    base = f'/api/projects/{project}/uploads'
    base += '/' + client.post(base).json()['upload_id']
    for name, data in {'manifest.json': json.dumps(manifest).encode(), key: content}.items():
        assert client.put(base + '/files', params={'key': name}, content=data).status_code == 200
    response = client.post(base + '/commit', json={'format': format, 'entry': 'manifest.json', 'files': {'manifest.json': 'manifest.json', key: key}})
    assert response.status_code == 200, response.text
    return response.json()


def inputs(client, project, content=None, sequence='AAAAA'):
    subject = upload(client, project, 'workbench.prediction', {'objects': [{'id': 'predicted-object', 'sequence': sequence, 'structure': {'file': 'subject.pdb', 'format': 'pdb'}}], 'tool': {'id': 'other.producer', 'parameters': {'seed': 0}}}, content or pdb(), 'subject.pdb')
    reference_pdb = pdb([(10-y, 20+x, 30+z) for x, y, z in POINTS])
    reference_cif = gemmi.read_pdb_string(reference_pdb).make_mmcif_document().as_string().encode()
    reference = upload(client, project, 'workbench.reference', {'objects': [{'id': 'independent-reference', 'label': 'Unrelated reference', 'structure': {'file': 'reference.cif', 'format': 'mmcif'}}]}, reference_cif, 'reference.cif')
    return subject, reference, reference_cif


def run(client, project, subject, reference):
    response = client.put(f'/api/projects/{project}', json={'flow': {'nodes': [{'id': 'compare', 'type': 'workbench.compare', 'inputs': {'subject': [subject['id']], 'reference': [reference['id']]}}], 'edges': []}, 'layout': {}})
    assert response.status_code == 200, response.text
    response = client.post(f'/api/projects/{project}/runs')
    assert response.status_code == 200, response.text
    return response.json()


def test_independent_comparison_persists_complete_reopenable_overlay(tmp_path):
    with TestClient(create_application(data_root=tmp_path)) as client:
        # No producer module available: only public prediction bytes are needed.
        assert client.delete('/api/modules/workbench.prediction').status_code == 200
        project = client.post('/api/projects', json={'name': 'Comparison'}).json()['id']
        subject, reference, reference_cif = inputs(client, project)
        result = run(client, project, subject, reference)
        assert result['status'] == 'succeeded', result
        output_id = result['nodes']['compare']['outputs']['comparison'][0]
    with TestClient(create_application(data_root=tmp_path)) as client:
        def read(key):
            response = client.get(f'/api/packages/{output_id}/file', params={'key': key})
            assert response.status_code == 200
            return response.content
        manifest = json.loads(read('manifest.json'))
        assert manifest['subject']['id'] == 'predicted-object'
        assert manifest['subject']['generation']['tool']['id'] == 'other.producer'
        assert manifest['reference']['id'] == 'independent-reference'
        assert read(manifest['subject']['structure']['file']) == pdb()
        assert read(manifest['reference']['structure']['file']) == reference_cif
        assert manifest['method']['name'] == 'TM-align'
        assert manifest['metrics']['tm_subject']['value'] == pytest.approx(1)
        assert manifest['metrics']['tm_reference']['value'] == pytest.approx(1)
        assert manifest['metrics']['rmsd']['value'] == pytest.approx(0, abs=1e-5)
        assert manifest['metrics']['rmsd']['aligned_pair_count'] == 5
        assert manifest['metrics']['tm_subject']['normalization_length'] == 5
        assert manifest['alignment']['subject_positions'][1] == {'chain': 'X', 'author_number': 12, 'insertion_code': 'A'}
        transform = manifest['transform']
        assert np.asarray(POINTS) @ np.asarray(transform['rotation']).T + transform['translation'] == pytest.approx(np.array([(10,20,30),(10,23,30),(6,23,30),(6,23,35),(8,21,36)]), abs=1e-5)
        overlay = json.loads(read(manifest['overlay']))
        assert len(overlay['subject']) == 6
        assert overlay['subject'][-1]['residue_name'] == 'HOH'
        assert overlay['reference'][-1]['residue_name'] == 'HOH'
        assert overlay['subject'][0]['position'] == pytest.approx([10,20,30])


@pytest.mark.parametrize(('content', 'sequence', 'diagnostic'), [
    (pdb(missing_ca=True), 'AAAAA', 'unambiguous CA'),
    (pdb(extra_chain=True), 'AAAAA', 'exactly one protein chain'),
    (pdb(), 'AAAAAA', 'residue correspondence disagree'),
    (b'SEQRES   1 X    6  ALA ALA ALA ALA ALA ALA\n' + pdb(), 'AAAAA', 'unresolved polymer residues'),
])
def test_invalid_scientific_input_is_saved_but_comparison_fails_without_changing_inputs(tmp_path, content, sequence, diagnostic):
    with TestClient(create_application(data_root=tmp_path)) as client:
        project = client.post('/api/projects', json={'name': 'Invalid comparison'}).json()['id']
        subject, reference, _ = inputs(client, project, content, sequence)
        result = run(client, project, subject, reference)
        assert result['status'] == 'failed', result
        node = result['nodes']['compare']
        assert diagnostic in ' '.join(node['diagnostics'])
        assert not node['outputs']
        response = client.get(f"/api/packages/{subject['id']}/file", params={'key': 'subject.pdb'})
        assert response.content == content


def test_tmalign_reports_both_length_normalizations_and_full_gapped_position_axes(tmp_path):
    with TestClient(create_application(data_root=tmp_path)) as client:
        project = client.post('/api/projects', json={'name': 'Unequal lengths'}).json()['id']
        subject, _, _ = inputs(client, project)
        reference = upload(client, project, 'workbench.reference', {'objects': [{'id': 'short-reference', 'structure': {'file': 'reference.pdb', 'format': 'pdb'}}]}, pdb(POINTS[:4]), 'reference.pdb')
        result = run(client, project, subject, reference)
        assert result['status'] == 'succeeded', result
        identifier = result['nodes']['compare']['outputs']['comparison'][0]
        manifest = client.get(f'/api/packages/{identifier}/file', params={'key': 'manifest.json'}).json()
        assert manifest['metrics']['tm_subject']['value'] == pytest.approx(0.8)
        assert manifest['metrics']['tm_reference']['value'] == pytest.approx(1)
        assert manifest['metrics']['tm_reference']['normalization_length'] == 4
        assert manifest['alignment']['subject_sequence'] == 'AAAAA'
        assert manifest['alignment']['reference_sequence'] == 'AAAA-'
        assert manifest['alignment']['reference_positions'][-1] is None
        assert len(manifest['alignment']['subject_positions']) == 5


def test_consumer_runs_when_importing_producer_and_legacy_scientific_packages_is_denied(tmp_path, monkeypatch):
    import builtins
    from core.host import Workbench
    from protein_workbench_public.http.app import create_http_app

    original = builtins.__import__
    def independent_import(name, *args, **kwargs):
        if name.startswith(('modules.folding', 'datatypes', 'core.catalog', 'core.execution')):
            raise ImportError('Producer and legacy scientific packages are unavailable')
        return original(name, *args, **kwargs)
    monkeypatch.setattr(builtins, '__import__', independent_import)
    app = Workbench(tmp_path)
    app.install('modules.structure_comparison:module')
    with TestClient(create_http_app(app)) as client:
        project = client.post('/api/projects', json={'name': 'Independent consumer'}).json()['id']
        subject, reference, _ = inputs(client, project)
        result = run(client, project, subject, reference)
        assert result['status'] == 'succeeded', result


@pytest.mark.parametrize('chain', ['X', 'L'])
def test_nonpolymer_amino_acid_ligands_are_preserved_without_entering_protein_alignment(tmp_path, chain):
    content = pdb().replace(b'HOH W', f'GLY {chain}'.encode())
    with TestClient(create_application(data_root=tmp_path)) as client:
        project = client.post('/api/projects', json={'name': 'Free amino acid ligand'}).json()['id']
        subject, reference, _ = inputs(client, project, content)
        result = run(client, project, subject, reference)
        assert result['status'] == 'succeeded', result
        identifier = result['nodes']['compare']['outputs']['comparison'][0]
        overlay = client.get(f'/api/packages/{identifier}/file', params={'key': 'overlay.json'}).json()
        assert overlay['subject'][-1]['residue_name'] == 'GLY'
        assert overlay['subject'][-1]['component'] == 'other'
        manifest = client.get(f'/api/packages/{identifier}/file', params={'key': 'manifest.json'}).json()
        assert manifest['metrics']['tm_subject']['normalization_length'] == 5
        assert manifest['metrics']['tm_subject']['value'] == pytest.approx(1)


def test_unknown_residue_in_declared_mmcif_protein_polymer_stops_comparison(tmp_path):
    structure = gemmi.read_pdb_string(pdb())
    structure.setup_entities()
    structure[0][0][2].name = 'XYZ'
    structure[0][0][2].het_flag = 'H'
    content = structure.make_mmcif_document().as_string().encode()
    with TestClient(create_application(data_root=tmp_path)) as client:
        project = client.post('/api/projects', json={'name': 'Unknown polymer residue'}).json()['id']
        subject, _, _ = inputs(client, project)
        reference = upload(client, project, 'workbench.reference', {'objects': [{'id': 'modified-reference', 'structure': {'file': 'reference.cif', 'format': 'mmcif'}}]}, content, 'reference.cif')
        result = run(client, project, subject, reference)
        assert result['status'] == 'failed', result
        assert 'Unsupported protein residue XYZ' in ' '.join(result['nodes']['compare']['diagnostics'])
        assert not result['nodes']['compare']['outputs']
