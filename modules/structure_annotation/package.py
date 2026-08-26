"""The single production registration for structure annotations."""

from __future__ import annotations

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
)
from core.catalog.definition_resource import DefinitionResource, load_method_definitions
from core.catalog.port_contract import BehaviorReference
from core.operation import (
    BindingEnvironment,
    OperationContext,
    ReadinessResult,
    ScientificOperation,
)

from .adapter import (
    MKDSSP_BINARY,
    MkdsspAdapter,
    mkdssp_readiness,
)
from .implementation import (
    ApplySASAToPromptOperation,
    ApplySecondaryStructureToPromptOperation,
    DSSPComputeOperation,
    ExpectedSecondaryStructureFromPromptOperation,
    SASAComputeOperation,
    SecondaryStructureAgreementOperation,
    SecondaryStructureExtractOperation,
)
from .port_types import STRUCTURE_ANNOTATION_PORT_TYPES


_OPERATIONS = (
    "dssp_compute",
    "secondary_structure_extract",
    "sasa_compute",
    "secondary_structure_agreement",
    "apply_secondary_structure_to_prompt",
    "apply_sasa_to_prompt",
    "expected_secondary_structure_from_prompt",
)
_DSSP_OPERATION = "dssp_compute"


def _dssp_ready(check_input: BindingEnvironment) -> ReadinessResult:
    return mkdssp_readiness(check_input.values)


def _build(operation: str):
    def factory(context: OperationContext) -> ScientificOperation:
        if operation == "dssp_compute":
            return DSSPComputeOperation(
                MkdsspAdapter(
                    environment=context.environment,
                    resources=context.resources,
                )
            )
        if operation == "secondary_structure_extract":
            return SecondaryStructureExtractOperation(context.resources)
        if operation == "sasa_compute":
            return SASAComputeOperation(context.resources)
        if operation == "secondary_structure_agreement":
            return SecondaryStructureAgreementOperation(
                resources=context.resources,
                method=context.method,
                produced_observation=context.produced_observations[0],
            )
        if operation == "apply_secondary_structure_to_prompt":
            return ApplySecondaryStructureToPromptOperation(context.resources)
        if operation == "apply_sasa_to_prompt":
            return ApplySASAToPromptOperation(context.resources)
        return ExpectedSecondaryStructureFromPromptOperation(
            context.resources
        )

    return factory


def _dssp_method() -> MethodDefinition:
    return MethodDefinition(
        method_id="structure_annotation.dssp_compute.method",
        algorithm_identity={
            "name": "mkdssp-residue-annotation",
            "binary": {
                "name": MKDSSP_BINARY,
            },
            "residue_correspondence": (
                "dssp-summary-label-pair-via-atom-site-authored-chain-"
                "signed-residue-and-insertion-code-to-authoritative-axis"
            ),
            "missing_value": "_",
            "coil_conversion": "mkdssp mmCIF '.' to SS8 C",
            "secondary_absent_marker": "?",
            "accessibility_absent_markers": [".", "?"],
        },
        model_identity={"kind": "none"},
        featurization_identity={
            "input": (
                "singleton ProteinStructure Candidate and authoritative "
                "resolved residue axis joined by exact admitted "
                "CandidateDataReference"
            ),
            "structure_format": "PDB-v3.3-fixed-columns",
            "provider_output_format": "mkdssp-mmCIF",
            "residue_mapping": (
                "dssp_struct_summary-label-asym-and-seq-joined-through-"
                "atom_site-auth-asym-auth-seq-and-PDB-ins-code-to-"
                "exact-authoritative-axis-identity"
            ),
        },
        scale_contract={"kind": "identity"},
    )


STATIC_METHODS = load_method_definitions(
    __package__,
    "definitions/methods.yaml",
)


