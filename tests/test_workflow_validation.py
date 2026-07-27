"""Public contract tests for authoritative Workflow validation."""

from core import (
    InputGroupDefinition,
    ModuleDefinition,
    ModuleRegistry,
    PortDefinition,
    TypeRegistry,
    Workflow,
    WorkflowEdge,
    WorkflowNode,
)


def _registry(*definitions: ModuleDefinition) -> ModuleRegistry:
    registry = ModuleRegistry(TypeRegistry())
    for definition in definitions:
        registry.register(definition)
    return registry


def _module(
    module_id: str,
    *,
    version: str = "1.0.0",
    inputs: list[PortDefinition] | None = None,
    input_groups: list[InputGroupDefinition] | None = None,
    outputs: list[PortDefinition] | None = None,
) -> ModuleDefinition:
    return ModuleDefinition(
        module_id=module_id,
        version=version,
        display_name=module_id,
        category="input",
        input_ports=inputs or [],
        input_groups=input_groups or [],
        output_ports=outputs or [],
    )


def test_validation_reports_missing_required_input_with_stable_context() -> None:
    workflow = Workflow()
    workflow.add_node(WorkflowNode("consumer", "test.consumer", "1.0.0"))
    registry = _registry(
        _module(
            "test.consumer",
            inputs=[PortDefinition("sequence", "protein.sequence", required=True)],
        )
    )

    result = workflow.validate(registry)

    assert result.to_dict() == {
        "valid": False,
        "errors": [
            {
                "kind": "required_input_missing",
                "message": "Required input Port 'sequence' is not connected",
                "node_id": "consumer",
                "module_id": "test.consumer",
                "port": "sequence",
            }
        ],
    }


def test_validation_reports_unavailable_module() -> None:
    workflow = Workflow()
    workflow.add_node(WorkflowNode("generate", "missing.provider", "1.0.0"))

    result = workflow.validate(_registry())

    assert result.to_dict() == {
        "valid": False,
        "errors": [
            {
                "kind": "module_unavailable",
                "message": "Module 'missing.provider' is not available",
                "node_id": "generate",
                "module_id": "missing.provider",
            }
        ],
    }


def test_validation_reports_module_version_mismatch() -> None:
    workflow = Workflow()
    workflow.add_node(WorkflowNode("generate", "test.generator", "1.9.0"))

    result = workflow.validate(_registry(_module("test.generator", version="2.0.0")))

    assert result.errors[0].to_dict() == {
        "kind": "module_version_mismatch",
        "message": (
            "Node requires Module 'test.generator' version '1.9.0'; "
            "available version is '2.0.0'"
        ),
        "node_id": "generate",
        "module_id": "test.generator",
    }


def test_validation_reports_missing_source_port() -> None:
    workflow = Workflow()
    workflow.add_node(WorkflowNode("source", "test.source", "1.0.0"))
    workflow.add_node(WorkflowNode("target", "test.target", "1.0.0"))
    workflow.add_edge(WorkflowEdge("source", "missing", "target", "sequence"))
    registry = _registry(
        _module(
            "test.source",
            outputs=[PortDefinition("sequence", "protein.sequence")],
        ),
        _module(
            "test.target",
            inputs=[PortDefinition("sequence", "protein.sequence")],
        ),
    )

    result = workflow.validate(registry)

    assert result.errors[0].to_dict() == {
        "kind": "source_port_not_found",
        "message": "Source Port 'missing' is not declared by Module 'test.source'",
        "node_id": "source",
        "module_id": "test.source",
        "port": "missing",
    }


