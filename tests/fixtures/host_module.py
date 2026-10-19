"""An independent module authored exclusively against the public SDK."""
from threading import Event

from protein_workbench_public.module_api import Delivery, InputPort, Module, Node, Outcome, OutputPort


def encode(call, runtime):
    incoming = call.inputs["source"][0]
    with incoming.open(incoming.entry) as stream:
        data = stream.read()
    (runtime.workdir / "encoded").mkdir()
    (runtime.workdir / "encoded" / "bytes.bin").write_bytes(data + call.parameters.get("suffix", "").encode() + call.settings.get("label", "").encode())
    return Outcome(outputs={"result": [Delivery(format="independent.binary", entry="entry.bin", files={"entry.bin": "encoded/bytes.bin"})]}, continuation={"done": 1})


def receive(call, runtime):
    package = call.inputs["source"][0]
    with package.open("entry.bin") as stream:
        data = stream.read()
    (runtime.workdir / "summary").write_bytes(b"received:" + data)
    return Outcome(outputs={"result": [Delivery("independent.received", "summary", {"summary": "summary"})]})


def module():
    return Module(id="independent", name="Independent module", settings={"label": {"type": "string"}}, nodes=(Node(id="independent.encode", name="Encode", execute=encode, inputs={"source": InputPort(("independent.request",))}, outputs={"result": OutputPort("independent.binary")}), Node(id="independent.receive", name="Receive", execute=receive, inputs={"source": InputPort(("independent.binary",))}, outputs={"result": OutputPort("independent.received")})))


def empty_batch(call, runtime):
    return Outcome(outputs={"result": []})


def should_not_receive_empty(call, runtime):
    raise AssertionError("receiver was executed with missing required input")


def empty_module():
    return Module(id="empty", name="Empty batch", nodes=(Node("empty.source", "Empty source", empty_batch, outputs={"result": OutputPort("batch", "many")}), Node("empty.receive", "Required receiver", should_not_receive_empty, inputs={"source": InputPort(("batch",), "many")})))


def mutating_node(call, runtime):
    call.parameters["nested"]["value"] = "changed inside node"
    call.settings["nested"]["value"] = "changed inside node"
    return Outcome(status="failed", diagnostics=("failure after local mutation",))


def mutating_module():
    return Module("mutating", "Mutating", nodes=(Node("mutating.node", "Mutating node", mutating_node),))


def conflicting_module():
    return Module("conflict", "Conflicting module", nodes=(Node("independent.encode", "Conflicting node", empty_batch),))


def malformed_module():
    return Module("malformed", "Malformed", nodes=(Node("bad.input", "Bad input", empty_batch, inputs={"source": InputPort("format-is-not-a-list")}),))


def invalid_catalog_module():
    return Module("invalid.catalog", "Invalid catalog", nodes=(Node("invalid.catalog.node", "Bad \ud800 title", empty_batch),))


entered = Event()
release = Event()


def held_node(call, runtime):
    entered.set()
    if not release.wait(10):
        raise RuntimeError('Test did not release held node')
    return Outcome()


def held_module():
    return Module('held', 'Held', nodes=(Node('held.node', 'Held node', held_node),))
