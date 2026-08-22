"""Contract tests for atomic Catalog construction from registrations."""

from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timedelta, timezone
import importlib
from pathlib import Path
import sys

from fastapi.testclient import TestClient
import pytest

from core.catalog.builder import (
    build_frozen_catalog,
)
from core.catalog.declarations import (
    AvailabilityDeclaration,
    AvailabilityResult,
    ContractIdentity,
    ExecutionBindingDefinition,
    MethodDefinition,
    ModulePackageRegistration,
    ObservationPropagationDefinition,
    ProducedObservationDefinition,
    ReadinessDeclaration,
    ScientificOperationFactory,
)
from core.catalog.model import CatalogAvailabilityProjection
from core.catalog.port_contract import (
    BehaviorReference,
    CatalogBuildError,
)
from core.operation import (
    OperationCall,
    ReadinessResult,
)
from protein_workbench_public.bootstrap import create_application
from datatypes.candidate import (
    Candidate,
    CandidateCollection,
    CandidateDataReference,
)
from datatypes.sequence import ProteinSequence
from tests.support.protocol import validate_response
from protein_workbench_public.bootstrap import module_registrations
from protein_workbench_public.catalog_codec import encode_catalog_projection
from tests.fixtures.scientific_operation import admitted_port_fixture


NODE_DEFINITION = """\
schema_version: "2.1.0"
node_type_id: synthetic.echo
version: "3.0.0"
title: Synthetic Echo
summary: Returns one text value for Module Package contract testing.
category: test_support
inputs:
  - name: value
    port_type_id: synthetic.text
    port_type_version: "2.1.0"
    required: true
    multiplicity: one
    scientific_meaning: Text supplied to the synthetic operation.
  - name: candidate_subjects
    port_type_id: candidate.collection
    port_type_version: "4.0.0"
    required: true
    multiplicity: one
    scientific_meaning: Candidate subjects supplied to the synthetic operation.
outputs:
  - name: value
    port_type_id: synthetic.text
    port_type_version: "2.1.0"
    required: true
    multiplicity: one
    scientific_meaning: Text returned by the synthetic operation.
  - name: candidates
    port_type_id: candidate.collection
    port_type_version: "4.0.0"
    required: false
    multiplicity: one
    scientific_meaning: Candidates observed by the synthetic operation.
  - name: scores
    port_type_id: score.collection
    port_type_version: "5.0.0"
    required: false
    multiplicity: one
    scientific_meaning: Typed observations emitted by the synthetic operation.
parameter_groups: []
node_parameters: {}
"""

METRIC_DEFINITION = """\
schema_version: "2.1.0"
metric_id: synthetic.identity
version: "2.1.0"
title: Synthetic identity score
description: Contract-test score emitted by the synthetic echo operation.
value_shape: scalar
unit: dimensionless
direction: higher_is_better
canonical_range:
  minimum: 0
  maximum: 1
granularity: candidate
aggregation_semantics:
  kind: none
observation_context_schema:
  kind: intrinsic
validation_contract:
  finite: true
"""


PACKAGE_REGISTRATION = """\
import os

from core.catalog.declarations import (
    AvailabilityDeclaration,
    AvailabilityResult,
    ContractIdentity,
    ExecutionBindingDefinition,
    ScientificOperationFactory,
    MethodDefinition,
    ModulePackageRegistration,
    ProducedObservationDefinition,
    ReadinessDeclaration,
    UtilityTransformDefinition,
)
from core.catalog.definition_resource import DefinitionResource
from core.catalog.port_contract import BehaviorReference, PortTypeDefinition


def _factory(context):
    del context
    if os.environ.get("SYNTHETIC_FACTORY_ALLOWED") != "1":
        raise AssertionError("Catalog construction instantiated an operation")
    return {"implementation": "synthetic.echo"}

def _validate_text(value):
    if type(value) is not str:
        raise ValueError("synthetic.text requires str")

def _identity(value, parameters):
    return float(value)

_METRIC = ContractIdentity("metric", "synthetic.identity", "2.1.0")
_METHOD = ContractIdentity("method", "synthetic.echo", "2.1.0")


MODULE_PACKAGE = ModulePackageRegistration(
    package_id="synthetic",
    package_version="2.1.0",
    package_module=__package__,
    node_definitions=(DefinitionResource("node.yaml"),),
    metric_definitions=(DefinitionResource("metric.yaml"),),
    methods=(
        MethodDefinition(
            method_id="synthetic.echo",
            version="2.1.0",
            algorithm_identity={"name": "identity"},
            model_identity={"kind": "none"},
            checkpoint_identity={"kind": "none"},
            featurization_identity={"kind": "none"},
            source_identity={"kind": "contract-test"},
            scale_contract={"kind": "identity"},
        ),
    ),
    port_types=(
        PortTypeDefinition(
            type_id="synthetic.text",
            version="2.1.0",
            validator=BehaviorReference(
                "synthetic.text/validate",
                "2.1.0",
                {"accepted_value_kind": "text"},
            ),
            codec=BehaviorReference(
                "synthetic.text/codec",
                "2.1.0",
                {"canonicalization": "RFC 8785"},
            ),
            content_identity=BehaviorReference(
                "synthetic.text/content",
                "2.1.0",
                {"digest": "SHA-256"},
            ),
            runtime_validator=_validate_text,
            runtime_to_wire=lambda value: value,
            runtime_from_wire=lambda value: value,
        ),
    ),
    utility_transforms=(
        UtilityTransformDefinition(
            transform_id="synthetic.identity",
            version="2.1.0",
            compatible_input_contract={
                "metric": _METRIC,
                "method": _METHOD,
            },
            parameters={},
            behavior=BehaviorReference(
                "synthetic.identity/transform",
                "2.1.0",
                {},
            ),
            transform=_identity,
        ),
    ),
    bindings=(
        ExecutionBindingDefinition(
            binding_id="synthetic.echo.direct",
            version="3.0.0",
            node_type=ContractIdentity("node_type", "synthetic.echo", "3.0.0"),
            method=_METHOD,
            binding_parameters={},
            execution_route="direct",
            factory=ScientificOperationFactory(
                behavior=BehaviorReference(
                    "synthetic.echo/factory",
                    "2.1.0",
                    {},
                ),
                build=_factory,
            ),
            availability=AvailabilityDeclaration(
                behavior=BehaviorReference(
                    "synthetic.echo/availability",
                    "2.1.0",
                    {},
                ),
                prerequisites={},
                check=lambda: AvailabilityResult.available(),
            ),
            readiness=ReadinessDeclaration(
                behavior=BehaviorReference(
                    "synthetic.echo/readiness",
                    "2.1.0",
                    {},
                ),
                prerequisites={},
                check=lambda environment: ReadinessResult(True),
            ),
            deterministic=True,
            cacheable=True,
            implementation_identity={"name": "synthetic.echo.direct"},
            produced_observations=(
                ProducedObservationDefinition(
                    output_port="scores",
                    output_partition="default",
                    metric=_METRIC,
                    context_profile={"kind": "intrinsic"},
                    subject_grain="candidate",
                    source_role="subject",
                    subject_direction="input",
                    subject_port="candidate_subjects",
                    guaranteed_multiplicity="one",
                ),
            ),
        ),
    ),
)
"""

