"""Independent module illustrating only the public temporary-call contract."""
from threading import Event
from protein_workbench_public.module_api import Call, Delivery, InputPort, Interaction, InteractionResult, Module

started = Event()
cancelled = Event()
finish = Event()


def inspect(call: Call, runtime):
    with call.inputs['data'][0].open(call.inputs['data'][0].entry) as reader:
        content = reader.read().decode()
    if call.parameters.get('wait'):
        started.set()
        while not runtime.cancelled:
            cancelled.wait(.01)
        cancelled.set()
        finish.wait(5)
    # This write must remain possible until the handler returns, including cancellation.
    (runtime.workdir / 'data').write_text(content + str(call.settings.get('suffix', '')))
    files = {'data': 'missing' if call.parameters.get('missing') else 'data'}
    return InteractionResult({'content': content, 'settings': call.settings}, {'result': Delivery('external.edited', 'data', files)})


def module():
    return Module(id='external.editor', name='Independent editor', settings={'suffix': {'type': 'string'}},
                  interactions=(Interaction('external.inspect', inspect, {'data': InputPort(('external.data',))}),))
