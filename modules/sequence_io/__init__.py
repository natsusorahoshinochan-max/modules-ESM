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


def module():
    return Module(id='workbench.sequence_io', name='Sequence input and output',
        ui=str(Path(__file__).with_name('ui.js')),
        nodes=(Node('workbench.export_sequences', 'Export sequences as FASTA', export_sequences,
            inputs={'sequences': InputPort(('workbench.sequence',))},
            outputs={'files': OutputPort('workbench.sequence_export')}),))