EXPECTED_SYNTHETIC_CONTRACT_DIGESTS = {
    ("binding", "synthetic.echo.direct"): (
        "sha256:f2d03215cb81344c594564cdb3aa1b3543b6fd43c68878464e8573252320c475"
    ),
    ("method", "synthetic.echo"): (
        "sha256:e485971a5abafb8460fd29fc8978b89ed2dc4d66efec93c37b75d0289c807120"
    ),
    ("metric", "synthetic.identity"): (
        "sha256:51f0164af916ccf5c3e69c72fc2adb1be6d07c07254869e5a304e870d6bfb2e5"
    ),
    ("node_type", "synthetic.echo"): (
        "sha256:aaf22801384d7aeca66a440a3550e5b34f73fb3f379f8c973f33395524056503"
    ),
    ("port_type", "synthetic.text"): (
        "sha256:cc3fa0e72b72eb82ced2b58697b44a98587c61b6a6ce567c133ca847d2f47870"
    ),
    ("utility_transform", "synthetic.identity"): (
        "sha256:b2e26cdb0fd42569fc280b594c2187f046c530311eb28972c4f60a9ce607b1b8"
    ),
}


def _write_registration_package(tmp_path: Path) -> str:
    root_name = "synthetic_module_packages"
    root = tmp_path / root_name
    root.mkdir()
    (root / "__init__.py").write_text("")
    package = root / "synthetic"
    package.mkdir()
    (package / "__init__.py").write_text("")
    (package / "node.yaml").write_text(NODE_DEFINITION)
    (package / "metric.yaml").write_text(METRIC_DEFINITION)
    (package / "package.py").write_text(PACKAGE_REGISTRATION)
    return root_name


def _load_registration(root_name: str) -> ModulePackageRegistration:
    return importlib.import_module(
        f"{root_name}.synthetic.package"
    ).MODULE_PACKAGE


def _forget_package(root_name: str) -> None:
    for name in tuple(sys.modules):
        if name == root_name or name.startswith(f"{root_name}."):
            sys.modules.pop(name)
    importlib.invalidate_caches()


def _build_synthetic_catalog(
    tmp_path: Path,
    monkeypatch,
    *,
    observed_at: datetime | None = None,
):
    root_name = _write_registration_package(tmp_path)
    monkeypatch.syspath_prepend(str(tmp_path))
    importlib.invalidate_caches()
    try:
        return build_frozen_catalog(
            (_load_registration(root_name),),
            observed_at=observed_at,
        )
    finally:
        _forget_package(root_name)


def _snapshot(catalog) -> dict[str, object]:
    return encode_catalog_projection(
        catalog.projection(),
        protocol_digest="sha256:" + ("0" * 64),
    )


def _method(
    method_id: str,
    *,
    version: str = "2.1.0",
    algorithm_identity=None,
) -> MethodDefinition:
    return MethodDefinition(
        method_id=method_id,
        version=version,
        algorithm_identity=algorithm_identity or {"name": method_id},
        model_identity={"kind": "none"},
        checkpoint_identity={"kind": "none"},
        featurization_identity={"kind": "none"},
        source_identity={"kind": "contract-test"},
        scale_contract={"kind": "identity"},
    )


def _registration(
    package_id: str,
    *,
    methods=(),
) -> ModulePackageRegistration:
    return ModulePackageRegistration(
        package_id=package_id,
        package_version="2.1.0",
        package_module=f"unused_{package_id}",
        methods=tuple(methods),
    )


def test_first_level_registration_contributes_every_contract_kind(
    tmp_path: Path,
    monkeypatch,
) -> None:
    catalog = _build_synthetic_catalog(tmp_path, monkeypatch)

    actual = {
        (contract.contract_kind, contract.contract_id)
        for contract in catalog.contracts
    }
    actual.update(
        ("port_type", definition.type_id)
        for definition in catalog.port_types
        if definition.type_id.startswith("synthetic.")
    )

    assert actual == set(EXPECTED_SYNTHETIC_CONTRACT_DIGESTS)


