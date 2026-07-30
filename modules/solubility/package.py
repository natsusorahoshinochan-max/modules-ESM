"""Single production registration for sequence-solubility capabilities."""

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
    ProducedObservationDefinition,
    ReadinessDeclaration,
)

from .adapter import (
    PROTEIN_SOL_BASH_SHA256,
    PROTEIN_SOL_BASH_VERSION,
    PROTEIN_SOL_CALIBRATION_CONTEXT,
    PROTEIN_SOL_PERL_SHA256,
    PROTEIN_SOL_PERL_VERSION,
    PROTEIN_SOL_RELEASE,
    PROTEIN_SOL_SOURCE_SHA256,
    SOLUPROT_DATABASE_SHA256,
    SOLUPROT_FEATURES_SHA256,
    SOLUPROT_MODEL_SHA256,
    SOLUPROT_MODEL_TREES_SHA256,
    SOLUPROT_PERL_SHA256,
    SOLUPROT_PERL_VERSION,
    SOLUPROT_PYTHON_VERSION,
    SOLUPROT_PYTHON_SHA256,
    SOLUPROT_RUNTIME_DISTRIBUTIONS,
    SOLUPROT_SOURCE_SHA256,
    SOLUPROT_TMHMM_SHA256,
    SOLUPROT_USEARCH_SHA256,
    SOLUPROT_VERSION,
    configured_protein_sol_runtime_fingerprint,
    configured_runtime_fingerprint,
    protein_sol_readiness,
    soluprot_readiness,
)


_VERSION = "2.0.0"
_MODES = ("full", "no_tm")


def _available() -> AvailabilityResult:
    """Discovery never imports SoluProt or touches operator assets."""
    return AvailabilityResult.available()


def _build(mode: str):
    def factory(**kwargs: object) -> object:
        from .implementation import SoluProtImplementation

        return SoluProtImplementation(
            kwargs["run_resources"],
            kwargs["environment_configuration"],
            kwargs["frozen_catalog"],
            mode=mode,
        )

    return factory


def _build_protein_sol(**kwargs: object) -> object:
    from .implementation import ProteinSolImplementation

    return ProteinSolImplementation(
        kwargs["run_resources"],
        kwargs["environment_configuration"],
        kwargs["frozen_catalog"],
    )


