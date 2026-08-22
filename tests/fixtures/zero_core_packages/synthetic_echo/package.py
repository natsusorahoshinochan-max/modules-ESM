"""The one production registration for the synthetic contract package."""

from __future__ import annotations

from collections.abc import Callable, Mapping
import base64

from core.catalog.declarations import (
    AvailabilityDeclaration,
    AvailabilityResult,
    ContractIdentity,
    EnvironmentFieldDeclaration,
    ExecutionBindingDefinition,
    MethodDefinition,
    ModulePackageRegistration,
    ProducedObservationDefinition,
    ReadinessDeclaration,
    ScientificOperationFactory,
    UtilityTransformDefinition,
)
from core.catalog.definition_resource import (
    DefinitionResource,
)
from core.catalog.port_contract import (
    BehaviorReference,
    PortTypeDefinition,
)
from core.operation import (
    ArtifactPayload,
    OperationContext,
    ReadinessCheckInput,
    ReadinessResult,
)

from .implementation import (
    SyntheticCandidateSourceImplementation,
    SyntheticEchoScorerImplementation,
)


_SOURCE_NODE_TYPE_ID = "contract_test.synthetic_candidate_source"
_SOURCE_VERSION = "1.0.0"
_SCORER_NODE_TYPE_ID = "contract_test.synthetic_echo"
_SCORER_VERSION = "4.0.0"
_SOURCE_METHOD = ContractIdentity(
    "method",
    "contract_test.synthetic_candidate_source.method",
    "1.0.0",
)
_METHOD = ContractIdentity(
    "method",
    "contract_test.synthetic_echo.method",
    "2.1.0",
)
_METRIC = ContractIdentity(
    "metric",
    "contract_test.synthetic_identity",
    "2.1.0",
)


def _validate_text(value: object) -> None:
    if type(value) is not str or not value:
        raise ValueError("synthetic text must be a non-empty string")


def _validate_artifact(value: object) -> None:
    if (
        type(value) is not ArtifactPayload
        or value.media_type != "text/plain"
        or value.filename != "result.txt"
        or value.candidate_id is not None
    ):
        raise ValueError("synthetic artifact is invalid")


def _artifact_to_wire(value: object) -> object:
    assert isinstance(value, ArtifactPayload)
    return {
        "body_base64": base64.b64encode(value.body).decode("ascii"),
        "media_type": value.media_type,
        "filename": value.filename,
        "candidate_id": value.candidate_id,
    }


def _artifact_from_wire(value: object) -> object:
    if not isinstance(value, dict) or set(value) != {
        "body_base64",
        "media_type",
        "filename",
        "candidate_id",
    }:
        raise ValueError("synthetic artifact wire value is invalid")
    return ArtifactPayload(
        body=base64.b64decode(value["body_base64"], validate=True),
        media_type=value["media_type"],
        filename=value["filename"],
        candidate_id=value["candidate_id"],
    )


def _identity(value: object, parameters: object) -> float:
    if parameters != {}:
        raise ValueError("identity Utility Transform takes no parameters")
    return float(value)


def _available() -> AvailabilityResult:
    return AvailabilityResult.available()


def _ready(check_input: ReadinessCheckInput) -> ReadinessResult:
    return ReadinessResult(
        check_input.values.get("fixture_ready") is True
    )


def _source_ready(check_input: ReadinessCheckInput) -> ReadinessResult:
    del check_input
    return ReadinessResult(True)


def _build_source(
    context: OperationContext,
) -> SyntheticCandidateSourceImplementation:
    if context.produced_observations:
        raise ValueError("synthetic Candidate source declares no Observations")
    return SyntheticCandidateSourceImplementation(
        run_resources=context.resources,
        environment=context.environment,
    )


def _build_scorer(
    context: OperationContext,
) -> SyntheticEchoScorerImplementation:
    observation = context.produced_observations[0]
    return SyntheticEchoScorerImplementation(
        run_resources=context.resources,
        environment=context.environment,
        metric=observation.metric,
        method=context.method,
    )


def _binding(
    binding_id: str,
    *,
    version: str,
    node_type_id: str,
    method: ContractIdentity,
    build: Callable[
        [OperationContext],
        SyntheticCandidateSourceImplementation
        | SyntheticEchoScorerImplementation,
    ],
    produced_observations: tuple[ProducedObservationDefinition, ...],
    requires_fixture_ready: bool,
) -> ExecutionBindingDefinition:
    behavior_prefix = binding_id.replace(".", "/")
    return ExecutionBindingDefinition(
        binding_id=binding_id,
        version=version,
        node_type=ContractIdentity(
            "node_type",
            node_type_id,
            version,
        ),
        method=method,
        binding_parameters={
            "repeat_count": {
                "parameter_scope": "scientific",
                "scientific_meaning": (
                    "Exact number of deterministic echo repetitions."
                ),
                "required": True,
                "value_contract": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 3,
                },
            }
        },
        environment_fields=(
            EnvironmentFieldDeclaration("fixture_ready", "json_value"),
            EnvironmentFieldDeclaration("credential", "credential_handle"),
            EnvironmentFieldDeclaration("runtime_path", "filesystem_path"),
            EnvironmentFieldDeclaration(
                "block_marker",
                "filesystem_path",
                required=False,
            ),
        ),
        execution_route="direct",
        factory=ScientificOperationFactory(
            behavior=BehaviorReference(
                f"{behavior_prefix}/factory",
                version,
                {"execution_route": "direct"},
            ),
            build=build,
        ),
        availability=AvailabilityDeclaration(
            behavior=BehaviorReference(
                f"{behavior_prefix}/availability",
                version,
                {"observation": "startup"},
            ),
            prerequisites={},
            check=_available,
        ),
        readiness=ReadinessDeclaration(
            behavior=BehaviorReference(
                f"{behavior_prefix}/readiness",
                version,
                {"observation": "per-run"},
            ),
            prerequisites=(
                {"fixture_ready": "required"}
                if requires_fixture_ready
                else {}
            ),
            check=_ready if requires_fixture_ready else _source_ready,
        ),
        deterministic=True,
        cacheable=False,
        implementation_identity={
            "name": binding_id,
            "source": "repository-contract-fixture",
        },
        produced_observations=produced_observations,
    )