def test_production_bindings_publish_exact_typed_environment_closures() -> None:
    registrations = module_registrations()
    external_packages = {
        registration.package_id
        for registration in registrations
        if any(binding.environment_fields for binding in registration.bindings)
    }
    assert external_packages == {
        "esm3",
        "folding",
        "proteinmpnn",
        "solubility",
        "structure_annotation",
    }

    catalog = build_frozen_catalog(registrations)
    for registration in registrations:
        for binding in registration.bindings:
            names = tuple(
                declaration.name
                for declaration in binding.environment_fields
            )
            assert len(names) == len(set(names))
            assert {"provider_client", "client_factory"}.isdisjoint(names)
            assert all(
                declaration.value_category
                in {
                    "json_value",
                    "filesystem_path",
                    "credential_handle",
                }
                for declaration in binding.environment_fields
            )
            resolved = catalog.require_contract(
                "binding",
                binding.binding_id,
                binding.version,
            )
            assert (
                resolved.definition.environment_fields
                == binding.environment_fields
            )


def test_only_adapter_bindings_declare_provider_readiness() -> None:
    registrations = module_registrations()
    catalog = build_frozen_catalog(registrations)

    for registration in registrations:
        for binding in registration.bindings:
            resolved = catalog.require_contract(
                "binding",
                binding.binding_id,
                binding.version,
            )
            if binding.execution_route == "adapter":
                assert binding.readiness is not None
                assert "readiness_declaration" in resolved.descriptor
            else:
                assert binding.readiness is None
                assert "readiness_declaration" not in resolved.descriptor


def test_package_owned_port_type_has_one_independent_exact_reference(
    tmp_path: Path,
    monkeypatch,
) -> None:
    catalog = _build_synthetic_catalog(tmp_path, monkeypatch)

    assert catalog.require_contract(
        "port_type",
        "synthetic.text",
        "2.1.0",
    ).reference() == {
        "contract_kind": "port_type",
        "contract_id": "synthetic.text",
        "contract_version": "2.1.0",
        "contract_digest": EXPECTED_SYNTHETIC_CONTRACT_DIGESTS[
            ("port_type", "synthetic.text")
        ],
    }


def test_package_owned_port_type_round_trips_a_complete_value(
    tmp_path: Path,
    monkeypatch,
) -> None:
    catalog = _build_synthetic_catalog(tmp_path, monkeypatch)
    synthetic_text = catalog.require_contract(
        "port_type",
        "synthetic.text",
        "2.1.0",
    )

    assert synthetic_text.decode(synthetic_text.encode("MÉTA")) == "MÉTA"


def test_node_descriptor_keeps_parameter_groups_separate(
    tmp_path: Path,
    monkeypatch,
) -> None:
    catalog = _build_synthetic_catalog(tmp_path, monkeypatch)

    assert catalog.require_contract(
        "node_type",
        "synthetic.echo",
        "3.0.0",
    ).descriptor["parameter_groups"] == ()


