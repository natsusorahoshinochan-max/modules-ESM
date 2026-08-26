"""Single production registration for sequence-solubility capabilities."""

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
from core.catalog.definition_resource import (
    DefinitionResource,
)
from core.catalog.port_contract import (
    BehaviorReference,
)
from core.operation import (
    OperationContext,
    ScientificOperation,
)

from .protein_sol import (
    PROTEIN_SOL_CALIBRATION_CONTEXT,
    PROTEIN_SOL_RELEASE,
    LocalProteinSolAdapter,
    protein_sol_readiness,
)
from .soluprot import (
    SOLUPROT_TMHMM_RELATIVE_ROOT,
    LocalSoluProtAdapter,
    SoluProtMode,
    soluprot_readiness,
)


_MODES: tuple[SoluProtMode, ...] = ("full", "no_tm")
_SOLUPROT_ENVIRONMENT_FIELDS = (
    EnvironmentFieldDeclaration("python_executable", "filesystem_path"),
    EnvironmentFieldDeclaration("site_packages_root", "filesystem_path"),
    EnvironmentFieldDeclaration("usearch_executable", "filesystem_path"),
)
_PROTEIN_SOL_ENVIRONMENT_FIELDS = (
    EnvironmentFieldDeclaration("source_root", "filesystem_path"),
    EnvironmentFieldDeclaration("bash_executable", "filesystem_path"),
    EnvironmentFieldDeclaration("perl_executable", "filesystem_path"),
)


def _available() -> AvailabilityResult:
    """Discovery never imports SoluProt or touches operator assets."""
    return AvailabilityResult.available()


def _build(mode: SoluProtMode):
    def factory(context: OperationContext) -> ScientificOperation:
        from .implementation import SoluProtImplementation

        return SoluProtImplementation(
            adapter=LocalSoluProtAdapter(
                mode=mode,
                environment=context.environment,
                resources=context.resources,
            ),
            method=context.method,
            produced_observation=context.produced_observations[0],
        )

    return factory


def _build_protein_sol(
    context: OperationContext,
) -> ScientificOperation:
    from .implementation import ProteinSolImplementation

    return ProteinSolImplementation(
        adapter=LocalProteinSolAdapter(
            environment=context.environment,
            resources=context.resources,
        ),
        method=context.method,
        produced_observations=context.produced_observations,
    )


def _method(mode: SoluProtMode) -> MethodDefinition:
    tm_feature = mode == "full"
    model_variant = "grad_clf_v1_tc" if tm_feature else "grad_clf_v1_tc_notmhmm"
    return MethodDefinition(
        method_id=f"solubility.soluprot_{mode}.v1_1_0",
        algorithm_identity={
            "name": (
                "Protein Workbench project-maintained SoluProt "
                "gradient-boosting port"
            ),
            "variant": model_variant,
            "transmembrane_features": tm_feature,
            "provider_postprocessing": {
                "rounding_decimal_places": 4,
                "clipping_range": [0, 1],
            },
        },
        model_identity={
            "provider": "Protein Workbench project-maintained SoluProt port",
            "upstream_model_family": "SoluProt",
            "model_variant": model_variant,
        },
        featurization_identity={
            "sequence_alphabet": "ACDEFGHIKLMNPQRSTVWY",
            "minimum_sequence_length": 20,
            "tmhmm_features": tm_feature,
        },
        scale_contract={
            "quantity": "soluble_expression_probability",
            "unit": "dimensionless_probability",
            "canonical_range": [0, 1],
            "normalization": "none",
            "provider_postprocessing": {
                "rounding_decimal_places": 4,
                "clipping_range": [0, 1],
            },
            "adapter_clamping": "forbidden",
        },
    )


