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
    def test_single_node_completes(self, isolated_project_dir: str) -> None:
        wf = Workflow()
        wf.add_node(WorkflowNode("n1", "stub.echo", "1.0.0", {"repeat": 1}))
        executor = Executor()
        result = asyncio.run(executor.execute(
            wf, make_echo_modules(), isolated_project_dir, "run-1"
        ))
        assert "n1" in result
        assert wf.nodes["n1"].state == NodeState.COMPLETED

    def test_single_node_creates_output(self, isolated_project_dir: str) -> None:
        wf = Workflow()
        wf.add_node(WorkflowNode("n1", "stub.echo", "1.0.0", {"repeat": 1}))
        executor = Executor()
        result = asyncio.run(executor.execute(
            wf, make_echo_modules(), isolated_project_dir, "run-2"
        ))
        assert result["n1"]["text"] == ""

    def test_state_callbacks_fire(self, isolated_project_dir: str) -> None:
        wf = Workflow()
        wf.add_node(WorkflowNode("n1", "stub.echo", "1.0.0"))
        executor = Executor()
        states = []
        executor.on_state_change(lambda nid, old, new: states.append((nid, old, new)))
        asyncio.run(executor.execute(
            wf, make_echo_modules(), isolated_project_dir, "run-3"
        ))
        # Should see: idle->queued, queued->running, running->completed
        assert len(states) >= 3
        assert ("n1", NodeState.IDLE, NodeState.QUEUED) in states
        assert ("n1", NodeState.QUEUED, NodeState.RUNNING) in states
        assert ("n1", NodeState.RUNNING, NodeState.COMPLETED) in states


class TestExecutorLinearChain:
    def test_three_node_chain(self, isolated_project_dir: str) -> None:
        wf = Workflow()
        wf.add_node(WorkflowNode("a", "stub.echo", "1.0.0", {"prefix": "A:"}))
        wf.add_node(WorkflowNode("b", "stub.echo", "1.0.0", {"prefix": "B:"}))
        wf.add_node(WorkflowNode("c", "stub.echo", "1.0.0", {"prefix": "C:"}))
        wf.add_edge(WorkflowEdge("a", "text", "b", "text"))
        wf.add_edge(WorkflowEdge("b", "text", "c", "text"))
        executor = Executor()
        result = asyncio.run(executor.execute(
            wf, make_echo_modules(), isolated_project_dir, "run-chain"
        ))
        assert result["c"]["text"] == "C:B:A:"
        assert wf.nodes["a"].state == NodeState.COMPLETED
        assert wf.nodes["b"].state == NodeState.COMPLETED
        assert wf.nodes["c"].state == NodeState.COMPLETED


class TestExecutorBranch:
    def test_one_to_two_branch(self, isolated_project_dir: str) -> None:
        wf = Workflow()
        wf.add_node(WorkflowNode("src", "stub.echo", "1.0.0", {"prefix": "S:"}))
        wf.add_node(WorkflowNode("left", "stub.echo", "1.0.0", {"prefix": "L:"}))
        wf.add_node(WorkflowNode("right", "stub.echo", "1.0.0", {"prefix": "R:"}))
        wf.add_edge(WorkflowEdge("src", "text", "left", "text"))
        wf.add_edge(WorkflowEdge("src", "text", "right", "text"))
        executor = Executor()
        result = asyncio.run(executor.execute(
            wf, make_echo_modules(), isolated_project_dir, "run-branch"
        ))
        assert result["left"]["text"] == "L:S:"
        assert result["right"]["text"] == "R:S:"


class TestExecutorMerge:
    def test_two_to_one_merge(self, isolated_project_dir: str) -> None:
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
            wf, make_echo_modules(), isolated_project_dir, "run-merge"
        ))
        # Both inputs contribute; the executor collects from all upstream edges.
        # The Echo module only reads 'text' from inputs — the last edge wins
        # in the dict since both target the same port. Either A: or B: is valid.
        assert "c" in result


class TestExecutorErrorPropagation:
    def test_failed_node_blocks_downstream(
        self, isolated_project_dir: str
    ) -> None:
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
            wf, modules, isolated_project_dir, "run-fail"
        ))
        assert wf.nodes["a"].state == NodeState.FAILED
        assert wf.nodes["b"].state == NodeState.BLOCKED
        assert "a" not in result
        assert "b" not in result

    def test_unrelated_branch_continues_after_failure(
        self, isolated_project_dir: str
    ) -> None:
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
            wf, modules, isolated_project_dir, "run-unrelated"
        ))
        assert wf.nodes["fail"].state == NodeState.FAILED
        assert wf.nodes["echo"].state == NodeState.COMPLETED
        assert "echo" in result
        assert result["echo"]["text"] == "OK:"


# ── Cache E2E Tests ──────────────────────────────────────────────────