def _method(mode: str) -> MethodDefinition:
    tm_feature = mode == "full"
    model_variant = "grad_clf_v1_tc" if tm_feature else "grad_clf_v1_tc_notmhmm"
    return MethodDefinition(
        method_id=f"solubility.soluprot_{mode}.v1_1_0",
        version=_VERSION,
        algorithm_identity={
            "name": "SoluProt gradient-boosting soluble-expression predictor",
            "variant": model_variant,
            "transmembrane_features": tm_feature,
            "provider_postprocessing": {
                "rounding_decimal_places": 4,
                "clipping_range": [0, 1],
            },
        },
        model_identity={
            "provider": "SoluProt",
            "provider_version": SOLUPROT_VERSION,
            "model_variant": model_variant,
        },
        checkpoint_identity={
            "model_json_sha256": SOLUPROT_MODEL_SHA256[mode],
            "model_arrays_sha256": SOLUPROT_MODEL_TREES_SHA256[mode],
        },
        featurization_identity={
            "sequence_alphabet": "ACDEFGHIKLMNPQRSTVWY",
            "minimum_sequence_length": 20,
            "provider_features_sha256": SOLUPROT_FEATURES_SHA256,
            "reference_database_sha256": SOLUPROT_DATABASE_SHA256,
            "usearch_sha256": SOLUPROT_USEARCH_SHA256,
            "tmhmm": (
                dict(SOLUPROT_TMHMM_SHA256)
                if tm_feature
                else "not-used-or-probed"
            ),
        },
        source_identity={
            "dependency": "soluprot",
            "version": SOLUPROT_VERSION,
            "wheel_sha256": SOLUPROT_SOURCE_SHA256,
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


def _binding(mode: str) -> ExecutionBindingDefinition:
    method_id = f"solubility.soluprot_{mode}.v1_1_0"
    tm_feature = mode == "full"
    return ExecutionBindingDefinition(
        binding_id=f"solubility.soluprot_{mode}.local",
        version=_VERSION,
        node_type=ContractIdentity(
            "node_type",
            "solubility.score_sequence",
            _VERSION,
        ),
        method=ContractIdentity("method", method_id, _VERSION),
        binding_parameters={},
        execution_route="adapter",
        factory=LazyImplementationFactory(
            behavior=BehaviorReference(
                f"solubility.soluprot_{mode}/factory",
                _VERSION,
                {"mode": mode, "provider_import": "lazy"},
            ),
            build=_build(mode),
        ),
        adapter_behavior=BehaviorReference(
            f"solubility.soluprot_{mode}/adapter",
            _VERSION,
            {
                "provider": "soluprot",
                "provider_version": SOLUPROT_VERSION,
                "mode": mode,
            },
        ),
        availability=AvailabilityDeclaration(
            behavior=BehaviorReference(
                f"solubility.soluprot_{mode}/availability",
                _VERSION,
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
                _VERSION,
                {
                    "observation": "per-run",
                    "mode": mode,
                    "cache_order": "before-cache-lookup",
                    "model_load": "forbidden",
                },
            ),
            prerequisites={
                "python_runtime": {
                    "version": SOLUPROT_PYTHON_VERSION,
                    "sha256": SOLUPROT_PYTHON_SHA256,
                    "installed_distribution_trees": (
                        SOLUPROT_RUNTIME_DISTRIBUTIONS
                    ),
                    "path_source": "trusted_environment_configuration",
                },
                "dependency_wheel": {
                    "sha256": SOLUPROT_SOURCE_SHA256,
                    "path_source": "trusted_environment_configuration",
                },
                "model": {
                    "json_sha256": SOLUPROT_MODEL_SHA256[mode],
                    "arrays_sha256": SOLUPROT_MODEL_TREES_SHA256[mode],
                    "path_source": "trusted_environment_configuration",
                },
                "reference_database": {
                    "sha256": SOLUPROT_DATABASE_SHA256,
                    "path_source": "trusted_environment_configuration",
                },
                "usearch": {
                    "sha256": SOLUPROT_USEARCH_SHA256,
                    "path_source": "trusted_environment_configuration",
                },
                "tmhmm": (
                    {
                        "required": True,
                        "asset_sha256": dict(SOLUPROT_TMHMM_SHA256),
                        "perl_version": SOLUPROT_PERL_VERSION,
                        "perl_sha256": SOLUPROT_PERL_SHA256,
                        "path_source": "trusted_environment_configuration",
                    }
                    if tm_feature
                    else {"required": False, "must_not_be_probed": True}
                ),
            },
            check=lambda environment: soluprot_readiness(environment, mode=mode),
        ),
        deterministic=True,
        cacheable=True,
        implementation_identity={
            "name": f"solubility.soluprot_{mode}.local-adapter",
            "provider": "soluprot",
            "provider_version": SOLUPROT_VERSION,
            "source_sha256": SOLUPROT_SOURCE_SHA256,
            "mode": mode,
            "model_json_sha256": SOLUPROT_MODEL_SHA256[mode],
            "model_arrays_sha256": SOLUPROT_MODEL_TREES_SHA256[mode],
            "reference_database_sha256": SOLUPROT_DATABASE_SHA256,
            "usearch_sha256": SOLUPROT_USEARCH_SHA256,
            "transmembrane_features": tm_feature,
            "tmhmm_sha256": (
                dict(SOLUPROT_TMHMM_SHA256)
                if tm_feature
                else {}
            ),
            "python_version": SOLUPROT_PYTHON_VERSION,
            "python_sha256": SOLUPROT_PYTHON_SHA256,
            "runtime_distribution_trees": SOLUPROT_RUNTIME_DISTRIBUTIONS,
            "perl": (
                {
                    "version": SOLUPROT_PERL_VERSION,
                    "sha256": SOLUPROT_PERL_SHA256,
                }
                if tm_feature
                else "not-used-or-probed"
            ),
            "resolved_runtime_fingerprint": configured_runtime_fingerprint(mode),
            "runtime_directory_policy": "private-per-run-invocation",
        },
        produced_observations=(
            ProducedObservationDefinition(
                output_port="scores",
                output_partition=f"soluprot_{mode}",
                metric=ContractIdentity(
                    "metric",
                    "solubility.soluprot_probability",
                    _VERSION,
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
        version=_VERSION,
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
        checkpoint_identity={
            "seq_reference_data_sha256": PROTEIN_SOL_SOURCE_SHA256[
                "seq_reference_data.txt"
            ],
            "ss_propensities_sha256": PROTEIN_SOL_SOURCE_SHA256[
                "ss_propensities.txt"
            ],
        },
        featurization_identity={
            "sequence_alphabet": "ACDEFGHIKLMNPQRSTVWY",
            "whole_sequence_features": True,
            "profile_windows": [21, 51],
            "isoelectric_point_range": [1, 14],
            "preprocessing": {
                "fasta_reformat_sha256": PROTEIN_SOL_SOURCE_SHA256[
                    "fasta_seq_reformat_export.pl"
                ],
                "composition_sha256": PROTEIN_SOL_SOURCE_SHA256[
                    "seq_compositions_perc_pipeline_export.pl"
                ],
                "prediction_sha256": PROTEIN_SOL_SOURCE_SHA256[
                    "server_prediction_seq_export.pl"
                ],
                "properties_sha256": PROTEIN_SOL_SOURCE_SHA256[
                    "seq_props_ALL_export.pl"
                ],
                "profiles_sha256": PROTEIN_SOL_SOURCE_SHA256[
                    "profiles_gather_export.pl"
                ],
            },
        },
        source_identity={
            "dependency": "protein-sol",
            "release": PROTEIN_SOL_RELEASE,
            "workspace_repository": "ESM-workflow-NEXT",
            "dependency_subpath": "vendor/protein-sol",
            "source_files_sha256": PROTEIN_SOL_SOURCE_SHA256,
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
        version=_VERSION,
        node_type=ContractIdentity(
            "node_type",
            "solubility.score_sequence",
            _VERSION,
        ),
        method=ContractIdentity(
            "method",
            "solubility.protein_sol.sequence_prediction_2017",
            _VERSION,
        ),
        binding_parameters={},
        execution_route="adapter",
        factory=LazyImplementationFactory(
            behavior=BehaviorReference(
                "solubility.protein_sol/factory",
                _VERSION,
                {"provider_import": "not-applicable", "source_copy": "exact"},
            ),
            build=_build_protein_sol,
        ),
        adapter_behavior=BehaviorReference(
            "solubility.protein_sol/adapter",
            _VERSION,
            {
                "provider": "protein-sol",
                "release": PROTEIN_SOL_RELEASE,
                "parser": "closed-sequence-predictions-v1",
            },
        ),
        availability=AvailabilityDeclaration(
            behavior=BehaviorReference(
                "solubility.protein_sol/availability",
                _VERSION,
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
                _VERSION,
                {
                    "observation": "per-run",
                    "cache_order": "before-cache-lookup",
                    "source_execution": "forbidden",
                },
            ),
            prerequisites={
                "source_files_sha256": PROTEIN_SOL_SOURCE_SHA256,
                "bash": {
                    "version": PROTEIN_SOL_BASH_VERSION,
                    "sha256": PROTEIN_SOL_BASH_SHA256,
                },
                "perl": {
                    "version": PROTEIN_SOL_PERL_VERSION,
                    "sha256": PROTEIN_SOL_PERL_SHA256,
                },
                "path_source": "trusted_environment_configuration",
            },
            check=lambda environment: protein_sol_readiness(environment),
        ),
        deterministic=True,
        cacheable=True,
        implementation_identity={
            "name": "solubility.protein_sol.local-adapter",
            "provider": "protein-sol",
            "release": PROTEIN_SOL_RELEASE,
            "source_files_sha256": PROTEIN_SOL_SOURCE_SHA256,
            "bash_version": PROTEIN_SOL_BASH_VERSION,
            "bash_sha256": PROTEIN_SOL_BASH_SHA256,
            "perl_version": PROTEIN_SOL_PERL_VERSION,
            "perl_sha256": PROTEIN_SOL_PERL_SHA256,
            "resolved_runtime_fingerprint": (
                configured_protein_sol_runtime_fingerprint()
            ),
            "runtime_directory_policy": "private-per-run-invocation",
        },
        produced_observations=tuple(
            ProducedObservationDefinition(
                output_port="scores",
                output_partition=partition,
                metric=ContractIdentity("metric", metric_id, _VERSION),
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
    schema_version=_VERSION,
    package_id="solubility",
    package_version=_VERSION,
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