def test_validation_reports_missing_target_port() -> None:
    workflow = Workflow()
    workflow.add_node(WorkflowNode("source", "test.source", "1.0.0"))
    workflow.add_node(WorkflowNode("target", "test.target", "1.0.0"))
    workflow.add_edge(WorkflowEdge("source", "sequence", "target", "missing"))
    registry = _registry(
        _module(
            "test.source",
            outputs=[PortDefinition("sequence", "protein.sequence")],
        ),
        _module(
            "test.target",
            inputs=[PortDefinition("sequence", "protein.sequence")],
        ),
    )

    result = workflow.validate(registry)

    assert result.errors[0].to_dict() == {
        "kind": "target_port_not_found",
        "message": "Target Port 'missing' is not declared by Module 'test.target'",
        "node_id": "target",
        "module_id": "test.target",
        "port": "missing",
    }


def test_validation_rejects_unequal_type_ids_without_implicit_conversion() -> None:
    workflow = Workflow()
    workflow.add_node(WorkflowNode("source", "test.source", "1.0.0"))
    workflow.add_node(WorkflowNode("target", "test.target", "1.0.0"))
    workflow.add_edge(WorkflowEdge("source", "sequence", "target", "structure"))
    registry = _registry(
        _module(
            "test.source",
            outputs=[PortDefinition("sequence", "protein.sequence")],
        ),
        _module(
            "test.target",
            inputs=[PortDefinition("structure", "protein.structure")],
        ),
    )

    result = workflow.validate(registry)

    assert result.errors[0].to_dict() == {
        "kind": "port_type_mismatch",
        "message": (
            "Source Port type 'protein.sequence' does not exactly match "
            "target Port type 'protein.structure'"
        ),
        "node_id": "target",
        "module_id": "test.target",
        "port": "structure",
    }


def test_validation_reports_cycle_nodes() -> None:
    workflow = Workflow()
    workflow.add_node(WorkflowNode("a", "test.echo", "1.0.0"))
    workflow.add_node(WorkflowNode("b", "test.echo", "1.0.0"))
    workflow.add_edge(WorkflowEdge("a", "text", "b", "text"))
    workflow.add_edge(WorkflowEdge("b", "text", "a", "text"))
    registry = _registry(
        _module(
            "test.echo",
            inputs=[PortDefinition("text", "text")],
            outputs=[PortDefinition("text", "text")],
        )
    )

    result = workflow.validate(registry)

    assert [error.to_dict() for error in result.errors] == [
        {
            "kind": "workflow_cycle",
            "message": "Node participates in a Workflow cycle",
            "node_id": "a",
            "module_id": "test.echo",
        },
        {
            "kind": "workflow_cycle",
            "message": "Node participates in a Workflow cycle",
            "node_id": "b",
            "module_id": "test.echo",
        },
    ]


def test_validation_does_not_report_downstream_node_as_part_of_cycle() -> None:
    workflow = Workflow()
    for node_id in ("a", "b", "downstream"):
        workflow.add_node(WorkflowNode(node_id, "test.echo", "1.0.0"))
    workflow.add_edge(WorkflowEdge("a", "text", "b", "text"))
    workflow.add_edge(WorkflowEdge("b", "text", "a", "text"))
    workflow.add_edge(WorkflowEdge("b", "text", "downstream", "text"))
    registry = _registry(
        _module(
            "test.echo",
            inputs=[PortDefinition("text", "text")],
            outputs=[PortDefinition("text", "text")],
        )
    )

    result = workflow.validate(registry)

    cycle_node_ids = [
        error.node_id for error in result.errors
        if error.kind == "workflow_cycle"
    ]
    assert cycle_node_ids == ["a", "b"]


def test_validation_rejects_duplicate_connections_to_single_input_port() -> None:
    workflow = Workflow()
    workflow.add_node(WorkflowNode("left", "test.source", "1.0.0"))
    workflow.add_node(WorkflowNode("right", "test.source", "1.0.0"))
    workflow.add_node(WorkflowNode("target", "test.target", "1.0.0"))
    workflow.add_edge(WorkflowEdge("left", "text", "target", "text"))
    workflow.add_edge(WorkflowEdge("right", "text", "target", "text"))
    registry = _registry(
        _module("test.source", outputs=[PortDefinition("text", "text")]),
        _module("test.target", inputs=[PortDefinition("text", "text")]),
    )

    result = workflow.validate(registry)

    assert result.errors[0].to_dict() == {
        "kind": "duplicate_input_connection",
        "message": "Input Port 'text' accepts only one connection",
        "node_id": "target",
        "module_id": "test.target",
        "port": "text",
    }


