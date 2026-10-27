"""ESMC sequence representations with module-owned numeric file formats."""
import json
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

from protein_workbench_public.module_api import Delivery, InputPort, Module, Node, Outcome, OutputPort, ToolSlot
from .formats import write_array, read_sequences


def execute(call, runtime):
    if set(call.parameters) - {'outputs', 'dtype'}:
        raise ValueError('Unknown ESMC node parameters')
    outputs = call.parameters.get('outputs', 'both')
    dtype = call.parameters.get('dtype', 'float32')
    if outputs not in ('embedding', 'logits', 'both') or dtype not in ('float16', 'float32'):
        raise ValueError('Select embedding, logits or both and float16 or float32 storage')
    sources = read_sequences(call.inputs['sequence'][0])
    objects, files = [], {}
    options = SimpleNamespace(embedding=outputs in ('embedding', 'both'), logits=outputs in ('logits', 'both'), cancelled=runtime.cancelled)
    parameters = call.tool_parameters.get('representation', {})
    for index, source in enumerate(sources):
        if runtime.cancelled:
            return Outcome(status='cancelled')
        result = call.tools['representation'](source['sequence'], parameters, options)
        obj = {'input': deepcopy(source), 'tokens': result.tokens, 'model': result.model}
        if options.embedding:
            if result.mean is None:
                raise ValueError('ESMC omitted requested embedding')
            obj['mean_embedding'] = {**write_array(runtime.workdir, f'{index}-mean', result.mean, dtype, files), 'semantics': result.mean_semantics}
        if options.logits:
            if result.logits is None:
                raise ValueError('ESMC omitted requested logits')
            obj['logits'] = {**write_array(runtime.workdir, f'{index}-logits', result.logits, dtype, files), 'columns': result.columns, 'semantics': 'raw logits; not probabilities'}
        objects.append(obj)
        runtime.progress(f'Represented {index + 1} of {len(sources)} sequences')
    manifest = {'objects': objects, 'tool': {'id': call.tool_choices['representation'], 'parameters': result.parameters}, 'parameters': {'outputs': outputs, 'dtype': dtype}}
    (runtime.workdir / 'manifest.json').write_text(json.dumps(manifest, allow_nan=False))
    files['manifest.json'] = 'manifest.json'
    return Outcome(outputs={'representation': [Delivery('workbench.esmc', 'manifest.json', files)]})


def module():
    from .adapters import tools
    return Module(id='workbench.esmc', name={'zh-CN': '序列表征', 'en': 'Sequence representations'}, nodes=(Node(id='workbench.represent', name={'zh-CN': '计算表征', 'en': 'Compute representations'}, execute=execute,
        inputs={'sequence': InputPort(('workbench.sequence',), name={'zh-CN': '序列', 'en': 'Sequence'})}, outputs={'representation': OutputPort('workbench.esmc')},
        parameters={'outputs': {'type': 'string', 'enum': ['embedding', 'logits', 'both'], 'default': 'both', 'title': {'zh-CN': '输出内容', 'en': 'Outputs'}}, 'dtype': {'type': 'string', 'enum': ['float32', 'float16'], 'default': 'float32', 'title': {'zh-CN': '保存精度', 'en': 'Precision'}}},
        tools={'representation': ToolSlot('workbench.esmc.representation', {'zh-CN': '序列表征', 'en': 'Sequence representation'})}),), tools=tools(),
        settings={'model_path': {'title': {'zh-CN': '模型目录', 'en': 'Model directory'}, 'description': 'Existing ESMC Hugging Face directory'}, 'device': {'title': {'zh-CN': '计算设备', 'en': 'Device'}, 'description': 'cpu, mps or cuda'}, 'service_url': {'title': {'zh-CN': '服务地址', 'en': 'Service URL'}, 'description': 'Biohub service URL, default https://biohub.ai'}, 'token': {'type': 'string', 'title': {'zh-CN': 'Biohub 凭据', 'en': 'Biohub credential'}, 'secret': True}}, ui=str(Path(__file__).with_name('ui.js').resolve()))
