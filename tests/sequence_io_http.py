"""Real HTTP/persistence bridge for the public module React action test."""
import base64
import io
import json
from pathlib import Path
import sys
import tempfile
import zipfile

from fastapi.testclient import TestClient
from protein_workbench_public.bootstrap import create_application
from tests.run_helpers import wait_response
from tests.test_sequence_io import upload


def exercise(value):
    files = {key: base64.b64decode(content) for key, content in value['files'].items()}
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        with TestClient(create_application(data_root=root)) as client:
            project = client.post('/api/projects', json={'name': 'Imported related results'}).json()['id']
            package = upload(client, project, value['format'], files, value['entry'])
            # An independent consumer reads the actual files with no producer installed.
            client.delete('/api/modules/workbench.prediction').raise_for_status()
            reference = upload(client, project, 'workbench.reference', {
                'manifest.json': json.dumps({'objects': [{'id': 'independent', 'structure': {'file': 'ref.pdb', 'format': 'pdb'}}]}).encode(),
                'ref.pdb': files['nested/model.pdb'],
            })
            flow = {'nodes': [{'id': 'compare', 'type': 'workbench.compare', 'inputs': {'subject': [package['id']], 'reference': [reference['id']]}},
                              {'id': 'convert', 'type': 'workbench.prediction_to_structure', 'inputs': {'prediction': [package['id']]}}], 'edges': []}
            client.put(f'/api/projects/{project}', json={'flow': flow, 'layout': {'x': 7}}).raise_for_status()
            result = wait_response(client, client.post(f'/api/projects/{project}/runs')).json()
            assert result['status'] == 'succeeded', result
            output = result['nodes']['compare']['outputs']['comparison'][0]
            converted = result['nodes']['convert']['outputs']['structure'][0]
        with TestClient(create_application(data_root=root)) as client:
            assert client.get(f'/api/projects/{project}').json()['flow'] == flow
            comparison = client.get(f'/api/packages/{output}/file', params={'key': 'manifest.json'}).json()
            converted_manifest = client.get(f'/api/packages/{converted}/file', params={'key': 'manifest.json'}).json()
            archive = client.get(f"/api/packages/{package['id']}/export.zip")
            archive.raise_for_status()
            with zipfile.ZipFile(io.BytesIO(archive.content)) as zipped:
                index = json.loads(zipped.read('package.json'))
                exported = {item['key']: base64.b64encode(zipped.read(item['member'])).decode() for item in index['files']}
            return {'package': package, 'comparison': comparison, 'converted': converted_manifest, 'files': exported, 'index': index}


if __name__ == '__main__':
    print(json.dumps(exercise(json.load(sys.stdin))))