def test_legacy_path_artifact_port_is_rejected(
    tmp_path: Path,
    monkeypatch,
) -> None:
    root_name = _write_registration_package(tmp_path)
    node_path = tmp_path / root_name / "synthetic" / "node.yaml"
    node_path.write_text(
        NODE_DEFINITION.replace(
            "  - name: value\n"
            "    port_type_id: synthetic.text\n"
            "    port_type_version: \"2.1.0\"\n"
            "    required: true\n"
            "    multiplicity: one\n"
            "    scientific_meaning: Text returned by the synthetic operation.",
            "  - name: value\n"
            "    port_type_id: file.path\n"
            "    port_type_version: \"2.1.0\"\n"
            "    required: true\n"
            "    multiplicity: one\n"
            "    scientific_meaning: File returned by the synthetic operation.\n"
            "    artifact_kind: standalone",
        )
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    importlib.invalidate_caches()

    try:
        with pytest.raises(CatalogBuildError):
            build_frozen_catalog((_load_registration(root_name),))
    finally:
        _forget_package(root_name)


def test_package_owned_utility_runtime_is_resolved_by_exact_identity(
    tmp_path: Path,
    monkeypatch,
) -> None:
    catalog = _build_synthetic_catalog(tmp_path, monkeypatch)

    utility = catalog.require_contract(
        "utility_transform",
        "synthetic.identity",
        "2.1.0",
    ).definition
    assert utility.transform(0.75, {}) == 0.75


def test_binding_keeps_its_factory_lazy_during_catalog_build(
    tmp_path: Path,
    monkeypatch,
) -> None:
    catalog = _build_synthetic_catalog(tmp_path, monkeypatch)

    binding = catalog.require_contract(
        "binding",
        "synthetic.echo.direct",
        "3.0.0",
    ).definition
    assert binding.factory.behavior.behavior_id == "synthetic.echo/factory"


def test_binding_availability_is_published_with_the_catalog_observation(
    tmp_path: Path,
    monkeypatch,
) -> None:
    catalog = _build_synthetic_catalog(
        tmp_path,
        monkeypatch,
        observed_at=datetime(
            2026,
            7,
            29,
            1,
            2,
            3,
            tzinfo=timezone.utc,
        ),
    )
    assert type(catalog.availability[0]) is CatalogAvailabilityProjection
    assert catalog.projection().availability == catalog.availability
    assert _snapshot(catalog)["availability"] == [{
        "binding": {
            "contract_kind": "binding",
            "contract_id": "synthetic.echo.direct",
            "contract_version": "3.0.0",
            "contract_digest": EXPECTED_SYNTHETIC_CONTRACT_DIGESTS[
                ("binding", "synthetic.echo.direct")
            ],
        },
        "observed_at": "2026-07-29T01:02:03Z",
        "available": True,
    }]


def test_backend_publishes_the_same_explicit_catalog_snapshot(
    tmp_path: Path,
    monkeypatch,
) -> None:
    root_name = _write_registration_package(tmp_path)
    monkeypatch.syspath_prepend(str(tmp_path))
    importlib.invalidate_caches()
    for name in ("PROJECT", "CACHE", "OUTPUT", "RUN"):
        root = tmp_path / name.lower()
        root.mkdir()
        monkeypatch.setenv(f"PROTEIN_WORKBENCH_{name}_ROOT", str(root))

    try:
        catalog = build_frozen_catalog((_load_registration(root_name),))
        with TestClient(
            create_application(
                frozen_catalog_override=catalog,
                _install_canonical_seed=False,
            )
        ) as client:
            response = client.get("/api/v2/catalog")
    finally:
        _forget_package(root_name)

    assert response.status_code == 200
    payload = response.json()
    validate_response("catalog_snapshot", 200, payload)
    assert any(
        contract["reference"]["contract_kind"] == "binding"
        and contract["reference"]["contract_id"] == "synthetic.echo.direct"
        for contract in payload["contracts"]
    )
    assert payload["availability"][0]["available"] is True


def test_binding_rejects_an_observation_for_an_unknown_output_port(
    tmp_path: Path,
    monkeypatch,
) -> None:
    root_name = _write_registration_package(tmp_path)
    monkeypatch.syspath_prepend(str(tmp_path))
    importlib.invalidate_caches()

    try:
        registration = _load_registration(root_name)
        binding = registration.bindings[0]
        invalid_binding = replace(
            binding,
            produced_observations=(
                ProducedObservationDefinition(
                    output_port="missing",
                    output_partition="default",
                    metric=binding.produced_observations[0].metric,
                    context_profile={"kind": "intrinsic"},
                    subject_grain="candidate",
                    source_role="subject",
                    subject_direction="input",
                    subject_port="candidate_subjects",
                    guaranteed_multiplicity="one",
                ),
            ),
        )
        with pytest.raises(
            CatalogBuildError,
            match="unknown Node output Port",
        ):
            build_frozen_catalog(
                (replace(registration, bindings=(invalid_binding,)),)
            )
    finally:
        _forget_package(root_name)


def test_binding_rejects_a_same_operation_output_candidate_subject(
    tmp_path: Path,
    monkeypatch,
) -> None:
    root_name = _write_registration_package(tmp_path)
    monkeypatch.syspath_prepend(str(tmp_path))
    importlib.invalidate_caches()

    try:
        registration = _load_registration(root_name)
        binding = registration.bindings[0]
        invalid_binding = replace(
            binding,
            produced_observations=(
                replace(
                    binding.produced_observations[0],
                    subject_direction="output",
                    subject_port="candidates",
                ),
            ),
        )
        with pytest.raises(
            CatalogBuildError,
            match="must use an admitted input Candidate source",
        ):
            build_frozen_catalog(
                (replace(registration, bindings=(invalid_binding,)),)
            )
    finally:
        _forget_package(root_name)


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        (
            {"output_port": "value"},
            "output must use exact score.collection@5.0.0",
        ),
        (
            {"subject_port": "value"},
            "subject must use exact candidate.collection@4.0.0",
        ),
        (
            {
                "context_profile": {
                    "kind": "pairwise",
                    "subject_role": "subject",
                    "reference_role": "reference",
                    "pairing_mode": "fixed_reference",
                    "normalization": "none",
                },
            },
            "reference contradicts its Context",
        ),
        (
            {
                "context_profile": {
                    "kind": "pairwise",
                    "subject_role": "subject",
                    "reference_role": "reference",
                    "pairing_mode": "per_subject_counterpart",
                    "normalization": "none",
                },
                "reference_direction": "input",
                "reference_port": "candidate_subjects",
            },
            "pairing contradicts its Context",
        ),
    ],
)
def test_binding_rejects_incompatible_produced_observation_ports(
    tmp_path: Path,
    monkeypatch,
    changes: dict[str, object],
    message: str,
) -> None:
    root_name = _write_registration_package(tmp_path)
    monkeypatch.syspath_prepend(str(tmp_path))
    importlib.invalidate_caches()

    try:
        registration = _load_registration(root_name)
        binding = registration.bindings[0]
        invalid_binding = replace(
            binding,
            produced_observations=(
                replace(
                    binding.produced_observations[0],
                    **changes,
                ),
            ),
        )
        with pytest.raises(CatalogBuildError, match=message):
            build_frozen_catalog(
                (replace(registration, bindings=(invalid_binding,)),)
            )
    finally:
        _forget_package(root_name)


