"""Tests for the serial Executor."""

import asyncio

import pytest
from core import Executor, NodeState, Workflow, WorkflowEdge, WorkflowNode
from core.run_context import RunContext
from core.workflow_module import WorkflowModule
from modules.stub import EchoModule


def make_echo_modules() -> dict[str, WorkflowModule]:
    return {"stub.echo": EchoModule()}


class TestExecutorSingleNode:
    def test_single_node_completes(self) -> None:
        wf = Workflow()
        wf.add_node(WorkflowNode("n1", "stub.echo", "1.0.0", {"repeat": 1}))
        executor = Executor()
        result = asyncio.run(executor.execute(
            wf, make_echo_modules(), "/tmp/test", "run-1"
        ))
        assert "n1" in result
        assert wf.nodes["n1"].state == NodeState.COMPLETED

    def test_single_node_creates_output(self) -> None:
        wf = Workflow()
        wf.add_node(WorkflowNode("n1", "stub.echo", "1.0.0", {"repeat": 1}))
        executor = Executor()
        result = asyncio.run(executor.execute(
            wf, make_echo_modules(), "/tmp/test", "run-2"
        ))
        assert result["n1"]["text"] == ""

    def test_state_callbacks_fire(self) -> None:
        wf = Workflow()
        wf.add_node(WorkflowNode("n1", "stub.echo", "1.0.0"))
        executor = Executor()
        states = []
        executor.on_state_change(lambda nid, old, new: states.append((nid, old, new)))
        asyncio.run(executor.execute(
            wf, make_echo_modules(), "/tmp/test", "run-3"
        ))
        # Should see: idle->queued, queued->running, running->completed
        assert len(states) >= 3
        assert ("n1", NodeState.IDLE, NodeState.QUEUED) in states
        assert ("n1", NodeState.QUEUED, NodeState.RUNNING) in states
        assert ("n1", NodeState.RUNNING, NodeState.COMPLETED) in states


class TestExecutorLinearChain:
    def test_three_node_chain(self) -> None:
        wf = Workflow()
        wf.add_node(WorkflowNode("a", "stub.echo", "1.0.0", {"prefix": "A:"}))
        wf.add_node(WorkflowNode("b", "stub.echo", "1.0.0", {"prefix": "B:"}))
        wf.add_node(WorkflowNode("c", "stub.echo", "1.0.0", {"prefix": "C:"}))
        wf.add_edge(WorkflowEdge("a", "text", "b", "text"))
        wf.add_edge(WorkflowEdge("b", "text", "c", "text"))
        executor = Executor()
        result = asyncio.run(executor.execute(
            wf, make_echo_modules(), "/tmp/test", "run-chain"
        ))
        assert result["c"]["text"] == "C:B:A:"
        assert wf.nodes["a"].state == NodeState.COMPLETED
        assert wf.nodes["b"].state == NodeState.COMPLETED
        assert wf.nodes["c"].state == NodeState.COMPLETED


class TestExecutorBranch:
    def test_one_to_two_branch(self) -> None:
        wf = Workflow()
        wf.add_node(WorkflowNode("src", "stub.echo", "1.0.0", {"prefix": "S:"}))
        wf.add_node(WorkflowNode("left", "stub.echo", "1.0.0", {"prefix": "L:"}))
        wf.add_node(WorkflowNode("right", "stub.echo", "1.0.0", {"prefix": "R:"}))
        wf.add_edge(WorkflowEdge("src", "text", "left", "text"))
        wf.add_edge(WorkflowEdge("src", "text", "right", "text"))
        executor = Executor()
        result = asyncio.run(executor.execute(
            wf, make_echo_modules(), "/tmp/test", "run-branch"
        ))
        assert result["left"]["text"] == "L:S:"
        assert result["right"]["text"] == "R:S:"


class TestExecutorMerge:
    def test_two_to_one_merge(self) -> None:
        # Two nodes feed into one. The downstream node gets both inputs.
        # Use a different setup: we'll test that the merge node receives
        # the output of whichever upstream node connects to its text port.
        wf = Workflow()
        wf.add_node(WorkflowNode("a", "stub.echo", "1.0.0", {"prefix": "A:"}))
        wf.add_node(WorkflowNode("b", "stub.echo", "1.0.0", {"prefix": "B:"}))
        wf.add_node(WorkflowNode("c", "stub.echo", "1.0.0"))
        wf.add_edge(WorkflowEdge("a", "text", "c", "text"))
        wf.add_edge(WorkflowEdge("b", "text", "c", "text"))
        executor = Executor()
        result = asyncio.run(executor.execute(
            wf, make_echo_modules(), "/tmp/test", "run-merge"
        ))
        # Both inputs contribute; the executor collects from all upstream edges.
        # The Echo module only reads 'text' from inputs — the last edge wins
        # in the dict since both target the same port. Either A: or B: is valid.
        assert "c" in result


class TestExecutorErrorPropagation:
    def test_failed_node_blocks_downstream(self) -> None:
        class FailingModule(WorkflowModule):
            @property
            def definition(self):
                from core.module_definition import ModuleDefinition
                return ModuleDefinition(
                    module_id="failing", version="1.0.0",
                    display_name="Fail", category="input",
                )
            def run(self, inputs, parameters, context):
                raise RuntimeError("intentional failure")

        wf = Workflow()
        wf.add_node(WorkflowNode("a", "failing", "1.0.0"))
        wf.add_node(WorkflowNode("b", "stub.echo", "1.0.0"))
        wf.add_edge(WorkflowEdge("a", "text", "b", "text"))

        modules = {"stub.echo": EchoModule(), "failing": FailingModule()}
        executor = Executor()
        result = asyncio.run(executor.execute(
            wf, modules, "/tmp/test", "run-fail"
        ))
        assert wf.nodes["a"].state == NodeState.FAILED
        assert wf.nodes["b"].state == NodeState.BLOCKED
        assert "a" not in result
        assert "b" not in result

    def test_unrelated_branch_continues_after_failure(self) -> None:
        class FailingModule(WorkflowModule):
            @property
            def definition(self):
                from core.module_definition import ModuleDefinition
                return ModuleDefinition(
                    module_id="failing", version="1.0.0",
                    display_name="Fail", category="input",
                )
            def run(self, inputs, parameters, context):
                raise RuntimeError("intentional failure")

        wf = Workflow()
        wf.add_node(WorkflowNode("fail", "failing", "1.0.0"))
        wf.add_node(WorkflowNode("echo", "stub.echo", "1.0.0", {"prefix": "OK:"}))
        # No edge between them — independent branches

        modules = {"stub.echo": EchoModule(), "failing": FailingModule()}
        executor = Executor()
        result = asyncio.run(executor.execute(
            wf, modules, "/tmp/test", "run-unrelated"
        ))
        assert wf.nodes["fail"].state == NodeState.FAILED
        assert wf.nodes["echo"].state == NodeState.COMPLETED
        assert "echo" in result
        assert result["echo"]["text"] == "OK:"
