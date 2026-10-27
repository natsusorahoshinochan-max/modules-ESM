"""Sequence import, viewing and file export, independently installable from tools."""
import json
from pathlib import Path

from protein_workbench_public.module_api import Delivery, InputPort, Module, Node, Outcome, OutputPort
from .formats import read_sequences


def export_sequences(call, runtime):
    objects = read_sequences(call.inputs['sequences'][0])
    if set(call.parameters) - {'objects'}:
        raise ValueError('Unknown sequence export parameter')
    selected = call.parameters.get('objects', [obj['id'] for obj in objects])
    if not isinstance(selected, list) or any(not isinstance(key, str) for key in selected) or len(set(selected)) != len(selected):
        raise ValueError('Select an ordered list of distinct sequence objects')
    by_id = {obj['id']: obj for obj in objects}
    if any(key not in by_id for key in selected):
        raise ValueError('A selected sequence object is missing from the supplied package')
    objects = [by_id[key] for key in selected]
    if runtime.cancelled:
        return Outcome(status='cancelled')
    records = []
    for obj in objects:
        if '_' in obj['sequence']:
            raise ValueError(f"FASTA export requires filled positions; object {obj['id']} has a blank at position {obj['sequence'].index('_') + 1}. Save the sequence package to preserve blanks.")
        label = (obj.get('label') or obj['id']).replace('\r', ' ').replace('\n', ' ')
        records.append(f">{label}\n{obj['sequence']}\n")
    (runtime.workdir / 'sequences.fasta').write_text(''.join(records), encoding='utf-8')
    (runtime.workdir / 'manifest.json').write_text(json.dumps({
        'objects': objects, 'export': {'format': 'fasta', 'file': 'sequences.fasta', 'parameters': call.parameters},
    }, ensure_ascii=False), encoding='utf-8')
    return Outcome(outputs={'files': [Delivery('workbench.sequence_export', 'manifest.json', {
        'manifest.json': 'manifest.json', 'sequences.fasta': 'sequences.fasta',
    })]})


def import_sequences(call, runtime):
    if runtime.cancelled:
        return Outcome(status='cancelled')
    if call.parameters:
        raise ValueError('序列导入没有计算参数')
    objects = read_sequences(call.inputs['file'][0])
    (runtime.workdir / 'manifest.json').write_text(json.dumps({'objects': objects}, ensure_ascii=False), encoding='utf-8')
    return Outcome(outputs={'sequence': [Delivery('workbench.sequence', 'manifest.json', {'manifest.json': 'manifest.json'})]})


def module():
    return Module(id='workbench.sequence_io', name={'zh-CN': '序列输入输出', 'en': 'Sequence I/O'},
        ui=str(Path(__file__).with_name('ui.js')),
        nodes=(Node('workbench.import_sequence', {'zh-CN': '导入序列', 'en': 'Import sequence'}, import_sequences, inputs={'file': InputPort(('workbench.sequence',), name={'zh-CN': '文件', 'en': 'Files'})}, outputs={'sequence': OutputPort('workbench.sequence', name={'zh-CN': '序列', 'en': 'Sequence'})}), Node('workbench.export_sequences', {'zh-CN': '导出序列', 'en': 'Export sequences'}, export_sequences,
            inputs={'sequences': InputPort(('workbench.sequence',), name={'zh-CN': '序列', 'en': 'Sequence'})},
            outputs={'files': OutputPort('workbench.sequence_export', name={'zh-CN': '文件', 'en': 'Files'})}),))
