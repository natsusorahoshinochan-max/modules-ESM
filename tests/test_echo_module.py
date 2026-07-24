"""Tests for the Echo stub module run() contract."""

from core.run_context import RunContext
from modules.stub import EchoModule


class TestEchoModule:
    def test_run_returns_text(self) -> None:
        mod = EchoModule()
        ctx = RunContext("/tmp/test", "n1")
        result = mod.run({"text": "hello"}, {"repeat": 1, "prefix": ""}, ctx)
        assert result == {"text": "hello"}

    def test_run_repeats_text(self) -> None:
        mod = EchoModule()
        ctx = RunContext("/tmp/test", "n1")
        result = mod.run({"text": "hi"}, {"repeat": 3, "prefix": ""}, ctx)
        assert result == {"text": "hi\nhi\nhi"}

    def test_run_with_prefix(self) -> None:
        mod = EchoModule()
        ctx = RunContext("/tmp/test", "n1")
        result = mod.run({"text": "test"}, {"repeat": 2, "prefix": "> "}, ctx)
        assert result == {"text": "> test\n> test"}

    def test_run_empty_input(self) -> None:
        mod = EchoModule()
        ctx = RunContext("/tmp/test", "n1")
        result = mod.run({}, {"repeat": 1, "prefix": ""}, ctx)
        assert result == {"text": ""}

    def test_run_default_parameters(self) -> None:
        mod = EchoModule()
        ctx = RunContext("/tmp/test", "n1")
        result = mod.run({"text": "x"}, {}, ctx)
        assert result == {"text": "x"}  # repeat=1 default, no prefix

    def test_definition_is_valid(self) -> None:
        mod = EchoModule()
        d = mod.definition
        assert d.module_id == "stub.echo"
        assert d.version == "1.0.0"
        assert d.category == "input"
        assert len(d.input_ports) == 1
        assert d.input_ports[0].name == "text"
        assert d.input_ports[0].type_id == "text"
        assert len(d.output_ports) == 1
        assert d.output_ports[0].name == "text"
        assert len(d.parameters) == 2
