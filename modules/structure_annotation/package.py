"""The single production registration for structure annotations."""

from __future__ import annotations

from datatypes.observation import PairwiseContextProfile

from core.catalog.observation import ObservationPortSource

from core.catalog.declarations import (
    AvailabilityDeclaration,
    AvailabilityResult,
    EnvironmentFieldDeclaration,
    ExecutionBindingDefinition,
    MethodDefinition,
    ModulePackageRegistration,
    ReadinessDeclaration,
    ScientificOperationFactory,
)
from datatypes.exact_reference import ExactContractReference
from core.catalog.observation import ProducedObservation
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
    DSSPComputeOperation,
    ExpectedSecondaryStructureFromPromptOperation,
    ObservedToConditioningOperation,
    SecondaryStructureAgreementOperation,
)
from .port_types import STRUCTURE_ANNOTATION_PORT_TYPES


_OPERATIONS = (
    "dssp_compute",
    "observed_to_conditioning",
    "secondary_structure_agreement",
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
        if operation == "observed_to_conditioning":
            return ObservedToConditioningOperation(context.resources)
        if operation == "secondary_structure_agreement":
            return SecondaryStructureAgreementOperation(
                resources=context.resources,
                method=context.method,
                produced_observation=context.produced_observations[0],
            )
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
            "missing_value": "JSON null",
            "secondary_conversion": {
                "DSSP _ (missing)": "null",
                "DSSP P (poly-proline coil)": "C",
                "mkdssp mmCIF '.' (coil)": "C",
                "mkdssp mmCIF '?' (absent)": "null",
                "canonical HBEGITSC": "pass through unchanged",
            },
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
    method = ExactContractReference(
        "method",
        f"structure_annotation.{operation}.method",
    )
    produced = ()
    if operation == "secondary_structure_agreement":
        produced = (
            ProducedObservation(
                output_port="scores",
                output_partition="default",
                metric=ExactContractReference(
                    "metric",
                    "structure_annotation.secondary_structure_agreement",
                ),
                context_profile=PairwiseContextProfile(
                    subject_role="subject",
                    reference_role="reference",
                    pairing_mode="fixed_reference",
                    normalization="exact-SS8-present-residue",
                ),
                subject_input="subject_residue_axes",
                reference_source=ObservationPortSource("input", "references"),
                axis_source=ObservationPortSource("input", "subject_residue_axes"),
                guaranteed_multiplicity="one",
            ),
        )
    is_dssp = operation == _DSSP_OPERATION
    route = "mkdssp_local" if is_dssp else "direct"
    execution_route = "adapter" if is_dssp else "direct"
    return ExecutionBindingDefinition(
        binding_id=f"structure_annotation.{operation}.{route}",
        node_type=ExactContractReference(
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
            "observed_to_conditioning",
            "secondary_structure_agreement",
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
