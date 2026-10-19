"""Consumer of the public example.note format."""
from protein_workbench_public.module_api import Delivery, InputPort, Module, Node, Outcome, OutputPort


def count(call, runtime):
    package = call.inputs['note'][0]
    with package.open(package.entry) as stream:
        text = stream.read().decode('utf-8')
    (runtime.workdir / 'count.txt').write_text(str(len(text)), encoding='utf-8')
    return Outcome(outputs={'count': [Delivery('example.count', 'count', {'count': 'count.txt'})]})


def module():
    return Module(id='example.reader', name='Independent note reader', nodes=(
        Node('example.count', 'Count note characters', count,
             inputs={'note': InputPort(('example.note',))}, outputs={'count': OutputPort('example.count')}),
    ))