def test_validation_accepts_unconnected_optional_input() -> None:
    workflow = Workflow()
    workflow.add_node(WorkflowNode("consumer", "test.consumer", "1.0.0"))
    registry = _registry(
        _module(
            "test.consumer",
            inputs=[
                PortDefinition(
                    "reference",
                    "protein.sequence",
                    required=False,
                )
            ],
        )
    )

    assert workflow.validate(registry).to_dict() == {
        "valid": True,
        "errors": [],
    }


def test_validation_accepts_exactly_typed_acyclic_workflow() -> None:
    workflow = Workflow()
    workflow.add_node(WorkflowNode("source", "test.source", "1.0.0"))
    workflow.add_node(WorkflowNode("target", "test.target", "1.0.0"))
    workflow.add_edge(WorkflowEdge("source", "sequence", "target", "sequence"))
    registry = _registry(
        _module(
            "test.source",
            outputs=[PortDefinition("sequence", "protein.sequence")],
        ),
        _module(
            "test.target",
            inputs=[PortDefinition("sequence", "protein.sequence")],
        ),
    )

    assert workflow.validate(registry).to_dict() == {
        "valid": True,
        "errors": [],
    }


def test_validation_requires_one_complete_input_group_alternative() -> None:
    workflow = Workflow()
    workflow.add_node(WorkflowNode("fold", "test.fold", "1.0.0"))
    registry = _registry(
        _module(
            "test.fold",
            inputs=[
                PortDefinition("sequence", "protein.sequence", required=False),
                PortDefinition("candidates", "candidate.collection", required=False),
            ],
            input_groups=[
                InputGroupDefinition(
                    name="fold_input",
                    alternatives=(("sequence",), ("candidates",)),
                )
            ],
        )
    )

    result = workflow.validate(registry)

    assert result.errors[0].to_dict() == {
        "kind": "required_input_group_missing",
        "message": (
            "Input group 'fold_input' requires one complete alternative: "
            "(sequence) or (candidates)"
        ),
        "node_id": "fold",
        "module_id": "test.fold",
        "ports": ["sequence", "candidates"],
    }


def test_validation_rejects_conflicting_input_group_alternatives() -> None:
    workflow = Workflow()
    workflow.add_node(WorkflowNode("sequence", "test.sequence", "1.0.0"))
    workflow.add_node(WorkflowNode("candidates", "test.candidates", "1.0.0"))
    workflow.add_node(WorkflowNode("fold", "test.fold", "1.0.0"))
    workflow.add_edge(WorkflowEdge("sequence", "value", "fold", "sequence"))
    workflow.add_edge(WorkflowEdge("candidates", "value", "fold", "candidates"))
    registry = _registry(
        _module(
            "test.sequence",
            outputs=[PortDefinition("value", "protein.sequence")],
        ),
        _module(
            "test.candidates",
            outputs=[PortDefinition("value", "candidate.collection")],
        ),
        _module(
            "test.fold",
            inputs=[
                PortDefinition("sequence", "protein.sequence", required=False),
                PortDefinition("candidates", "candidate.collection", required=False),
            ],
            input_groups=[
                InputGroupDefinition(
                    name="fold_input",
                    alternatives=(("sequence",), ("candidates",)),
                )
            ],
        ),
    )

    result = workflow.validate(registry)

    assert result.errors[0].to_dict() == {
        "kind": "conflicting_input_connections",
        "message": (
            "Input group 'fold_input' accepts only one alternative: "
            "(sequence) or (candidates)"
        ),
        "node_id": "fold",
        "module_id": "test.fold",
        "ports": ["sequence", "candidates"],
    }
