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
    configured_runtime_fingerprint,
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
    ),
    methods=tuple(_method(mode) for mode in _MODES),
    bindings=tuple(_binding(mode) for mode in _MODES),
)
