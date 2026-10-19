"""Independent evaluation of already supplied sequence objects."""
import json
from pathlib import Path
from copy import deepcopy

from protein_workbench_public.module_api import Delivery, InputPort, Module, Node, Outcome, OutputPort, ToolSlot
from .contract import SolubilityRequest, SolubilityResult
from .formats import read_sequences, validate_evaluations


def execute(call, runtime):
    if call.parameters:
        raise ValueError('Solubility evaluates complete supplied sequences; unsupported node parameters')
    objects = read_sequences(call.inputs['sequence'][0])
    parameters = call.tool_parameters.get('evaluator', {})
    if not isinstance(parameters, dict):
        raise ValueError('Solubility tool parameters must be an object')
    result = call.tools['evaluator'](SolubilityRequest(tuple(obj['sequence'] for obj in objects)), deepcopy(parameters), runtime)
    if runtime.cancelled:
        return Outcome(status='cancelled')
    if not isinstance(result, SolubilityResult) or len(result.values) != len(objects):
        raise ValueError('Tool must return one evaluation per supplied sequence, in request order')
    output = Path(result.output_file)
    if output.is_absolute() or not (runtime.workdir / output).resolve().is_relative_to(runtime.workdir.resolve()) or not (runtime.workdir / output).is_file():
        raise ValueError('Solubility tool output must be a completed file inside runtime.workdir')
    document = {'objects': deepcopy(objects), 'evaluations': [
        {'object_id': obj['id'], 'reference': None, 'region': None, 'method': result.method, 'values': values}
        for obj, values in zip(objects, result.values, strict=True)],
        'tool': {'id': call.tool_choices['evaluator'], 'parameters': dict(result.parameters), 'context': dict(result.context), 'output': 'tool-output.txt'}}
    manifest = runtime.workdir / 'evaluation.json'
    manifest.write_text(json.dumps(document, allow_nan=False))
    validate_evaluations(document)
    return Outcome(outputs={'evaluation': [Delivery('workbench.solubility', 'manifest.json', {'manifest.json': manifest.name, 'tool-output.txt': str(output)})]})


def module():
    from .adapters import SLOT, tools
    return Module(id='workbench.solubility', name='Sequence solubility evaluation', nodes=(Node(
        id='workbench.evaluate_solubility', name='Evaluate existing sequence solubility', execute=execute,
        inputs={'sequence': InputPort(('workbench.sequence',))}, outputs={'evaluation': OutputPort('workbench.solubility')},
        tools={'evaluator': ToolSlot(SLOT, 'Sequence solubility evaluator')}),), tools=tools(),
        settings={key: title for key, title in (
            ('protein_sol_source', 'Existing official Protein-Sol October 2017 script directory'),
            ('bash', 'Existing Bash executable'), ('perl', 'Existing Perl executable'),
            ('soluprot_source', 'Existing maintained SoluProt port package root'),
            ('soluprot_python', 'Existing Python with SoluProt dependencies'),
            ('usearch', 'Existing USEARCH executable'), ('tmhmm', 'Existing TMHMM executable (full mode)'),
            ('soluprot_full_model', 'Existing full model.json'), ('soluprot_no_tm_model', 'Existing no-TM model.json'),
            ('soluprot_database', 'Existing E. coli PDB FASTA database'))},
        ui=str(Path(__file__).with_name('ui.js').resolve()))
