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
    algorithm_identity = {
        "build_residue_layout": {
            "name": "canonical-residue-layout-construction",
            "residue_identity": "<chain>:<one-based-generated-label>",
            "chain_boundary": "ordered-contiguous-chain-blocks",
        },
        "edit_residue_layout": {
            "name": "explicit-residue-identity-reconciliation",
            "mapping_operations": ["delete", "insert", "match"],
            "mapping_indexing": "zero-based-with-negative-unmapped-sentinel",
        },
        "map_residue_track": {
            "name": "explicit-residue-map-conversion",
            "nullable_semantics": "JSON null means unmapped or unspecified",
            "mapping_indexing": "zero-based",
        },
        "override_residue_track": {
            "name": "identity-addressed-track-override",
            "actions": ["clear", "preserve", "replace"],
            "nullable_semantics": "JSON null means unspecified",
        },
    }[operation]
    return MethodDefinition(
        method_id=f"prompt_authoring.{operation}.method",
        version=_VERSION,
        algorithm_identity=algorithm_identity,
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
    node_definitions=(
        DefinitionResource("definitions/build_residue_layout.yaml"),
        DefinitionResource("definitions/edit_residue_layout.yaml"),
        DefinitionResource("definitions/map_residue_track.yaml"),
        DefinitionResource("definitions/override_residue_track.yaml"),
    ),
    methods=tuple(_method(operation) for operation in _OPERATIONS),
    bindings=tuple(_binding(operation) for operation in _OPERATIONS),
)
