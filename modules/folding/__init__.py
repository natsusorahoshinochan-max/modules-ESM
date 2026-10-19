"""Sequence prediction through a public replaceable tool slot."""
import json
import math
import shutil
from copy import deepcopy
from pathlib import Path
from uuid import uuid4

from protein_workbench_public.module_api import Delivery, InputPort, Module, Node, Outcome, OutputPort, ToolSlot
from .contract import PredictionRequest, PredictionResult


def _encode_result(result, source, runtime, prefix):
    sequence = source['sequence']
    if not isinstance(result, PredictionResult) or result.structure_format not in ('pdb', 'mmcif'):
        raise ValueError('Prediction tool must return a PDB or mmCIF structure')
    path = Path(result.structure_path)
    if path.is_absolute() or not (runtime.workdir / path).resolve().is_relative_to(runtime.workdir.resolve()) or not (runtime.workdir / path).is_file():
        raise ValueError('Prediction structure must be a completed file inside runtime.workdir')
    structure_key = prefix + ('structure.pdb' if result.structure_format == 'pdb' else 'structure.cif')
    encoded = runtime.workdir / uuid4().hex
    encoded.mkdir()
    relative = encoded.relative_to(runtime.workdir)
    shutil.copyfile(runtime.workdir / path, encoded / 'structure')
    files = {structure_key: str(relative / 'structure')}
    obj = {'id': uuid4().hex, 'sequence': sequence, 'structure': {'file': structure_key, 'format': result.structure_format}}
    if 'label' in source:
        obj['label'] = source['label']
    confidence = {}
    if result.plddt is not None:
        if len(result.plddt) != len(sequence) or any(isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= 1 for value in result.plddt):
            raise ValueError('Prediction pLDDT must contain one finite 0–1 value per sequence residue')
        (encoded / 'confidence.json').write_text(json.dumps({'plddt': result.plddt}, allow_nan=False))
        files[prefix + 'confidence.json'] = str(relative / 'confidence.json')
        confidence['plddt'] = {'file': prefix + 'confidence.json', 'scale': '0-1'}
    if result.ptm is not None:
        if not math.isfinite(result.ptm) or not 0 <= result.ptm <= 1:
            raise ValueError('Prediction pTM must be a finite 0–1 value')
        confidence['ptm'] = result.ptm
    if confidence:
        obj['confidence'] = confidence
    if result.extras:
        (encoded / 'supplementary.json').write_text(json.dumps(result.extras, allow_nan=False))
        files[prefix + 'supplementary.json'] = str(relative / 'supplementary.json')
        obj['supplementary'] = {'file': prefix + 'supplementary.json'}
    return obj, files


def execute(call, runtime):
    package = call.inputs['sequence'][0]
    with package.open(package.entry) as stream:
        document = json.load(stream)
    if not isinstance(document, dict) or set(document) != {'objects'} or not isinstance(document['objects'], list) or not document['objects']:
        raise ValueError('Prediction requires a nonempty sequence object batch')
    sources = document['objects']
    for source in sources:
        if not isinstance(source, dict) or set(source) - {'id', 'sequence', 'label'}:
            raise ValueError('Prediction accepts a protein sequence only; unsupported components or conditions')
        sequence = source.get('sequence')
        if not isinstance(sequence, str) or not sequence or any(residue not in 'ACDEFGHIKLMNPQRSTVWY' for residue in sequence):
            raise ValueError('Prediction requires an unmodified canonical protein sequence')
        if not isinstance(source.get('id'), str) or not source['id']:
            raise ValueError('Sequence object id is required')
    if call.parameters:
        raise ValueError('Unknown prediction node parameters; configure the selected tool')
    parameters = call.tool_parameters.get('predictor', {})
    if not isinstance(parameters, dict):
        raise ValueError('Predictor parameters must be an object')
    objects, files = [], {}
    if call.previous is not None:
        completed = call.previous.continuation['completed']
        previous = call.previous.outputs.get('structure', ())
        if completed:
            if len(previous) != 1:
                raise ValueError('Continuation requires the accepted partial prediction package')
            package = previous[0]
            with package.open(package.entry) as stream:
                objects = json.load(stream)['objects']
            if len(objects) != completed or completed > len(sources):
                raise ValueError('Partial prediction count does not match continuation')
            for index, key in enumerate(package.files):
                if key == package.entry:
                    continue
                destination = runtime.workdir / ('previous-' + str(index))
                with package.open(key) as source, destination.open('wb') as target:
                    shutil.copyfileobj(source, target)
                files[key] = destination.name
    status, diagnostics = 'succeeded', ()
    for index in range(len(objects), len(sources)):
        if runtime.cancelled:
            status = 'cancelled'
            break
        source = sources[index]
        try:
            result = call.tools['predictor'](PredictionRequest(source['sequence'], source['id']), deepcopy(parameters), runtime)
            if runtime.cancelled:
                status = 'cancelled'
                break
            obj, delivered = _encode_result(result, source, runtime, '' if index == 0 else f'objects/{index}/')
            objects.append(obj)
            files.update(delivered)
            runtime.progress(f'Completed {len(objects)} of {len(sources)} predictions')
        except Exception as exc:
            status = 'cancelled' if runtime.cancelled else 'failed'
            diagnostics = (f'Prediction {index + 1} of {len(sources)} failed: {exc}',)
            break
    outputs = {}
    if objects:
        manifest = {'objects': objects, 'tool': {'id': call.tool_choices['predictor'], 'parameters': parameters}}
        (runtime.workdir / 'batch-manifest.json').write_text(json.dumps(manifest, allow_nan=False))
        files['manifest.json'] = 'batch-manifest.json'
        outputs['structure'] = [Delivery('workbench.prediction', 'manifest.json', files)]
    return Outcome(status=status, outputs=outputs, diagnostics=diagnostics,
                   continuation={'completed': len(objects)})


def module():
    from .adapters import tools
    return Module(id='workbench.prediction', name='Structure prediction', nodes=(Node(id='workbench.predict', name='Predict structure', execute=execute, inputs={'sequence': InputPort(('workbench.sequence',))}, outputs={'structure': OutputPort('workbench.prediction')}, tools={'predictor': ToolSlot('workbench.predict.structure', 'Structure predictor')}),), tools=tools(), settings={'python': 'Existing Python executable with pinned ESMFold2 dependencies', 'model_path': 'Existing ESMFold2 snapshot directory', 'language_model_path': 'Existing ESMC snapshot directory', 'device': 'cpu, mps or cuda', 'service_url': 'Biohub URL, default https://biohub.ai', 'token': {'type': 'string', 'title': 'Biohub credential', 'secret': True}}, ui=str(Path(__file__).with_name('ui.js').resolve()))
