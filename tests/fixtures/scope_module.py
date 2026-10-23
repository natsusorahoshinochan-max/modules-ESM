"""Independent text module used to exercise package-only scope scheduling."""
from threading import Event

from protein_workbench_public.module_api import Delivery, InputPort, Module, Node, Outcome, OutputPort

observed = []
refuse_delivery = set()
entered = Event()
release = Event()


def text(package):
    with package.open(package.entry) as reader:
        return reader.read().decode()


def transform(call, runtime):
    value = text(call.inputs['source'][0])
    reference = ''.join(text(item) for item in call.inputs['reference'])
    observed.append((value, reference, dict(call.parameters), call.previous is not None))
    if call.parameters.get('hold') and call.previous is None:
        entered.set()
        release.wait(5)
    failed = call.parameters.get('fail') == value and call.previous is None
    output = []
    for index in range(call.parameters.get('copies', 1)):
        filename = f'{index}.txt'
        (runtime.workdir / filename).write_text(value + call.parameters.get('suffix', '!') + reference)
        output.append(Delivery('scope.text', 'text', {'text': filename}))
    if value in refuse_delivery:
        refuse_delivery.remove(value)
        output.append(Delivery('scope.text', 'text', {'text': 'missing.txt'}))
    return Outcome(status='failed' if failed else 'succeeded', outputs={'result': output},
                   continuation={'retry': True} if failed else None,
                   diagnostics=('requested text failure',) if failed else ())


def module():
    return Module('scope.text', 'Text scopes', nodes=(Node('scope.transform', 'Transform text', transform,
        inputs={'source': InputPort(('scope.text',)), 'reference': InputPort(('scope.text',), 'many', False)},
        outputs={'result': OutputPort('scope.text', 'many')}),))


def reserved_module():
    return Module('reserved.scope', 'Reserved name', nodes=(Node('host.map', 'Map', transform),))


def source(call, runtime):
    (runtime.workdir / 'text').write_text('A')
    return Outcome(outputs={'result': [Delivery('scope.text', 'text', {'text': 'text'})]})


def source_module():
    return Module('scope.source', 'Independent source', nodes=(Node('scope.source', 'Source', source,
        outputs={'result': OutputPort('scope.text')}),))
