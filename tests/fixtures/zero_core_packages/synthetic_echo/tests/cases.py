"""Contract Test Kit inputs kept separate from production registration."""

from __future__ import annotations

from core.operation import (
    ArtifactPayload,
)
from tests.support.contract_test_kit import (
    ModulePackageContractCase,
    ModulePackagePortCase,
)
from core.workflow.document import WorkflowNodeInstance
from core.workflow.document import WorkflowEdge


SOURCE_EXECUTION_CASE = ModulePackageContractCase(
    case_id="synthetic-echo-candidate-source",
    node_type_id="contract_test.synthetic_candidate_source",
    node_type_version="1.0.0",
    binding_id="contract_test.synthetic_candidate_source.direct",
    binding_version="1.0.0",
    node_parameters={"message": "SOURCE"},
    binding_parameters={"repeat_count": 1},
    environment_values={
        "fixture_ready": True,
        "credential": "contract-test-secret-must-not-publish",
        "runtime_path": "/private/contract-test-runtime",
    },
    expected_scalar_outputs={"text": "SOURCE"},
    expected_candidate_counts={"candidates": 1},
    expected_artifacts={"artifact": b"SOURCE"},
    forbidden_public_fragments=(
        "contract-test-secret-must-not-publish",
        "/private/contract-test-runtime",
    ),
)


EXECUTION_CASE = ModulePackageContractCase(
    case_id="synthetic-echo-complete-journey",
    node_type_id="contract_test.synthetic_echo",
    node_type_version="4.0.0",
    binding_id="contract_test.synthetic_echo.direct",
    binding_version="4.0.0",
    node_parameters={"message": "ECHO"},
    binding_parameters={"repeat_count": 2},
    environment_values={
        "fixture_ready": True,
        "credential": "contract-test-secret-must-not-publish",
        "runtime_path": "/private/contract-test-runtime",
    },
    workflow_nodes=(
        WorkflowNodeInstance(
            node_id="candidate-source",
            node_type_id="contract_test.synthetic_candidate_source",
            node_type_version="1.0.0",
            binding_id="contract_test.synthetic_candidate_source.direct",
            binding_version="1.0.0",
            node_parameters={"message": "SOURCE"},
            binding_parameters={"repeat_count": 1},
        ),
    ),
    workflow_edges=(
        WorkflowEdge(
            source_node_id="candidate-source",
            source_port="candidates",
            target_node_id="contract-test-node",
            target_port="candidate_input",
        ),
    ),
    expected_scalar_outputs={"text": "ECHOECHO"},
    expected_candidate_counts={"candidates": 1},
    expected_observation_counts={"scores": 1},
    expected_artifacts={"artifact": b"ECHOECHO"},
    forbidden_public_fragments=(
        "contract-test-secret-must-not-publish",
        "/private/contract-test-runtime",
    ),
)

PORT_CASE = ModulePackagePortCase(
    type_id="contract_test.synthetic_text",
    version="2.1.0",
    valid_value="canonical echo",
    invalid_values=("", 7),
)

ARTIFACT_PORT_CASE = ModulePackagePortCase(
    type_id="contract_test.synthetic_artifact",
    version="2.1.0",
    valid_value=ArtifactPayload(
        body=b"fixture",
        media_type="text/plain",
        filename="result.txt",
    ),
    invalid_values=(b"fixture", "result.txt"),
)