def test_binding_rejects_invalid_observation_propagation_inputs(
    tmp_path: Path,
    monkeypatch,
) -> None:
    root_name = _write_registration_package(tmp_path)
    node_path = tmp_path / root_name / "synthetic" / "node.yaml"
    node_path.write_text(
        NODE_DEFINITION.replace(
            "    port_type_id: synthetic.text\n"
            "    port_type_version: \"2.1.0\"\n"
            "    required: true\n"
            "    multiplicity: one\n"
            "    scientific_meaning: Text supplied to the synthetic operation.",
            "    port_type_id: score.collection\n"
            "    port_type_version: \"5.0.0\"\n"
            "    required: true\n"
            "    multiplicity: many\n"
            "    scientific_meaning: Scores supplied to the synthetic operation.",
        )
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    importlib.invalidate_caches()

    try:
        registration = _load_registration(root_name)
        binding = registration.bindings[0]
        invalid_binding = replace(
            binding,
            produced_observations=(),
            observation_propagation=ObservationPropagationDefinition(
                mode="pass_through",
                output_port="scores",
                input_ports=("value",),
            ),
        )

        with pytest.raises(
            CatalogBuildError,
            match="propagation inputs must use multiplicity one",
        ):
            build_frozen_catalog(
                (replace(registration, bindings=(invalid_binding,)),)
            )
        invalid_binding = replace(
            invalid_binding,
            observation_propagation=ObservationPropagationDefinition(
                mode="union",
                output_port="scores",
                input_ports=("value",),
            ),
        )
        with pytest.raises(
            CatalogBuildError,
            match="mode requires unique input Ports",
        ):
            build_frozen_catalog(
                (replace(registration, bindings=(invalid_binding,)),)
            )
    finally:
        _forget_package(root_name)


def test_binding_rejects_a_context_profile_outside_the_metric_schema(
    tmp_path: Path,
    monkeypatch,
) -> None:
    root_name = _write_registration_package(tmp_path)
    monkeypatch.syspath_prepend(str(tmp_path))
    importlib.invalidate_caches()

    try:
        registration = _load_registration(root_name)
        binding = registration.bindings[0]
        invalid_binding = replace(
            binding,
            produced_observations=(
                    replace(
                        binding.produced_observations[0],
                        context_profile={
                            "kind": "pairwise",
                            "subject_role": "subject",
                            "reference_role": "reference",
                            "pairing_mode": "fixed_reference",
                            "normalization": "none",
                        },
                        reference_direction="output",
                        reference_port="candidates",
                    ),
            ),
        )
        with pytest.raises(
            CatalogBuildError,
            match="does not satisfy Metric observation_context_schema",
        ):
            build_frozen_catalog(
                (replace(registration, bindings=(invalid_binding,)),)
            )
    finally:
        _forget_package(root_name)


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("\nunknown_field: true\n", "unknown fields"),
        (
            NODE_DEFINITION.replace(
                'schema_version: "2.1.0"',
                'schema_version: "9.0.0"',
            ),
            "unsupported Node Definition schema_version",
        ),
        (
            NODE_DEFINITION.replace(
                "title: Synthetic Echo",
                "title: First title\ntitle: Second title",
            ),
            "duplicate YAML object key",
        ),
    ],
)
def test_malformed_or_open_node_definition_fails_catalog_build(
    tmp_path: Path,
    monkeypatch,
    mutation: str,
    message: str,
) -> None:
    root_name = _write_registration_package(tmp_path)
    node_path = tmp_path / root_name / "synthetic" / "node.yaml"
    if mutation.startswith("\n"):
        node_path.write_text(NODE_DEFINITION + mutation)
    else:
        node_path.write_text(mutation)
    monkeypatch.syspath_prepend(str(tmp_path))
    importlib.invalidate_caches()

    try:
        with pytest.raises(CatalogBuildError, match=message):
            build_frozen_catalog((_load_registration(root_name),))
    finally:
        _forget_package(root_name)


def test_duplicate_contract_identity_fails_closed() -> None:
    duplicate = _method("synthetic.duplicate")

    with pytest.raises(CatalogBuildError, match="duplicate contract identity"):
        build_frozen_catalog(
            (
                _registration(
                    "duplicate_owner",
                    methods=(duplicate, duplicate),
                ),
            )
        )


def test_catalog_builder_owns_method_identity_admission() -> None:
    method = replace(
        _method("synthetic.valid"),
        method_id="not a canonical identifier",
    )

    with pytest.raises(CatalogBuildError, match="method_id"):
        build_frozen_catalog(
            (_registration("method_identity_owner", methods=(method,)),)
        )


def test_catalog_builder_owns_package_identity_admission() -> None:
    registration = replace(
        _registration("valid_package"),
        package_id="not a canonical identifier",
    )

    with pytest.raises(CatalogBuildError, match="package_id"):
        build_frozen_catalog((registration,))


def test_active_catalog_rejects_multiple_versions_of_one_logical_contract() -> None:
    with pytest.raises(
        CatalogBuildError,
        match=(
            "multiple active versions for contract "
            "method:synthetic.single-active"
        ),
    ):
        build_frozen_catalog(
            (
                _registration(
                    "legacy_owner",
                    methods=(
                        _method(
                            "synthetic.single-active",
                            version="2.1.0",
                        ),
                    ),
                ),
                _registration(
                    "current_owner",
                    methods=(
                        _method(
                            "synthetic.single-active",
                            version="3.0.0",
                        ),
                    ),
                ),
            )
        )