def _binding(operation: str) -> ExecutionBindingDefinition:
    method = ContractIdentity(
        "method",
        f"structure_annotation.{operation}.method",
    )
    produced = ()
    if operation == "secondary_structure_agreement":
        produced = (
            ProducedObservationDefinition(
                output_port="scores",
                output_partition="default",
                metric=ContractIdentity(
                    "metric",
                    "structure_annotation.secondary_structure_agreement",
                ),
                context_profile={
                    "kind": "pairwise",
                    "subject_role": "subject",
                    "reference_role": "reference",
                    "pairing_mode": "fixed_reference",
                    "normalization": "exact-SS8-present-residue",
                },
                subject_grain="candidate",
                source_role="subject",
                subject_direction="input",
                subject_port="subjects",
                reference_direction="input",
                reference_port="references",
                axis_direction="input",
                axis_port="subject_residue_axes",
                guaranteed_multiplicity="one",
            ),
        )
    is_dssp = operation == _DSSP_OPERATION
    route = "mkdssp_local" if is_dssp else "direct"
    execution_route = "adapter" if is_dssp else "direct"
    return ExecutionBindingDefinition(
        binding_id=f"structure_annotation.{operation}.{route}",
        node_type=ContractIdentity(
            "node_type",
            f"structure_annotation.{operation}",
        ),
        method=method,
        binding_parameters={},
        environment_fields=(
            (EnvironmentFieldDeclaration("dssp_binary", "filesystem_path"),)
            if is_dssp
            else ()
        ),
        execution_route=execution_route,
        factory=ScientificOperationFactory(
            behavior=BehaviorReference(
                f"structure_annotation.{operation}/factory",
                {"execution_route": execution_route, "route": route},
            ),
            build=_build(operation),
        ),
        adapter_behavior=(
            BehaviorReference(
                "structure_annotation.mkdssp_local/adapter",
                {
                    "provider_contract": "mkdssp",
                    "binary": MKDSSP_BINARY,
                    "request_format": "PDB-v3.3-fixed-columns",
                    "response_format": "mkdssp-mmCIF",
                    "axis_source": (
                        "exact-candidate-associated-authoritative-"
                        "resolved-residue-axis"
                    ),
                    "residue_reconciliation": (
                        "dssp-summary-label-pair-via-atom-site-auth-fields-"
                        "to-authoritative-axis-exact-identity"
                    ),
                },
            )
            if is_dssp
            else None
        ),
        availability=AvailabilityDeclaration(
            behavior=BehaviorReference(
                f"structure_annotation.{operation}/availability",
                {"observation": "startup"},
            ),
            prerequisites=(
                {
                    "binary_configuration": {
                        "name": MKDSSP_BINARY,
                        "path_source": "trusted_environment_configuration",
                    }
                }
                if is_dssp
                else {}
            ),
            check=AvailabilityResult.available,
        ),
        readiness=(
            ReadinessDeclaration(
                behavior=BehaviorReference(
                    f"structure_annotation.{operation}/readiness",
                    {
                        "observation": "per-run",
                        "path_source": "trusted_environment_configuration",
                    }
                ),
                prerequisites={
                    "binary": {
                        "name": MKDSSP_BINARY,
                        "path_source": "trusted_environment_configuration",
                    }
                },
                check=_dssp_ready,
            )
            if is_dssp
            else None
        ),
        deterministic=True,
        cacheable=True,
        produced_observations=produced,
    )


MODULE_PACKAGE = ModulePackageRegistration(
    package_id="structure_annotation",
    package_module=__package__,
    node_definitions=tuple(
        DefinitionResource(f"definitions/{name}.yaml")
        for name in (
            "dssp_compute",
            "secondary_structure_extract",
            "sasa_compute",
            "secondary_structure_agreement",
            "apply_secondary_structure_to_prompt",
            "apply_sasa_to_prompt",
            "expected_secondary_structure_from_prompt",
        )
    ),
    metric_definitions=(
        DefinitionResource(
            "definitions/secondary_structure_agreement_metric.yaml"
        ),
        DefinitionResource(
            "definitions/secondary_structure_position_agreement_metric.yaml"
        ),
    ),
    methods=(_dssp_method(), *STATIC_METHODS),
    bindings=tuple(_binding(operation) for operation in _OPERATIONS),
    port_types=STRUCTURE_ANNOTATION_PORT_TYPES,
)