def _binding(mode: SoluProtMode) -> ExecutionBindingDefinition:
    method_id = f"solubility.soluprot_{mode}.v1_1_0"
    tm_feature = mode == "full"
    return ExecutionBindingDefinition(
        binding_id=f"solubility.soluprot_{mode}.local",
        node_type=ContractIdentity(
            "node_type",
            "solubility.score_sequence",
        ),
        method=ContractIdentity(
            "method",
            method_id,
        ),
        binding_parameters={},
        environment_fields=(
            _SOLUPROT_ENVIRONMENT_FIELDS
            + (
                EnvironmentFieldDeclaration(
                    "perl_executable",
                    "filesystem_path",
                ),
            )
            if tm_feature
            else _SOLUPROT_ENVIRONMENT_FIELDS
        ),
        execution_route="adapter",
        factory=ScientificOperationFactory(
            behavior=BehaviorReference(
                f"solubility.soluprot_{mode}/factory",
                {"mode": mode, "provider_import": "lazy"},
            ),
            build=_build(mode),
        ),
        adapter_behavior=BehaviorReference(
            f"solubility.soluprot_{mode}/adapter",
            {
                "provider": "protein-workbench-soluprot-port",
                "official_release_equivalence": "not_claimed",
                "mode": mode,
                "request_subject_identity": "candidate_{zero_based_index}",
                "parser": "documented-csv-provider-order",
                "response_subject_join": "staged-fasta-identity",
            },
        ),
        availability=AvailabilityDeclaration(
            behavior=BehaviorReference(
                f"solubility.soluprot_{mode}/availability",
                {
                    "observation": "startup",
                    "provider_import": "forbidden",
                    "asset_probe": "forbidden",
                },
            ),
            prerequisites={},
            check=_available,
        ),
        readiness=ReadinessDeclaration(
            behavior=BehaviorReference(
                f"solubility.soluprot_{mode}/readiness",
                {
                    "observation": "cache-miss",
                    "mode": mode,
                    "cache_order": "before-provider-entry",
                    "model_load": "forbidden",
                },
            ),
            prerequisites={
                "python_runtime": {
                    "path_source": "trusted_environment_configuration",
                },
                "model": {
                    "path_source": "trusted_environment_configuration",
                },
                "reference_database": {
                    "path_source": "trusted_environment_configuration",
                },
                "usearch": {
                    "path_source": "trusted_environment_configuration",
                },
                "tmhmm": (
                    {
                        "required": True,
                        "bundled_asset_root": str(
                            SOLUPROT_TMHMM_RELATIVE_ROOT
                        ),
                        "decoder": {
                            "selection": "uname-system-and-machine",
                        },
                        "path_source": "installed_distribution",
                    }
                    if tm_feature
                    else {"required": False, "must_not_be_probed": True}
                ),
            },
            check=lambda check_input: soluprot_readiness(
                check_input.values,
                mode=mode,
            ),
        ),
        deterministic=True,
        cacheable=True,
        produced_observations=(
            ProducedObservationDefinition(
                output_port="scores",
                output_partition=f"soluprot_{mode}",
                metric=ContractIdentity(
                    "metric",
                    "solubility.soluprot_probability",
                ),
                context_profile={"kind": "intrinsic"},
                subject_grain="candidate",
                source_role="subject",
                subject_direction="input",
                subject_port="sequence_candidates",
                guaranteed_multiplicity="one",
            ),
        ),
    )


def _protein_sol_method() -> MethodDefinition:
    return MethodDefinition(
        method_id="solubility.protein_sol.sequence_prediction_2017",
        algorithm_identity={
            "name": "Protein-Sol sequence-based soluble-fraction predictor",
            "training_population": "niwa_non_membrane_2396",
            "scientific_feature_count": 35,
            "raw_composition_column_count": 36,
            "raw_bookkeeping_column": "totperc",
            "fitted_feature_count": 10,
            "feature_bounds": "clamped-by-upstream-before-linear-fit",
            "provider_postprocessing": {
                "decimal_places": 3,
                "adapter_clamping": "forbidden",
            },
        },
        model_identity={
            "provider": "Protein-Sol",
            "release": PROTEIN_SOL_RELEASE,
            "training_data": "Niwa_2009_non_membrane_2396",
            "population_percent_solubility": 53.347,
            "low_percent_solubility": 5.208,
            "top_percent_solubility": 113.241,
            "population_scaled_solubility": 0.446,
        },
        featurization_identity={
            "sequence_alphabet": "ACDEFGHIKLMNPQRSTVWY",
            "minimum_sequence_length": 21,
            "whole_sequence_features": True,
            "profile_windows": [21, 51],
            "isoelectric_point_range": [1, 14],
        },
        scale_contract={
            "percent_sol": {
                "unit": "percent_soluble_fraction",
                "canonical_range": [5.208, 113.241],
            },
            "scaled_sol": {
                "unit": "dimensionless",
                "canonical_range": [0, 1],
                "normalization": "(percent_sol-5.208)/(113.241-5.208)",
            },
            "population_sol": {
                "role": "calibration_context",
                "value": 0.446,
                "unit": "dimensionless",
            },
            "pi": {
                "unit": "ph",
                "canonical_range": [1, 14],
            },
            "adapter_scale_inference": "forbidden",
            "adapter_clamping": "forbidden",
        },
    )


