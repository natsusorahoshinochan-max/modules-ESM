"""The one production registration for the synthetic contract package."""

from __future__ import annotations

from collections.abc import Mapping
import base64

from core import (
    ArtifactPayload,
    AvailabilityDeclaration,
    AvailabilityResult,
    BehaviorReference,
    ContractIdentity,
    DefinitionResource,
    ExecutionBindingDefinition,
    MethodDefinition,
    ModulePackageRegistration,
    OperationContext,
    PortTypeDefinition,
    ProducedObservationDefinition,
    ReadinessCheckInput,
    ReadinessDeclaration,
    ReadinessResult,
    ScientificOperationFactory,
    UtilityTransformDefinition,
)

from .implementation import SyntheticEchoImplementation


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


def _build(context: OperationContext) -> SyntheticEchoImplementation:
    observation = context.produced_observations[0]
    return SyntheticEchoImplementation(
        run_resources=context.resources,
        environment=context.environment,
        metric=observation.metric,
        method=context.method,
    )


MODULE_PACKAGE = ModulePackageRegistration(
    schema_version="2.1.0",
    package_id="contract_test.synthetic_echo",
    package_version="2.1.0",
    package_module=__package__,
    node_definitions=(DefinitionResource("definitions/echo.yaml"),),
    metric_definitions=(
        DefinitionResource("definitions/identity_metric.yaml"),
    ),
    methods=(
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
        ExecutionBindingDefinition(
            binding_id="contract_test.synthetic_echo.direct",
            version="2.1.0",
            node_type=ContractIdentity(
                "node_type",
                "contract_test.synthetic_echo",
                "2.1.0",
            ),
            method=_METHOD,
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
            execution_route="direct",
            factory=ScientificOperationFactory(
                behavior=BehaviorReference(
                    "contract_test.synthetic_echo/factory",
                    "2.1.0",
                    {"execution_route": "direct"},
                ),
                build=_build,
            ),
            availability=AvailabilityDeclaration(
                behavior=BehaviorReference(
                    "contract_test.synthetic_echo/availability",
                    "2.1.0",
                    {"observation": "startup"},
                ),
                prerequisites={},
                check=_available,
            ),
            readiness=ReadinessDeclaration(
                behavior=BehaviorReference(
                    "contract_test.synthetic_echo/readiness",
                    "2.1.0",
                    {"observation": "per-run"},
                ),
                prerequisites={"fixture_ready": "required"},
                check=_ready,
            ),
            deterministic=True,
            cacheable=False,
            implementation_identity={
                "name": "contract_test.synthetic_echo.direct",
                "source": "repository-contract-fixture",
            },
            produced_observations=(
                ProducedObservationDefinition(
                    output_port="scores",
                    metric=_METRIC,
                    context_profile={"kind": "intrinsic"},
                    subject_grain="candidate",
                    source_role="subject",
                    subject_direction="output",
                    subject_port="candidates",
                    guaranteed_multiplicity="one",
                ),
            ),
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
