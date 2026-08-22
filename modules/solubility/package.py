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

from .adapter import (
    LocalProteinSolAdapter,
    LocalSoluProtAdapter,
    PROTEIN_SOL_ARCHIVE_SHA256,
    PROTEIN_SOL_BASH_SHA256,
    PROTEIN_SOL_BASH_VERSION,
    PROTEIN_SOL_CALIBRATION_CONTEXT,
    PROTEIN_SOL_OFFICIAL_DOWNLOAD_URL,
    PROTEIN_SOL_PERL_SHA256,
    PROTEIN_SOL_PERL_VERSION,
    PROTEIN_SOL_RELEASE,
    PROTEIN_SOL_SOURCE_SHA256,
    SOLUPROT_DATABASE_SHA256,
    SOLUPROT_CODE_SHA256,
    SOLUPROT_FEATURES_SHA256,
    SOLUPROT_MODEL_SHA256,
    SOLUPROT_MODEL_TREES_SHA256,
    SOLUPROT_PERL_SHA256,
    SOLUPROT_PERL_VERSION,
    SOLUPROT_PYTHON_VERSION,
    SOLUPROT_PYTHON_SHA256,
    SOLUPROT_RUNTIME_VERSIONS,
    SOLUPROT_SOURCE_SHA256,
    SOLUPROT_TMHMM_SHA256,
    SOLUPROT_USEARCH_SHA256,
    SOLUPROT_PORT_VERSION,
    SoluProtMode,
    protein_sol_readiness,
    soluprot_readiness,
)