MODULE_PACKAGE = ModulePackageRegistration(
    schema_version="2.1.0",
    package_id="contract_test.synthetic_echo",
    package_version="2.1.0",
    package_module=__package__,
    node_definitions=(
        DefinitionResource("definitions/candidate_source.yaml"),
        DefinitionResource("definitions/echo.yaml"),
    ),
    metric_definitions=(
        DefinitionResource("definitions/identity_metric.yaml"),
    ),
    methods=(
        MethodDefinition(
            method_id="contract_test.synthetic_candidate_source.method",
            version="1.0.0",
            algorithm_identity={"name": "deterministic-candidate-source"},
            model_identity={"kind": "none"},
            checkpoint_identity={"kind": "none"},
            featurization_identity={"kind": "identity"},
            source_identity={"kind": "contract-test-fixture"},
            scale_contract={"kind": "none"},
        ),
        MethodDefinition(
            method_id="contract_test.synthetic_echo.method",
            version="2.1.0",
            algorithm_identity={"name": "deterministic-echo"},
            model_identity={"kind": "none"},
            checkpoint_identity={"kind": "none"},
            featurization_identity={"kind": "identity"},
            source_identity={"kind": "contract-test-fixture"},
            scale_contract={"kind": "identity"},
        ),
    ),
    bindings=(
        _binding(
            "contract_test.synthetic_candidate_source.direct",
            version=_SOURCE_VERSION,
            node_type_id=_SOURCE_NODE_TYPE_ID,
            method=_SOURCE_METHOD,
            build=_build_source,
            produced_observations=(),
            requires_fixture_ready=False,
        ),
        _binding(
            "contract_test.synthetic_echo.direct",
            version=_SCORER_VERSION,
            node_type_id=_SCORER_NODE_TYPE_ID,
            method=_METHOD,
            build=_build_scorer,
            produced_observations=(
                ProducedObservationDefinition(
                    output_port="scores",
                    output_partition="default",
                    metric=_METRIC,
                    context_profile={"kind": "intrinsic"},
                    subject_grain="candidate",
                    source_role="subject",
                    subject_direction="input",
                    subject_port="candidate_input",
                    guaranteed_multiplicity="one",
                ),
            ),
            requires_fixture_ready=True,
        ),
    ),
    port_types=(
        PortTypeDefinition(
            type_id="contract_test.synthetic_text",
            version="2.1.0",
            validator=BehaviorReference(
                "contract_test.synthetic_text/validate",
                "2.1.0",
                {"accepted_value_kind": "text"},
            ),
            codec=BehaviorReference(
                "contract_test.synthetic_text/codec",
                "2.1.0",
                {"canonicalization": "RFC 8785"},
            ),
            content_identity=BehaviorReference(
                "contract_test.synthetic_text/content",
                "2.1.0",
                {"digest": "SHA-256"},
            ),
            runtime_validator=_validate_text,
            runtime_to_wire=lambda value: value,
            runtime_from_wire=lambda value: value,
        ),
        PortTypeDefinition(
            type_id="contract_test.synthetic_artifact",
            version="2.1.0",
            validator=BehaviorReference(
                "contract_test.synthetic_artifact/validate",
                "2.1.0",
                {
                    "accepted_value_kind": "artifact_payload",
                    "artifact_publication": {
                        "media_types": ["text/plain"],
                    },
                },
            ),
            codec=BehaviorReference(
                "contract_test.synthetic_artifact/codec",
                "2.1.0",
                {
                    "canonicalization": "RFC 8785",
                    "binary_encoding": "base64",
                },
            ),
            content_identity=BehaviorReference(
                "contract_test.synthetic_artifact/content",
                "2.1.0",
                {"digest": "SHA-256"},
            ),
            runtime_validator=_validate_artifact,
            runtime_to_wire=_artifact_to_wire,
            runtime_from_wire=_artifact_from_wire,
        ),
    ),
    utility_transforms=(
        UtilityTransformDefinition(
            transform_id="contract_test.synthetic_identity",
            version="2.1.0",
            compatible_input_contract={
                "metric": _METRIC,
                "method": _METHOD,
            },
            parameters={},
            behavior=BehaviorReference(
                "contract_test.synthetic_identity/transform",
                "2.1.0",
                {},
            ),
            transform=_identity,
        ),
    ),
)
