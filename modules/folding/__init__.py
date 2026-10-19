"""Sequence prediction through a public replaceable tool slot."""
import json
import math
from pathlib import Path
from uuid import uuid4

from protein_workbench_public.module_api import Delivery, InputPort, Module, Node, Outcome, OutputPort, ToolSlot
from .contract import PredictionRequest, PredictionResult


def execute(call, runtime):
    package = call.inputs['sequence'][0]
    with package.open(package.entry) as stream:
        document = json.load(stream)
    if not isinstance(document, dict) or set(document) != {'objects'} or not isinstance(document['objects'], list) or len(document['objects']) != 1:
        raise ValueError('Prediction requires exactly one sequence object')
    source = document['objects'][0]
    if not isinstance(source, dict) or set(source) - {'id', 'sequence', 'label'}:
        raise ValueError('Prediction accepts a protein sequence only; unsupported components or conditions')
    sequence = source.get('sequence')
    if not isinstance(sequence, str) or not sequence or any(residue not in 'ACDEFGHIKLMNPQRSTVWY' for residue in sequence):
        raise ValueError('Prediction requires an unmodified canonical protein sequence')
    if not isinstance(source.get('id'), str) or not source['id']:
        raise ValueError('Sequence object id is required')
    if call.parameters:
        raise ValueError('Unknown prediction node parameters; configure the selected tool')
    if runtime.cancelled:
        return Outcome(status='cancelled')
    parameters = call.tool_parameters.get('predictor', {})
    if not isinstance(parameters, dict):
        raise ValueError('Predictor parameters must be an object')
    result = call.tools['predictor'](PredictionRequest(sequence, source['id']), parameters, runtime)
    if runtime.cancelled:
        return Outcome(status='cancelled')
    if not isinstance(result, PredictionResult) or result.structure_format not in ('pdb', 'mmcif'):
        raise ValueError('Prediction tool must return a PDB or mmCIF structure')
    path = Path(result.structure_path)
    if path.is_absolute() or not (runtime.workdir / path).resolve().is_relative_to(runtime.workdir.resolve()) or not (runtime.workdir / path).is_file():
        raise ValueError('Prediction structure must be a completed file inside runtime.workdir')
    structure_key = 'structure.pdb' if result.structure_format == 'pdb' else 'structure.cif'
    encoded = runtime.workdir / uuid4().hex
    encoded.mkdir()
    relative = encoded.relative_to(runtime.workdir)
    files = {'manifest.json': str(relative / 'manifest.json'), structure_key: str(path)}
    obj = {'id': uuid4().hex, 'sequence': sequence, 'structure': {'file': structure_key, 'format': result.structure_format}}
    if 'label' in source:
        obj['label'] = source['label']
    confidence = {}
    if result.plddt is not None:
        if len(result.plddt) != len(sequence) or any(isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= 1 for value in result.plddt):
            raise ValueError('Prediction pLDDT must contain one finite 0–1 value per sequence residue')
        (encoded / 'confidence.json').write_text(json.dumps({'plddt': result.plddt}, allow_nan=False))
        files['confidence.json'] = str(relative / 'confidence.json')
        confidence['plddt'] = {'file': 'confidence.json', 'scale': '0-1'}
    if result.ptm is not None:
        if not math.isfinite(result.ptm) or not 0 <= result.ptm <= 1:
            raise ValueError('Prediction pTM must be a finite 0–1 value')
        confidence['ptm'] = result.ptm
    if confidence:
        obj['confidence'] = confidence
    if result.extras:
        (encoded / 'supplementary.json').write_text(json.dumps(result.extras, allow_nan=False))
        files['supplementary.json'] = str(relative / 'supplementary.json')
        obj['supplementary'] = {'file': 'supplementary.json'}
    manifest = {'objects': [obj], 'tool': {'id': call.tool_choices['predictor'], 'parameters': parameters}}
    (encoded / 'manifest.json').write_text(json.dumps(manifest, allow_nan=False))
    return Outcome(outputs={'structure': [Delivery('workbench.prediction', 'manifest.json', files)]})


def module():
    from .adapters import tools
    return Module(id='workbench.prediction', name='Structure prediction', nodes=(Node(id='workbench.predict', name='Predict structure', execute=execute, inputs={'sequence': InputPort(('workbench.sequence',))}, outputs={'structure': OutputPort('workbench.prediction')}, tools={'predictor': ToolSlot('workbench.predict.structure', 'Structure predictor')}),), tools=tools(), settings={'python': 'Existing Python executable with pinned ESMFold2 dependencies', 'model_path': 'Existing ESMFold2 snapshot directory', 'language_model_path': 'Existing ESMC snapshot directory', 'device': 'cpu, mps or cuda', 'service_url': 'Biohub URL, default https://biohub.ai', 'token': {'type': 'string', 'title': 'Biohub credential', 'secret': True}}, ui=str(Path(__file__).with_name('ui.js').resolve()))