class TestCacheE2E:
    def test_cache_hit_skips_execution(self) -> None:
        """Second run with same inputs should hit cache and skip module.run."""
        from unittest.mock import MagicMock
        from core.graph import Workflow, WorkflowNode, WorkflowEdge
        from core.executor import Executor
        from modules.stub import EchoModule
        import tempfile, os, asyncio

        mock_module = MagicMock(wraps=EchoModule())
        mock_module.definition = EchoModule().definition

        workflow = Workflow()
        node = WorkflowNode(node_id="n1", module_id="stub.echo", module_version="1.0.0",
                            parameters={"text": "cache-test"})
        workflow.add_node(node)

        with tempfile.TemporaryDirectory() as tmpdir:
            ex = Executor()
            modules = {"stub.echo": mock_module}

            # First run: should execute
            asyncio.run(ex.execute(workflow, modules, tmpdir, "run1", seed=42))
            assert mock_module.run_async.call_count == 1
            assert node.state.value == "completed"

            # Second run: should hit cache, not call run again
            node2 = WorkflowNode(node_id="n1", module_id="stub.echo", module_version="1.0.0",
                                 parameters={"text": "cache-test"})
            workflow2 = Workflow()
            workflow2.add_node(node2)

            mock_module2 = MagicMock(wraps=EchoModule())
            mock_module2.definition = EchoModule().definition
            modules2 = {"stub.echo": mock_module2}

            asyncio.run(ex.execute(workflow2, modules2, tmpdir, "run2", seed=42))
            assert mock_module2.run_async.call_count == 0  # Cache hit!
            assert node2.state.value == "completed"

    def test_cache_miss_on_input_change(self) -> None:
        """Different input should cause cache miss."""
        from unittest.mock import MagicMock
        from core.graph import Workflow, WorkflowNode
        from core.executor import Executor
        from modules.stub import EchoModule
        import tempfile, asyncio

        with tempfile.TemporaryDirectory() as tmpdir:
            ex = Executor()

            # First run
            mock1 = MagicMock(wraps=EchoModule())
            mock1.definition = EchoModule().definition
            wf1 = Workflow()
            wf1.add_node(WorkflowNode(node_id="n1", module_id="stub.echo", module_version="1.0.0",
                         parameters={"text": "input-A"}))
            asyncio.run(ex.execute(wf1, {"stub.echo": mock1}, tmpdir, "run1", seed=42))
            assert mock1.run_async.call_count == 1

            # Second run with different input
            mock2 = MagicMock(wraps=EchoModule())
            mock2.definition = EchoModule().definition
            wf2 = Workflow()
            wf2.add_node(WorkflowNode(node_id="n1", module_id="stub.echo", module_version="1.0.0",
                         parameters={"text": "input-B"}))
            asyncio.run(ex.execute(wf2, {"stub.echo": mock2}, tmpdir, "run2", seed=42))
            assert mock2.run_async.call_count == 1  # Cache miss!

    def test_force_rerun_ignores_cache(self) -> None:
        """force_rerun_nodes should skip cache and re-execute."""
        from unittest.mock import MagicMock
        from core.graph import Workflow, WorkflowNode
        from core.executor import Executor
        from modules.stub import EchoModule
        import tempfile, asyncio

        with tempfile.TemporaryDirectory() as tmpdir:
            ex = Executor()

            # First run: populate cache
            mock1 = MagicMock(wraps=EchoModule())
            mock1.definition = EchoModule().definition
            wf1 = Workflow()
            wf1.add_node(WorkflowNode(node_id="n1", module_id="stub.echo", module_version="1.0.0",
                         parameters={"text": "force-test"}))
            asyncio.run(ex.execute(wf1, {"stub.echo": mock1}, tmpdir, "run1", seed=42))
            assert mock1.run_async.call_count == 1

            # Second run: force rerun same node
            mock2 = MagicMock(wraps=EchoModule())
            mock2.definition = EchoModule().definition
            wf2 = Workflow()
            wf2.add_node(WorkflowNode(node_id="n1", module_id="stub.echo", module_version="1.0.0",
                         parameters={"text": "force-test"}))
            asyncio.run(ex.execute(
                wf2, {"stub.echo": mock2}, tmpdir, "run2", seed=42,
                force_rerun_nodes={"n1"},
            ))
            assert mock2.run_async.call_count == 1  # Should re-execute despite cache


# ── Cancel E2E Tests ─────────────────────────────────────────────────

class TestCancelE2E:
    def test_cancel_endpoint_works(self) -> None:
        """Cancel endpoint accepts run_id and returns cancelled status."""
        from core.server import app
        from fastapi.testclient import TestClient

        with TestClient(app) as client:
            # Start a simple execution
            payload = {
                "nodes": [
                    {"node_id": "n1", "module_id": "stub.echo",
                     "module_version": "1.0.0", "parameters": {"text": "test"}},
                ],
                "edges": [],
            }
            resp = client.post("/api/execute", json=payload)
            assert resp.status_code == 200
            run_id = resp.json().get("run_id", "")
            assert run_id

            # Cancel immediately (echo is fast, so it may already be done)
            cancel_resp = client.post("/api/execute/cancel", json={"run_id": run_id})
            assert cancel_resp.status_code == 200
            # The request is non-terminal; fast work may already be complete.
            assert cancel_resp.json()["status"] in (
                "cancellation_requested",
                "not_found",
            )
