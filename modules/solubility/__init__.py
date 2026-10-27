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
    return Module(id='workbench.solubility', name={'zh-CN': '可溶性评价', 'en': 'Solubility evaluation'}, nodes=(Node(
        id='workbench.evaluate_solubility', name={'zh-CN': '评价可溶性', 'en': 'Evaluate solubility'}, execute=execute,
        inputs={'sequence': InputPort(('workbench.sequence',), name={'zh-CN': '序列', 'en': 'Sequence'})}, outputs={'evaluation': OutputPort('workbench.solubility', name={'zh-CN': '评价', 'en': 'Evaluation'})},
        tools={'evaluator': ToolSlot(SLOT, {'zh-CN': '序列可溶性评价', 'en': 'Sequence solubility evaluator'})}),), tools=tools(),
        settings={'protein_sol_source': {'title': {'zh-CN': 'Protein-Sol 源码目录', 'en': 'Protein-Sol source directory'}}, 'bash': {'title': {'zh-CN': 'Bash 路径', 'en': 'Bash path'}}, 'perl': {'title': {'zh-CN': 'Perl 路径', 'en': 'Perl path'}}, 'soluprot_source': {'title': {'zh-CN': 'SoluProt 源码目录', 'en': 'SoluProt source directory'}}, 'soluprot_python': {'title': {'zh-CN': 'SoluProt Python 路径', 'en': 'SoluProt Python path'}}, 'usearch': {'title': {'zh-CN': 'USEARCH 路径', 'en': 'USEARCH path'}}, 'tmhmm': {'title': {'zh-CN': 'TMHMM 路径', 'en': 'TMHMM path'}}, 'soluprot_full_model': {'title': {'zh-CN': 'SoluProt 完整模型', 'en': 'SoluProt full model'}}, 'soluprot_no_tm_model': {'title': {'zh-CN': 'SoluProt 无跨膜模型', 'en': 'SoluProt no-TM model'}}, 'soluprot_database': {'title': {'zh-CN': 'SoluProt 数据库', 'en': 'SoluProt database'}}},
        ui=str(Path(__file__).with_name('ui.js').resolve()))
