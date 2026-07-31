"""Contract tests for atomic v2 Module Package discovery."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
import importlib
from pathlib import Path
import sys

from fastapi.testclient import TestClient
import pytest

from core import (
    AvailabilityDeclaration,
    AvailabilityResult,
    BehaviorReference,
    CatalogBuildError,
    ContractIdentity,
    ExecutionBindingDefinition,
    ExpectedOptionalDependencyMissing,
    LazyImplementationFactory,
    MethodDefinition,
    ModulePackageRegistration,
    ObservationPropagationDefinition,
    ProducedObservationDefinition,
    ReadinessDeclaration,
    ReadinessResult,
    build_discovered_frozen_catalog,
    build_frozen_catalog,
    discover_module_packages,
)
from core.server import create_app
from protein_workbench_public import validate_response


NODE_DEFINITION = """\
schema_version: "2.1.0"
node_type_id: synthetic.echo
version: "2.1.0"
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
outputs:
  - name: value
    port_type_id: synthetic.text
    port_type_version: "2.1.0"
    required: true
    multiplicity: one
    scientific_meaning: Text returned by the synthetic operation.
  - name: candidates
    port_type_id: candidate.collection
    port_type_version: "2.1.0"
    required: false
    multiplicity: one
    scientific_meaning: Candidates observed by the synthetic operation.
  - name: scores
    port_type_id: score.collection
    port_type_version: "2.1.0"
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
    PortTypeDefinition,
    ProducedObservationDefinition,
    ReadinessDeclaration,
    UtilityTransformDefinition,
)


def _factory():
    if os.environ.get("SYNTHETIC_FACTORY_ALLOWED") != "1":
        raise AssertionError("Catalog discovery constructed an implementation")
    return {"implementation": "synthetic.echo"}

def _validate_text(value):
    if type(value) is not str:
        raise ValueError("synthetic.text requires str")

def _identity(value, parameters):
    return float(value)

_METRIC = ContractIdentity("metric", "synthetic.identity", "2.1.0")
_METHOD = ContractIdentity("method", "synthetic.echo", "2.1.0")


