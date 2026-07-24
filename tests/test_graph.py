"""Tests for Workflow DAG model and topological sort."""

import pytest
from core import NodeState, Workflow, WorkflowEdge, WorkflowNode


class TestWorkflowNode:
    def test_creation(self) -> None:
        node = WorkflowNode("n1", "stub.echo", "1.0.0", {"repeat": 3})
        assert node.node_id == "n1"
        assert node.module_id == "stub.echo"
        assert node.parameters == {"repeat": 3}
        assert node.state == NodeState.IDLE
        assert node.outputs == {}

    def test_reset(self) -> None:
        node = WorkflowNode("n1", "stub.echo", "1.0.0")
        node.state = NodeState.COMPLETED
        node.outputs = {"text": "hello"}
        node.reset()
        assert node.state == NodeState.IDLE
        assert node.outputs == {}

    def test_defaults(self) -> None:
        node = WorkflowNode("n1", "stub.echo", "1.0.0")
        assert node.parameters == {}
        assert node.state == NodeState.IDLE


class TestWorkflowGraph:
    def test_add_node(self) -> None:
        wf = Workflow()
        wf.add_node(WorkflowNode("a", "stub.echo", "1.0.0"))
        assert "a" in wf.nodes
        assert len(wf.nodes) == 1

    def test_add_duplicate_node_raises(self) -> None:
        wf = Workflow()
        wf.add_node(WorkflowNode("a", "stub.echo", "1.0.0"))
        with pytest.raises(ValueError, match="already exists"):
            wf.add_node(WorkflowNode("a", "stub.echo", "1.0.0"))

    def test_add_edge(self) -> None:
        wf = Workflow()
        wf.add_node(WorkflowNode("a", "stub.echo", "1.0.0"))
        wf.add_node(WorkflowNode("b", "stub.echo", "1.0.0"))
        wf.add_edge(WorkflowEdge("a", "text", "b", "text"))
        assert len(wf.edges) == 1

    def test_add_edge_bad_source_raises(self) -> None:
        wf = Workflow()
        wf.add_node(WorkflowNode("b", "stub.echo", "1.0.0"))
        with pytest.raises(ValueError, match="not found"):
            wf.add_edge(WorkflowEdge("nonexistent", "text", "b", "text"))

    def test_add_edge_bad_target_raises(self) -> None:
        wf = Workflow()
        wf.add_node(WorkflowNode("a", "stub.echo", "1.0.0"))
        with pytest.raises(ValueError, match="not found"):
            wf.add_edge(WorkflowEdge("a", "text", "nonexistent", "text"))

    def test_get_upstream_nodes(self) -> None:
        wf = Workflow()
        wf.add_node(WorkflowNode("a", "stub.echo", "1.0.0"))
        wf.add_node(WorkflowNode("b", "stub.echo", "1.0.0"))
        wf.add_node(WorkflowNode("c", "stub.echo", "1.0.0"))
        wf.add_edge(WorkflowEdge("a", "text", "c", "text"))
        wf.add_edge(WorkflowEdge("b", "text", "c", "text"))
        upstream = wf.get_upstream_nodes("c")
        assert set(upstream) == {"a", "b"}

    def test_get_downstream_nodes(self) -> None:
        wf = Workflow()
        wf.add_node(WorkflowNode("a", "stub.echo", "1.0.0"))
        wf.add_node(WorkflowNode("b", "stub.echo", "1.0.0"))
        wf.add_node(WorkflowNode("c", "stub.echo", "1.0.0"))
        wf.add_edge(WorkflowEdge("a", "text", "b", "text"))
        wf.add_edge(WorkflowEdge("a", "text", "c", "text"))
        downstream = wf.get_downstream_nodes("a")
        assert set(downstream) == {"b", "c"}


class TestTopologicalSort:
    def test_single_node(self) -> None:
        wf = Workflow()
        wf.add_node(WorkflowNode("a", "stub.echo", "1.0.0"))
        assert wf.topological_sort() == ["a"]

    def test_linear_chain(self) -> None:
        wf = Workflow()
        wf.add_node(WorkflowNode("a", "stub.echo", "1.0.0"))
        wf.add_node(WorkflowNode("b", "stub.echo", "1.0.0"))
        wf.add_node(WorkflowNode("c", "stub.echo", "1.0.0"))
        wf.add_edge(WorkflowEdge("a", "text", "b", "text"))
        wf.add_edge(WorkflowEdge("b", "text", "c", "text"))
        order = wf.topological_sort()
        assert order == ["a", "b", "c"]

    def test_diamond(self) -> None:
        wf = Workflow()
        wf.add_node(WorkflowNode("a", "stub.echo", "1.0.0"))
        wf.add_node(WorkflowNode("b", "stub.echo", "1.0.0"))
        wf.add_node(WorkflowNode("c", "stub.echo", "1.0.0"))
        wf.add_node(WorkflowNode("d", "stub.echo", "1.0.0"))
        wf.add_edge(WorkflowEdge("a", "text", "b", "text"))
        wf.add_edge(WorkflowEdge("a", "text", "c", "text"))
        wf.add_edge(WorkflowEdge("b", "text", "d", "text"))
        wf.add_edge(WorkflowEdge("c", "text", "d", "text"))
        order = wf.topological_sort()
        assert order[0] == "a"
        assert order[3] == "d"
        assert set(order[1:3]) == {"b", "c"}

    def test_cycle_detection(self) -> None:
        wf = Workflow()
        wf.add_node(WorkflowNode("a", "stub.echo", "1.0.0"))
        wf.add_node(WorkflowNode("b", "stub.echo", "1.0.0"))
        wf.add_edge(WorkflowEdge("a", "text", "b", "text"))
        wf.add_edge(WorkflowEdge("b", "text", "a", "text"))
        with pytest.raises(ValueError, match="cycle"):
            wf.topological_sort()

    def test_validate_acyclic_returns_cycle_nodes(self) -> None:
        wf = Workflow()
        wf.add_node(WorkflowNode("a", "stub.echo", "1.0.0"))
        wf.add_node(WorkflowNode("b", "stub.echo", "1.0.0"))
        wf.add_node(WorkflowNode("c", "stub.echo", "1.0.0"))
        wf.add_edge(WorkflowEdge("a", "text", "b", "text"))
        wf.add_edge(WorkflowEdge("b", "text", "c", "text"))
        wf.add_edge(WorkflowEdge("c", "text", "a", "text"))
        cycle = wf.validate_acyclic()
        assert set(cycle) == {"a", "b", "c"}

    def test_empty_workflow(self) -> None:
        wf = Workflow()
        assert wf.topological_sort() == []
        assert wf.validate_acyclic() == []

    def test_get_inputs_for_node(self) -> None:
        wf = Workflow()
        wf.add_node(WorkflowNode("a", "stub.echo", "1.0.0"))
        wf.add_node(WorkflowNode("b", "stub.echo", "1.0.0"))
        wf.nodes["a"].outputs = {"text": "hello"}
        wf.add_edge(WorkflowEdge("a", "text", "b", "text"))
        inputs = wf.get_inputs_for_node("b")
        assert inputs == {"text": "hello"}