_PACKAGE_VERSION = "4.0.0"
_METHOD_VERSION = "3.0.0"
_METRIC_VERSION = "2.1.0"
_NODE_BINDING_VERSION = "5.0.0"
_MODES: tuple[SoluProtMode, ...] = ("full", "no_tm")
_SOLUPROT_ENVIRONMENT_FIELDS = (
    EnvironmentFieldDeclaration("python_executable", "filesystem_path"),
    EnvironmentFieldDeclaration("wheel_path", "filesystem_path"),
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
        version=_METHOD_VERSION,
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
            "port_artifact_version": SOLUPROT_PORT_VERSION,
            "upstream_model_family": "SoluProt",
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
            "kind": "project_maintained_locked_port",
            "upstream_project": "SoluProt",
            "port_distribution": "soluprot",
            "port_artifact_version": SOLUPROT_PORT_VERSION,
            "wheel_sha256": SOLUPROT_SOURCE_SHA256,
            "installed_code_sha256": SOLUPROT_CODE_SHA256,
            "official_release_equivalence": "not_claimed",
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
        version=_NODE_BINDING_VERSION,
        node_type=ContractIdentity(
            "node_type",
            "solubility.score_sequence",
            _NODE_BINDING_VERSION,
        ),
        method=ContractIdentity(
            "method",
            method_id,
            _METHOD_VERSION,
        ),
        binding_parameters={},
        environment_fields=(
            _SOLUPROT_ENVIRONMENT_FIELDS
            + (
                EnvironmentFieldDeclaration("tmhmm_root", "filesystem_path"),
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
                _NODE_BINDING_VERSION,
                {"mode": mode, "provider_import": "lazy"},
            ),
            build=_build(mode),
        ),
        adapter_behavior=BehaviorReference(
            f"solubility.soluprot_{mode}/adapter",
            _NODE_BINDING_VERSION,
            {
                "provider": "protein-workbench-soluprot-port",
                "port_artifact_version": SOLUPROT_PORT_VERSION,
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
                _NODE_BINDING_VERSION,
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
                _NODE_BINDING_VERSION,
                {
                    "observation": "cache-miss",
                    "mode": mode,
                    "cache_order": "before-provider-entry",
                    "model_load": "forbidden",
                },
            ),
            prerequisites={
                "python_runtime": {
                    "version": SOLUPROT_PYTHON_VERSION,
                    "sha256": SOLUPROT_PYTHON_SHA256,
                    "installed_distribution_versions": (
                        SOLUPROT_RUNTIME_VERSIONS
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
            check=lambda check_input: soluprot_readiness(
                check_input.values,
                mode=mode,
            ),
        ),
        deterministic=True,
        cacheable=True,
        implementation_identity={
            "name": f"solubility.soluprot_{mode}.local-adapter",
            "provider": "protein-workbench-soluprot-port",
            "port_artifact_version": SOLUPROT_PORT_VERSION,
            "wheel_sha256": SOLUPROT_SOURCE_SHA256,
            "installed_code_sha256": SOLUPROT_CODE_SHA256,
            "official_release_equivalence": "not_claimed",
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
            "runtime_distribution_versions": SOLUPROT_RUNTIME_VERSIONS,
            "perl": (
                {
                    "version": SOLUPROT_PERL_VERSION,
                    "sha256": SOLUPROT_PERL_SHA256,
                }
                if tm_feature
                else "not-used-or-probed"
            ),
            "runtime_directory_policy": "private-per-run-invocation",
        },
        produced_observations=(
            ProducedObservationDefinition(
                output_port="scores",
                output_partition=f"soluprot_{mode}",
                metric=ContractIdentity(
                    "metric",
                    "solubility.soluprot_probability",
                    _METRIC_VERSION,
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
        version=_METHOD_VERSION,
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
            "minimum_sequence_length": 21,
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
            "kind": "official_release_archive",
            "provider": "Protein-Sol",
            "release": PROTEIN_SOL_RELEASE,
            "official_download_url": PROTEIN_SOL_OFFICIAL_DOWNLOAD_URL,
            "download_url_role": "locator_only",
            "archive_sha256": PROTEIN_SOL_ARCHIVE_SHA256,
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
        version=_NODE_BINDING_VERSION,
        node_type=ContractIdentity(
            "node_type",
            "solubility.score_sequence",
            _NODE_BINDING_VERSION,
        ),
        method=ContractIdentity(
            "method",
            "solubility.protein_sol.sequence_prediction_2017",
            _METHOD_VERSION,
        ),
        binding_parameters={},
        environment_fields=_PROTEIN_SOL_ENVIRONMENT_FIELDS,
        execution_route="adapter",
        factory=ScientificOperationFactory(
            behavior=BehaviorReference(
                "solubility.protein_sol/factory",
                _NODE_BINDING_VERSION,
                {
                    "provider_import": "not-applicable",
                    "source_copy": "after-readiness-attestation",
                },
            ),
            build=_build_protein_sol,
        ),
        adapter_behavior=BehaviorReference(
            "solubility.protein_sol/adapter",
            _NODE_BINDING_VERSION,
            {
                "provider": "protein-sol",
                "release": PROTEIN_SOL_RELEASE,
                "official_archive_sha256": PROTEIN_SOL_ARCHIVE_SHA256,
                "request_subject_identity": "candidate_{zero_based_index}",
                "parser": "documented-predictions-provider-order",
                "response_subject_join": "staged-fasta-identity",
            },
        ),
        availability=AvailabilityDeclaration(
            behavior=BehaviorReference(
                "solubility.protein_sol/availability",
                _NODE_BINDING_VERSION,
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
                _NODE_BINDING_VERSION,
                {
                    "observation": "cache-miss",
                    "cache_order": "before-provider-entry",
                    "source_execution": "forbidden",
                },
            ),
            prerequisites={
                "official_archive": {
                    "download_url": PROTEIN_SOL_OFFICIAL_DOWNLOAD_URL,
                    "download_url_role": "locator_only",
                    "sha256": PROTEIN_SOL_ARCHIVE_SHA256,
                },
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
            check=lambda check_input: protein_sol_readiness(
                check_input.values
            ),
        ),
        deterministic=True,
        cacheable=True,
        implementation_identity={
            "name": "solubility.protein_sol.local-adapter",
            "provider": "protein-sol",
            "release": PROTEIN_SOL_RELEASE,
            "official_download_url": PROTEIN_SOL_OFFICIAL_DOWNLOAD_URL,
            "official_archive_sha256": PROTEIN_SOL_ARCHIVE_SHA256,
            "source_files_sha256": PROTEIN_SOL_SOURCE_SHA256,
            "bash_version": PROTEIN_SOL_BASH_VERSION,
            "bash_sha256": PROTEIN_SOL_BASH_SHA256,
            "perl_version": PROTEIN_SOL_PERL_VERSION,
            "perl_sha256": PROTEIN_SOL_PERL_SHA256,
            "runtime_directory_policy": "private-per-run-invocation",
        },
        produced_observations=tuple(
            ProducedObservationDefinition(
                output_port="scores",
                output_partition=partition,
                metric=ContractIdentity(
                    "metric",
                    metric_id,
                    _METRIC_VERSION,
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
    schema_version="2.1.0",
    package_id="solubility",
    package_version=_PACKAGE_VERSION,
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
