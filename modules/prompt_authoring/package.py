"""The single production registration for prompt authoring."""

from __future__ import annotations

from core import (
    AvailabilityDeclaration,
    AvailabilityResult,
    BehaviorReference,
    ContractIdentity,
    DefinitionResource,
    ExecutionBindingDefinition,
    LazyImplementationFactory,
    MethodDefinition,
    ModulePackageRegistration,
    ReadinessDeclaration,
)

from .implementation import (
    BuildResidueLayoutImplementation,
    EditResidueLayoutImplementation,
    MapResidueTrackImplementation,
    OverrideResidueTrackImplementation,
)


_VERSION = "2.0.0"
_OPERATIONS = (
    "build_residue_layout",
    "edit_residue_layout",
    "map_residue_track",
    "override_residue_track",
)
_IMPLEMENTATIONS = {
    "build_residue_layout": BuildResidueLayoutImplementation,
    "edit_residue_layout": EditResidueLayoutImplementation,
    "map_residue_track": MapResidueTrackImplementation,
    "override_residue_track": OverrideResidueTrackImplementation,
}


def _available() -> AvailabilityResult:
    return AvailabilityResult.available()


def _ready(environment: object) -> bool:
    del environment
    return True


def _build(operation: str):
    def factory(**kwargs: object) -> object:
        implementation = _IMPLEMENTATIONS[operation]
        return implementation(kwargs["run_resources"], operation)

    return factory


def _method(operation: str) -> MethodDefinition:
    algorithm = {
        "build_residue_layout": "canonical-residue-layout-construction",
        "edit_residue_layout": "explicit-residue-identity-reconciliation",
        "map_residue_track": "explicit-residue-map-conversion",
        "override_residue_track": "identity-addressed-track-override",
    }[operation]
    return MethodDefinition(
        method_id=f"prompt_authoring.{operation}.method",
        version=_VERSION,
        algorithm_identity={
            "name": algorithm,
            "indexing": "zero-based-internal-residue-map",
            "nullable_semantics": "JSON null means unspecified",
        },
        model_identity={"kind": "none"},
        checkpoint_identity={"kind": "none"},
        featurization_identity={
            "residue_identity": "<chain>:<label>",
            "chain_boundary": "contiguous",
        },
        source_identity={"kind": "repository-owned"},
        scale_contract={"kind": "identity"},
    )


def _binding(operation: str) -> ExecutionBindingDefinition:
    return ExecutionBindingDefinition(
        binding_id=f"prompt_authoring.{operation}.direct",
        version=_VERSION,
        node_type=ContractIdentity(
            "node_type",
            f"prompt_authoring.{operation}",
            _VERSION,
        ),
        method=ContractIdentity(
            "method",
            f"prompt_authoring.{operation}.method",
            _VERSION,
        ),
        binding_parameters={},
        execution_route="direct",
        factory=LazyImplementationFactory(
            behavior=BehaviorReference(
                f"prompt_authoring.{operation}/factory",
                _VERSION,
                {"execution_route": "direct"},
            ),
            build=_build(operation),
        ),
        availability=AvailabilityDeclaration(
            behavior=BehaviorReference(
                f"prompt_authoring.{operation}/availability",
                _VERSION,
                {"observation": "startup"},
            ),
            prerequisites={},
            check=_available,
        ),
        readiness=ReadinessDeclaration(
            behavior=BehaviorReference(
                f"prompt_authoring.{operation}/readiness",
                _VERSION,
                {"observation": "per-run"},
            ),
            prerequisites={},
            check=_ready,
        ),
        deterministic=True,
        cacheable=True,
        implementation_identity={
            "name": f"prompt_authoring.{operation}.direct",
            "source": "repository-owned",
        },
    )


MODULE_PACKAGE = ModulePackageRegistration(
    schema_version=_VERSION,
    package_id="prompt_authoring",
    package_version=_VERSION,
    package_module=__package__,
    node_definitions=tuple(
        DefinitionResource(f"definitions/{operation}.yaml")
        for operation in _OPERATIONS
    ),
    methods=tuple(_method(operation) for operation in _OPERATIONS),
    bindings=tuple(_binding(operation) for operation in _OPERATIONS),
)