MODULE_PACKAGE = ModulePackageRegistration(
    schema_version="2.1.0",
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
            version="2.1.0",
            node_type=ContractIdentity("node_type", "synthetic.echo", "2.1.0"),
            method=_METHOD,
            binding_parameters={},
            execution_route="direct",
            factory=LazyImplementationFactory(
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
)
"""

EXPECTED_SYNTHETIC_CONTRACT_DIGESTS = {
    ("binding", "synthetic.echo.direct"): (
        "sha256:c8cd1c2bb713f574b48fa016378489261c75afc2138cbc698e8690d50ca91306"
    ),
    ("method", "synthetic.echo"): (
        "sha256:e485971a5abafb8460fd29fc8978b89ed2dc4d66efec93c37b75d0289c807120"
    ),
    ("metric", "synthetic.identity"): (
        "sha256:51f0164af916ccf5c3e69c72fc2adb1be6d07c07254869e5a304e870d6bfb2e5"
    ),
    ("node_type", "synthetic.echo"): (
        "sha256:e6638f21a85016e4c306368436465ac6c484dc18a65f3aedc6d52b3b8d0b92b6"
    ),
    ("port_type", "synthetic.text"): (
        "sha256:cc3fa0e72b72eb82ced2b58697b44a98587c61b6a6ce567c133ca847d2f47870"
    ),
    ("utility_transform", "synthetic.identity"): (
        "sha256:b2e26cdb0fd42569fc280b594c2187f046c530311eb28972c4f60a9ce607b1b8"
    ),
}


def _write_discovery_root(tmp_path: Path) -> str:
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
    root_name = _write_discovery_root(tmp_path)
    monkeypatch.syspath_prepend(str(tmp_path))
    importlib.invalidate_caches()
    try:
        return build_discovered_frozen_catalog(
            root_name,
            observed_at=observed_at,
        )
    finally:
        _forget_package(root_name)


def _method(
    method_id: str,
    *,
    algorithm_identity=None,
) -> MethodDefinition:
    return MethodDefinition(
        method_id=method_id,
        version="2.1.0",
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
        schema_version="2.1.0",
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
        "2.1.0",
    ).descriptor["parameter_groups"] == ()


def test_legacy_path_artifact_port_is_rejected(
    tmp_path: Path,
    monkeypatch,
) -> None:
    root_name = _write_discovery_root(tmp_path)
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
            build_discovered_frozen_catalog(root_name)
    finally:
        _forget_package(root_name)


def test_package_owned_utility_runtime_is_resolved_by_exact_identity(
    tmp_path: Path,
    monkeypatch,
) -> None:
    catalog = _build_synthetic_catalog(tmp_path, monkeypatch)

    assert catalog.require_utility_transform(
        "synthetic.identity",
        "2.1.0",
    )(0.75, {}) == 0.75


def test_binding_keeps_its_factory_lazy_during_catalog_build(
    tmp_path: Path,
    monkeypatch,
) -> None:
    catalog = _build_synthetic_catalog(tmp_path, monkeypatch)

    assert catalog.require_factory(
        "synthetic.echo.direct",
        "2.1.0",
    ).behavior.behavior_id == "synthetic.echo/factory"


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
    assert catalog.public_snapshot(
        protocol_digest="sha256:" + ("0" * 64),
    )["availability"] == [{
        "binding": {
            "contract_kind": "binding",
            "contract_id": "synthetic.echo.direct",
            "contract_version": "2.1.0",
            "contract_digest": EXPECTED_SYNTHETIC_CONTRACT_DIGESTS[
                ("binding", "synthetic.echo.direct")
            ],
        },
        "observed_at": "2026-07-29T01:02:03Z",
        "available": True,
    }]


def test_backend_publishes_the_same_discovered_catalog_snapshot(
    tmp_path: Path,
    monkeypatch,
) -> None:
    root_name = _write_discovery_root(tmp_path)
    monkeypatch.syspath_prepend(str(tmp_path))
    importlib.invalidate_caches()
    for name in ("PROJECT", "CACHE", "OUTPUT", "RUN"):
        root = tmp_path / name.lower()
        root.mkdir()
        monkeypatch.setenv(f"PROTEIN_WORKBENCH_{name}_ROOT", str(root))

    try:
        with TestClient(
            create_app(module_packages_package=root_name)
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
    root_name = _write_discovery_root(tmp_path)
    monkeypatch.syspath_prepend(str(tmp_path))
    importlib.invalidate_caches()

    try:
        registration = discover_module_packages(root_name)[0]
        binding = registration.bindings[0]
        invalid_binding = replace(
            binding,
            produced_observations=(
                ProducedObservationDefinition(
                    output_port="missing",
                    metric=binding.produced_observations[0].metric,
                    context_profile={"kind": "intrinsic"},
                    subject_grain="candidate",
                    source_role="subject",
                    subject_direction="output",
                    subject_port="value",
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


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        (
            {"output_port": "value"},
            "output must use exact score.collection@2.1.0",
        ),
        (
            {"subject_port": "value"},
            "subject must use exact candidate.collection@2.1.0",
        ),
    ],
)
def test_binding_rejects_incompatible_produced_observation_ports(
    tmp_path: Path,
    monkeypatch,
    changes: dict[str, str],
    message: str,
) -> None:
    root_name = _write_discovery_root(tmp_path)
    monkeypatch.syspath_prepend(str(tmp_path))
    importlib.invalidate_caches()

    try:
        registration = discover_module_packages(root_name)[0]
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


def test_binding_rejects_many_valued_observation_propagation_inputs(
    tmp_path: Path,
    monkeypatch,
) -> None:
    root_name = _write_discovery_root(tmp_path)
    node_path = tmp_path / root_name / "synthetic" / "node.yaml"
    node_path.write_text(
        NODE_DEFINITION.replace(
            "    port_type_id: synthetic.text\n"
            "    port_type_version: \"2.1.0\"\n"
            "    required: true\n"
            "    multiplicity: one\n"
            "    scientific_meaning: Text supplied to the synthetic operation.",
            "    port_type_id: score.collection\n"
            "    port_type_version: \"2.1.0\"\n"
            "    required: true\n"
            "    multiplicity: many\n"
            "    scientific_meaning: Scores supplied to the synthetic operation.",
        )
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    importlib.invalidate_caches()

    try:
        registration = discover_module_packages(root_name)[0]
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
    finally:
        _forget_package(root_name)


def test_binding_rejects_a_context_profile_outside_the_metric_schema(
    tmp_path: Path,
    monkeypatch,
) -> None:
    root_name = _write_discovery_root(tmp_path)
    monkeypatch.syspath_prepend(str(tmp_path))
    importlib.invalidate_caches()

    try:
        registration = discover_module_packages(root_name)[0]
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
    root_name = _write_discovery_root(tmp_path)
    node_path = tmp_path / root_name / "synthetic" / "node.yaml"
    if mutation.startswith("\n"):
        node_path.write_text(NODE_DEFINITION + mutation)
    else:
        node_path.write_text(mutation)
    monkeypatch.syspath_prepend(str(tmp_path))
    importlib.invalidate_caches()

    try:
        with pytest.raises(CatalogBuildError, match=message):
            build_discovered_frozen_catalog(root_name)
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
    wrong_digest = "sha256:" + ("f" * 64)
    mismatch = _method(
        "synthetic.mismatch",
        algorithm_identity={
            "dependency": ContractIdentity(
                "method",
                "synthetic.target",
                "2.1.0",
                wrong_digest,
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


def test_discovery_ignores_recursive_definitions_and_import_side_effects(
    tmp_path: Path,
    monkeypatch,
) -> None:
    root_name = "non_recursive_packages"
    root = tmp_path / root_name
    root.mkdir()
    (root / "__init__.py").write_text("")
    legacy = root / "legacy_node"
    legacy.mkdir()
    (legacy / "__init__.py").write_text(
        "raise AssertionError('legacy package must not be imported')"
    )
    (legacy / "definition.yaml").write_text(NODE_DEFINITION)
    nested = legacy / "nested"
    nested.mkdir()
    (nested / "package.py").write_text(
        "raise AssertionError('recursive package.py must not be imported')"
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    importlib.invalidate_caches()

    try:
        assert discover_module_packages(root_name) == ()
    finally:
        _forget_package(root_name)


def test_missing_optional_dependency_does_not_hide_available_sibling(
    tmp_path: Path,
    monkeypatch,
) -> None:
    root_name = _write_discovery_root(tmp_path)
    monkeypatch.syspath_prepend(str(tmp_path))
    importlib.invalidate_caches()

    try:
        registration = discover_module_packages(root_name)[0]
        available_binding = registration.bindings[0]

        def missing_optional_dependency() -> AvailabilityResult:
            raise ExpectedOptionalDependencyMissing(
                "synthetic_optional_provider",
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
            factory=LazyImplementationFactory(
                behavior=BehaviorReference(
                    "synthetic.echo.optional/factory",
                    "2.1.0",
                    {},
                ),
                build=lambda: (_ for _ in ()).throw(
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
        for snapshot in catalog.public_snapshot(
            protocol_digest="sha256:" + ("0" * 64)
        )["availability"]
    }
    assert by_binding["synthetic.echo.direct"]["available"] is True
    assert by_binding["synthetic.echo.optional"] == {
        "binding": catalog.require_contract(
            "binding",
            "synthetic.echo.optional",
            "2.1.0",
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
    root_name = _write_discovery_root(tmp_path)
    monkeypatch.syspath_prepend(str(tmp_path))
    importlib.invalidate_caches()
    registration = discover_module_packages(root_name)[0]
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
        with pytest.raises(
            CatalogBuildError,
            match="Availability checker .* failed",
        ) as rejected:
            build_frozen_catalog(
                (replace(registration, bindings=(broken,)),)
            )
    finally:
        _forget_package(root_name)

    assert rejected.value.__cause__ is checker_error


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
    root_name = _write_discovery_root(tmp_path)
    monkeypatch.syspath_prepend(str(tmp_path))
    importlib.invalidate_caches()
    try:
        catalog = build_discovered_frozen_catalog(root_name)
    finally:
        _forget_package(root_name)
    package_root = tmp_path / root_name / "synthetic"
    (package_root / "node.yaml").unlink()
    (package_root / "metric.yaml").unlink()
    monkeypatch.setenv("SYNTHETIC_FACTORY_ALLOWED", "1")

    assert catalog.require_factory(
        "synthetic.echo.direct",
        "2.1.0",
    ).build() == {"implementation": "synthetic.echo"}


def test_frozen_contract_descriptor_is_immutable(
    tmp_path: Path,
    monkeypatch,
) -> None:
    catalog = _build_synthetic_catalog(tmp_path, monkeypatch)

    with pytest.raises(TypeError):
        catalog.require_contract(
            "node_type",
            "synthetic.echo",
            "2.1.0",
        ).descriptor["title"] = "mutated"


def test_frozen_runtime_factory_view_is_immutable(
    tmp_path: Path,
    monkeypatch,
) -> None:
    catalog = _build_synthetic_catalog(tmp_path, monkeypatch)

    with pytest.raises(TypeError):
        catalog.factories[("synthetic.echo.direct", "2.1.0")] = object()


def test_observed_availability_never_changes_stable_contract_identity(
    tmp_path: Path,
    monkeypatch,
) -> None:
    root_name = _write_discovery_root(tmp_path)
    monkeypatch.syspath_prepend(str(tmp_path))
    importlib.invalidate_caches()

    try:
        registration = discover_module_packages(root_name)[0]
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
    available_snapshot = available_catalog.public_snapshot(
        protocol_digest="sha256:" + ("0" * 64)
    )
    unavailable_snapshot = unavailable_catalog.public_snapshot(
        protocol_digest="sha256:" + ("0" * 64)
    )
    assert available_snapshot["availability"][0]["available"] is True
    assert unavailable_snapshot["availability"][0]["available"] is False
    assert available_snapshot["availability_observed_at"] != (
        unavailable_snapshot["availability_observed_at"]
    )


def test_snapshot_observation_override_updates_every_availability_time(
    tmp_path: Path,
    monkeypatch,
) -> None:
    catalog = _build_synthetic_catalog(tmp_path, monkeypatch)
    override = datetime(
        2026,
        7,
        29,
        10,
        0,
        tzinfo=timezone(timedelta(hours=8)),
    )

    snapshot = catalog.public_snapshot(
        protocol_digest="sha256:" + ("0" * 64),
        observed_at=override,
    )

    assert {
        snapshot["availability_observed_at"],
        *(item["observed_at"] for item in snapshot["availability"]),
    } == {"2026-07-29T02:00:00Z"}


def test_snapshot_rejects_a_naive_observation_time(
    tmp_path: Path,
    monkeypatch,
) -> None:
    catalog = _build_synthetic_catalog(tmp_path, monkeypatch)

    with pytest.raises(
        CatalogBuildError,
        match="observation time must be timezone-aware",
    ):
        catalog.public_snapshot(
            protocol_digest="sha256:" + ("0" * 64),
            observed_at=datetime(2026, 7, 29, 2, 0),
        )


def test_adapter_binding_requires_an_explicit_adapter_behavior(
    tmp_path: Path,
    monkeypatch,
) -> None:
    root_name = _write_discovery_root(tmp_path)
    monkeypatch.syspath_prepend(str(tmp_path))
    importlib.invalidate_caches()

    try:
        binding = discover_module_packages(root_name)[0].bindings[0]
        with pytest.raises(
            CatalogBuildError,
            match="adapter route requires an explicit Adapter behavior",
        ):
            replace(binding, execution_route="adapter")
    finally:
        _forget_package(root_name)


def test_all_package_contract_kinds_match_canonical_digest_vectors(
    tmp_path: Path,
    monkeypatch,
) -> None:
    root_name = _write_discovery_root(tmp_path)
    monkeypatch.syspath_prepend(str(tmp_path))
    importlib.invalidate_caches()

    try:
        catalog = build_discovered_frozen_catalog(root_name)
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
