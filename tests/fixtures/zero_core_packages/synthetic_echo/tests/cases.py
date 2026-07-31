"""Contract Test Kit inputs kept separate from production registration."""

from __future__ import annotations

from core import ArtifactPayload, ModulePackageContractCase, ModulePackagePortCase


EXECUTION_CASE = ModulePackageContractCase(
    case_id="synthetic-echo-complete-journey",
    node_type_id="contract_test.synthetic_echo",
    node_type_version="2.1.0",
    binding_id="contract_test.synthetic_echo.direct",
    binding_version="2.1.0",
    node_parameters={"message": "ECHO"},
    binding_parameters={"repeat_count": 2},
    environment_values={
        "fixture_ready": True,
        "credential": "contract-test-secret-must-not-publish",
        "runtime_path": "/private/contract-test-runtime",
    },
    safe_environment_fingerprint="synthetic-echo-environment-v1",
    invalidation_token="synthetic-echo-assets-v1",
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
