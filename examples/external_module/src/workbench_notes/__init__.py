"""An independently installable module using only the public author SDK."""
from pathlib import Path
from uuid import uuid4

from protein_workbench_public.module_api import Delivery, InputPort, Module, Node, Outcome, OutputPort


def uppercase(call, runtime):
    source = call.inputs['note'][0]
    with source.open(source.entry) as stream:
        text = stream.read().decode('utf-8')
    result = runtime.workdir / 'result.txt'
    result.write_text(call.settings.get('prefix', '') + text.upper(), encoding='utf-8')
    identity = runtime.workdir / 'object.txt'
    identity.write_text(str(uuid4()), encoding='utf-8')
    return Outcome(outputs={'note': [Delivery('example.note', 'text', {'text': 'result.txt', 'object': 'object.txt'})]})


def module():
    return Module(
        id='example.notes', name='External notes',
        settings={'prefix': {'type': 'string', 'title': 'Output prefix'}},
        ui=str(Path(__file__).with_name('ui.js')),
        nodes=(Node('example.uppercase', 'Uppercase note', uppercase,
                    inputs={'note': InputPort(('example.note',))},
                    outputs={'note': OutputPort('example.note')}),),
    )