def test_identical_exact_metric_contract_retains_common_ownership(
    tmp_path: Path,
    monkeypatch,
) -> None:
    root_name = _write_registration_package(tmp_path)
    shared_owner = tmp_path / root_name / "shared_metric"
    shared_owner.mkdir()
    (shared_owner / "__init__.py").write_text("")
    (shared_owner / "metric.yaml").write_text(METRIC_DEFINITION)
    (shared_owner / "package.py").write_text(
        """\
from core.catalog.declarations import ModulePackageRegistration
from core.catalog.definition_resource import DefinitionResource

MODULE_PACKAGE = ModulePackageRegistration(
    package_id="shared_metric",
    package_version="2.1.0",
    package_module=__package__,
    metric_definitions=(DefinitionResource("metric.yaml"),),
)
"""
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    importlib.invalidate_caches()

    try:
        synthetic = _load_registration(root_name)
        shared = importlib.import_module(
            f"{root_name}.shared_metric.package"
        ).MODULE_PACKAGE
        catalog = build_frozen_catalog((synthetic, shared))
    finally:
        _forget_package(root_name)

    assert [
        contract.reference()
        for contract in catalog.contracts
        if contract.contract_kind == "metric"
        and contract.contract_id == "synthetic.identity"
    ] == [
        catalog.require_contract(
            "metric",
            "synthetic.identity",
            "2.1.0",
        ).reference()
    ]


def test_version_conflict_is_rejected_before_binding_availability_probe(
    tmp_path: Path,
    monkeypatch,
) -> None:
    root_name = _write_registration_package(tmp_path)
    monkeypatch.syspath_prepend(str(tmp_path))
    importlib.invalidate_caches()
    probes: list[str] = []

    def binding_with_version(binding, version: str):
        def check() -> AvailabilityResult:
            probes.append(version)
            return AvailabilityResult.available()

        return replace(
            binding,
            version=version,
            availability=replace(binding.availability, check=check),
        )

    try:
        registration = _load_registration(root_name)
        binding = registration.bindings[0]
        conflicting = replace(
            registration,
            bindings=(
                binding_with_version(binding, "2.1.0"),
                binding_with_version(binding, "3.0.0"),
            ),
        )
        with pytest.raises(
            CatalogBuildError,
            match=(
                "multiple active versions for contract "
                "binding:synthetic.echo.direct"
            ),
        ):
            build_frozen_catalog((conflicting,))
    finally:
        _forget_package(root_name)

    assert probes == []


def test_conflicting_contract_identity_fails_closed() -> None:
    with pytest.raises(CatalogBuildError, match="conflicting contract identity"):
        build_frozen_catalog(
            (
                _registration(
                    "first_owner",
                    methods=(_method("synthetic.conflict"),),
                ),
                _registration(
                    "second_owner",
                    methods=(
                        _method(
                            "synthetic.conflict",
                            algorithm_identity={"name": "different"},
                        ),
                    ),
                ),
            )
        )


def test_dangling_contract_reference_fails_closed() -> None:
    dangling = _method(
        "synthetic.dangling",
        algorithm_identity={
            "dependency": ContractIdentity(
                "method",
                "synthetic.missing",
                "2.1.0",
            )
        },
    )
    with pytest.raises(CatalogBuildError, match="dangling contract reference"):
        build_frozen_catalog(
            (_registration("dangling_owner", methods=(dangling,)),)
        )


def test_expected_contract_digest_conflict_fails_closed() -> None:
    target = _method("synthetic.target")
    mismatch = _method(
        "synthetic.mismatch",
        algorithm_identity={
            "dependency": ContractIdentity(
                "method",
                "synthetic.target",
                "2.1.0",
                "not-the-target-digest",
            )
        },
    )
    with pytest.raises(CatalogBuildError, match="contract digest conflict"):
        build_frozen_catalog(
            (
                _registration(
                    "mismatch_owner",
                    methods=(target, mismatch),
                ),
            )
        )


def test_cyclic_contract_reference_graph_fails_closed() -> None:
    first = _method(
        "synthetic.cycle.first",
        algorithm_identity={
            "dependency": ContractIdentity(
                "method",
                "synthetic.cycle.second",
                "2.1.0",
            )
        },
    )
    second = _method(
        "synthetic.cycle.second",
        algorithm_identity={
            "dependency": ContractIdentity(
                "method",
                "synthetic.cycle.first",
                "2.1.0",
            )
        },
    )
    with pytest.raises(CatalogBuildError, match="cyclic contract reference graph"):
        build_frozen_catalog(
            (_registration("cycle_owner", methods=(first, second)),)
        )


def test_failed_candidate_never_mutates_an_already_published_catalog() -> None:
    published = build_frozen_catalog(
        (
            _registration(
                "published_owner",
                methods=(_method("synthetic.published"),),
            ),
        )
    )
    published_bytes = published.catalog_descriptor_bytes
    malformed = _method(
        "synthetic.malformed",
        algorithm_identity={
            "dependency": ContractIdentity(
                "method",
                "synthetic.unknown",
                "2.1.0",
            )
        },
    )

    with pytest.raises(CatalogBuildError):
        build_frozen_catalog(
            (_registration("malformed_owner", methods=(malformed,)),)
        )

    assert published.catalog_descriptor_bytes == published_bytes
    assert published.require_contract(
        "method",
        "synthetic.published",
        "2.1.0",
    ).descriptor["algorithm_identity"] == {"name": "synthetic.published"}


def test_missing_optional_dependency_does_not_hide_available_sibling(
    tmp_path: Path,
    monkeypatch,
) -> None:
    root_name = _write_registration_package(tmp_path)
    monkeypatch.syspath_prepend(str(tmp_path))
    importlib.invalidate_caches()

    try:
        registration = _load_registration(root_name)
        available_binding = registration.bindings[0]

        def missing_optional_dependency() -> AvailabilityResult:
            return AvailabilityResult.unavailable(
                "optional_dependency_missing",
                "Optional dependency synthetic_optional_provider is not installed",
                retryable=False,
            )

        unavailable_binding = replace(
            available_binding,
            binding_id="synthetic.echo.optional",
            availability=AvailabilityDeclaration(
                behavior=BehaviorReference(
                    "synthetic.echo.optional/availability",
                    "2.1.0",
                    {},
                ),
                prerequisites={
                    "python_distribution": "synthetic_optional_provider"
                },
                check=missing_optional_dependency,
            ),
            factory=ScientificOperationFactory(
                behavior=BehaviorReference(
                    "synthetic.echo.optional/factory",
                    "2.1.0",
                    {},
                ),
                build=lambda context: (_ for _ in ()).throw(
                    AssertionError("factory must stay lazy")
                ),
            ),
            readiness=ReadinessDeclaration(
                behavior=BehaviorReference(
                    "synthetic.echo.optional/readiness",
                    "2.1.0",
                    {},
                ),
                prerequisites={},
                check=lambda environment: ReadinessResult(False),
            ),
        )
        catalog = build_frozen_catalog(
            (
                replace(
                    registration,
                    bindings=(unavailable_binding, available_binding),
                ),
            )
        )
    finally:
        _forget_package(root_name)

    by_binding = {
        snapshot["binding"]["contract_id"]: snapshot
        for snapshot in _snapshot(catalog)["availability"]
    }
    assert by_binding["synthetic.echo.direct"]["available"] is True
    assert by_binding["synthetic.echo.optional"] == {
        "binding": catalog.require_contract(
            "binding",
            "synthetic.echo.optional",
            "3.0.0",
        ).reference(),
        "observed_at": by_binding["synthetic.echo.optional"]["observed_at"],
        "available": False,
        "reason": {
            "code": "optional_dependency_missing",
            "message": (
                "Optional dependency synthetic_optional_provider "
                "is not installed"
            ),
            "retryable": False,
        },
    }


@pytest.mark.parametrize(
    "checker_error",
    (
        AssertionError("availability invariant failed"),
        KeyError("missing implementation field"),
        ModuleNotFoundError(
            "No module named 'unexpected_internal_module'",
            name="unexpected_internal_module",
        ),
    ),
)
def test_availability_checker_programming_errors_abort_catalog_atomically(
    tmp_path: Path,
    monkeypatch,
    checker_error: Exception,
) -> None:
    root_name = _write_registration_package(tmp_path)
    monkeypatch.syspath_prepend(str(tmp_path))
    importlib.invalidate_caches()
    registration = _load_registration(root_name)
    binding = registration.bindings[0]

    def broken_checker() -> AvailabilityResult:
        raise checker_error

    broken = replace(
        binding,
        availability=replace(
            binding.availability,
            check=broken_checker,
        ),
    )

    try:
        with pytest.raises(type(checker_error)) as rejected:
            build_frozen_catalog(
                (replace(registration, bindings=(broken,)),)
            )
    finally:
        _forget_package(root_name)

    assert rejected.value is checker_error


def test_cross_package_exact_reference_is_order_independent() -> None:
    dependency = _method("synthetic.shared")
    consumer = _method(
        "synthetic.consumer",
        algorithm_identity={
            "dependency": ContractIdentity(
                "method",
                "synthetic.shared",
                "2.1.0",
            )
        },
    )
    first = _registration("shared_owner", methods=(dependency,))
    second = _registration("consumer_owner", methods=(consumer,))

    forward = build_frozen_catalog((first, second))
    reverse = build_frozen_catalog((second, first))

    assert forward.catalog_descriptor_bytes == reverse.catalog_descriptor_bytes
    assert forward.contract_digest == reverse.contract_digest
    dependency_contract = forward.require_contract(
        "method",
        "synthetic.shared",
        "2.1.0",
    )
    assert forward.require_contract(
        "method",
        "synthetic.consumer",
        "2.1.0",
    ).descriptor["algorithm_identity"]["dependency"] == (
        dependency_contract.reference()
    )


def test_lazy_factory_does_not_reload_definition_resources(
    tmp_path: Path,
    monkeypatch,
) -> None:
    root_name = _write_registration_package(tmp_path)
    monkeypatch.syspath_prepend(str(tmp_path))
    importlib.invalidate_caches()
    try:
        catalog = build_frozen_catalog((_load_registration(root_name),))
    finally:
        _forget_package(root_name)
    package_root = tmp_path / root_name / "synthetic"
    (package_root / "node.yaml").unlink()
    (package_root / "metric.yaml").unlink()
    monkeypatch.setenv("SYNTHETIC_FACTORY_ALLOWED", "1")

    binding = catalog.require_contract(
        "binding",
        "synthetic.echo.direct",
        "3.0.0",
    ).definition
    assert binding.factory.build(None) == {"implementation": "synthetic.echo"}


def test_operation_call_freezes_caller_owned_input_and_parameter_containers(
) -> None:
    candidate = Candidate(
        candidate_id="candidate-1",
        data=ProteinSequence(sequence="MA"),
    )
    candidates = CandidateCollection(
        collection_id="collection-1",
        item_type="protein.sequence",
        items=[candidate],
    )
    candidate_digest = CandidateDataReference(
        candidate_id="candidate-1",
        data_type_id="protein.sequence",
        content_digest="sha256:" + ("1" * 64),
    )
    inputs = {"value": ["A"], "candidates": candidates}
    node_parameters = {"nested": {"values": [1, 2]}}
    call = OperationCall(
        inputs={
            "value": admitted_port_fixture(
                inputs["value"],
                port_type_id="synthetic.text",
                value_content_digests=("sha256:" + ("3" * 64),),
            ),
            "candidates": admitted_port_fixture(
                candidates,
                port_type_id="candidate.collection",
                value_content_digests=("sha256:" + ("2" * 64),),
                candidate_data=(candidate_digest,),
            ),
        },
        node_parameters=node_parameters,
        binding_parameters={},
        effective_randomness={},
    )

    inputs["value"].append("B")
    node_parameters["nested"]["values"].append(3)
    with pytest.raises(FrozenInstanceError):
        candidate.data.sequence = "MUTATED"
    with pytest.raises(AttributeError):
        candidates.items.clear()

    assert call.inputs["value"].value == ("A",)
    admitted = call.inputs["candidates"]
    assert admitted.value is candidates
    assert admitted.value.items[0].candidate_id == "candidate-1"
    assert admitted.value.items[0].data.sequence == "MA"
    assert call.node_parameters["nested"]["values"] == (1, 2)
    assert call.inputs["candidates"].candidate_data == (
        candidate_digest,
    )
    with pytest.raises(TypeError):
        call.inputs["new"] = "value"


def test_frozen_contract_descriptor_is_immutable(
    tmp_path: Path,
    monkeypatch,
) -> None:
    catalog = _build_synthetic_catalog(tmp_path, monkeypatch)

    with pytest.raises(TypeError):
        catalog.require_contract(
            "node_type",
            "synthetic.echo",
            "3.0.0",
        ).descriptor["title"] = "mutated"


def test_binding_definition_is_immutable(
    tmp_path: Path,
    monkeypatch,
) -> None:
    catalog = _build_synthetic_catalog(tmp_path, monkeypatch)

    binding = catalog.require_contract(
        "binding",
        "synthetic.echo.direct",
        "3.0.0",
    ).definition
    with pytest.raises(FrozenInstanceError):
        binding.factory = object()


def test_observed_availability_never_changes_stable_contract_identity(
    tmp_path: Path,
    monkeypatch,
) -> None:
    root_name = _write_registration_package(tmp_path)
    monkeypatch.syspath_prepend(str(tmp_path))
    importlib.invalidate_caches()

    try:
        registration = _load_registration(root_name)
        available_catalog = build_frozen_catalog(
            (registration,),
            observed_at=datetime(
                2026,
                7,
                29,
                2,
                0,
                tzinfo=timezone.utc,
            ),
        )
        binding = registration.bindings[0]
        unavailable_catalog = build_frozen_catalog(
            (
                replace(
                    registration,
                    bindings=(
                        replace(
                            binding,
                            availability=AvailabilityDeclaration(
                                behavior=binding.availability.behavior,
                                prerequisites=(
                                    binding.availability.prerequisites
                                ),
                                check=lambda: (
                                    AvailabilityResult.unavailable(
                                        "provider_offline",
                                        "Provider is offline",
                                        retryable=True,
                                    )
                                ),
                            ),
                        ),
                    ),
                ),
            ),
            observed_at=datetime(
                2026,
                7,
                29,
                2,
                1,
                tzinfo=timezone.utc,
            ),
        )
    finally:
        _forget_package(root_name)

    assert available_catalog.catalog_descriptor_bytes == (
        unavailable_catalog.catalog_descriptor_bytes
    )
    assert available_catalog.contract_digest == (
        unavailable_catalog.contract_digest
    )
    available_snapshot = _snapshot(available_catalog)
    unavailable_snapshot = _snapshot(unavailable_catalog)
    assert available_snapshot["availability"][0]["available"] is True
    assert unavailable_snapshot["availability"][0]["available"] is False
    assert available_snapshot["availability_observed_at"] != (
        unavailable_snapshot["availability_observed_at"]
    )


def test_catalog_build_normalizes_observation_time_to_utc(
    tmp_path: Path,
    monkeypatch,
) -> None:
    catalog = _build_synthetic_catalog(
        tmp_path,
        monkeypatch,
        observed_at=datetime(
            2026,
            7,
            29,
            10,
            0,
            tzinfo=timezone(timedelta(hours=8)),
        ),
    )

    snapshot = _snapshot(catalog)

    assert {
        snapshot["availability_observed_at"],
        *(item["observed_at"] for item in snapshot["availability"]),
    } == {"2026-07-29T02:00:00Z"}


def test_catalog_build_rejects_a_naive_observation_time(
    tmp_path: Path,
    monkeypatch,
) -> None:
    with pytest.raises(
        CatalogBuildError,
        match="observation time must be timezone-aware",
    ):
        _build_synthetic_catalog(
            tmp_path,
            monkeypatch,
            observed_at=datetime(2026, 7, 29, 2, 0),
        )


def test_adapter_binding_requires_an_explicit_adapter_behavior(
    tmp_path: Path,
    monkeypatch,
) -> None:
    root_name = _write_registration_package(tmp_path)
    monkeypatch.syspath_prepend(str(tmp_path))
    importlib.invalidate_caches()

    try:
        registration = _load_registration(root_name)
        binding = replace(
            registration.bindings[0],
            execution_route="adapter",
        )
        with pytest.raises(
            CatalogBuildError,
            match="execution route and Adapter behavior are inconsistent",
        ):
            build_frozen_catalog(
                (replace(registration, bindings=(binding,)),)
            )
    finally:
        _forget_package(root_name)


def test_all_package_contract_kinds_match_canonical_digest_vectors(
    tmp_path: Path,
    monkeypatch,
) -> None:
    root_name = _write_registration_package(tmp_path)
    monkeypatch.syspath_prepend(str(tmp_path))
    importlib.invalidate_caches()

    try:
        catalog = build_frozen_catalog((_load_registration(root_name),))
    finally:
        _forget_package(root_name)

    actual = {
        ("port_type", definition.type_id): definition.contract_digest
        for definition in catalog.port_types
        if definition.type_id.startswith("synthetic.")
    }
    actual.update(
        {
            (contract.contract_kind, contract.contract_id): (
                contract.contract_digest
            )
            for contract in catalog.contracts
        }
    )
    assert actual == EXPECTED_SYNTHETIC_CONTRACT_DIGESTS


@pytest.mark.parametrize("forbidden", [b"<lambda>", b"0x", b"/private/"])
def test_canonical_descriptors_exclude_private_python_identity(
    tmp_path: Path,
    monkeypatch,
    forbidden: bytes,
) -> None:
    catalog = _build_synthetic_catalog(tmp_path, monkeypatch)

    assert all(
        forbidden not in contract.descriptor_bytes
        for contract in catalog.contracts
    )