def _protein_sol_binding() -> ExecutionBindingDefinition:
    return ExecutionBindingDefinition(
        binding_id="solubility.protein_sol.local",
        node_type=ContractIdentity(
            "node_type",
            "solubility.score_sequence",
        ),
        method=ContractIdentity(
            "method",
            "solubility.protein_sol.sequence_prediction_2017",
        ),
        binding_parameters={},
        environment_fields=_PROTEIN_SOL_ENVIRONMENT_FIELDS,
        execution_route="adapter",
        factory=ScientificOperationFactory(
            behavior=BehaviorReference(
                "solubility.protein_sol/factory",
                {
                    "provider_import": "not-applicable",
                    "source_copy": "after-readiness-attestation",
                },
            ),
            build=_build_protein_sol,
        ),
        adapter_behavior=BehaviorReference(
            "solubility.protein_sol/adapter",
            {
                "provider": "protein-sol",
                "release": PROTEIN_SOL_RELEASE,
                "request_subject_identity": "candidate_{zero_based_index}",
                "parser": "documented-predictions-provider-order",
                "response_subject_join": "staged-fasta-identity",
            },
        ),
        availability=AvailabilityDeclaration(
            behavior=BehaviorReference(
                "solubility.protein_sol/availability",
                {
                    "observation": "startup",
                    "source_probe": "forbidden",
                },
            ),
            prerequisites={},
            check=_available,
        ),
        readiness=ReadinessDeclaration(
            behavior=BehaviorReference(
                "solubility.protein_sol/readiness",
                {
                    "observation": "cache-miss",
                    "cache_order": "before-provider-entry",
                    "source_execution": "forbidden",
                },
            ),
            prerequisites={
                "source_root": {
                    "path_source": "trusted_environment_configuration",
                },
                "bash": {
                    "path_source": "trusted_environment_configuration",
                },
                "perl": {
                    "path_source": "trusted_environment_configuration",
                },
                "path_source": "trusted_environment_configuration",
            },
            check=lambda check_input: protein_sol_readiness(
                check_input.values
            ),
        ),
        deterministic=True,
        cacheable=True,
        produced_observations=tuple(
            ProducedObservationDefinition(
                output_port="scores",
                output_partition=partition,
                metric=ContractIdentity(
                    "metric",
                    metric_id,
                ),
                context_profile=context_profile,
                subject_grain="candidate",
                source_role="subject",
                subject_direction="input",
                subject_port="sequence_candidates",
                guaranteed_multiplicity="one",
            )
            for partition, metric_id, context_profile in (
                (
                    "protein_sol_percent",
                    "solubility.protein_sol_percent",
                    PROTEIN_SOL_CALIBRATION_CONTEXT,
                ),
                (
                    "protein_sol_scaled",
                    "solubility.protein_sol_scaled",
                    PROTEIN_SOL_CALIBRATION_CONTEXT,
                ),
                (
                    "protein_sol_pi",
                    "solubility.protein_sol_pi",
                    {"kind": "intrinsic"},
                ),
            )
        ),
    )


MODULE_PACKAGE = ModulePackageRegistration(
    package_id="solubility",
    package_module=__package__,
    node_definitions=(
        DefinitionResource("definitions/score_sequence.yaml"),
    ),
    metric_definitions=(
        DefinitionResource("definitions/soluprot_probability_metric.yaml"),
        DefinitionResource("definitions/protein_sol_percent_metric.yaml"),
        DefinitionResource("definitions/protein_sol_scaled_metric.yaml"),
        DefinitionResource("definitions/protein_sol_pi_metric.yaml"),
    ),
    methods=tuple(_method(mode) for mode in _MODES)
    + (_protein_sol_method(),),
    bindings=tuple(_binding(mode) for mode in _MODES)
    + (_protein_sol_binding(),),
)
