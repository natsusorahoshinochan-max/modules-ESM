from pathlib import Path

import pytest

from core.catalog.declarations import (
    CatalogBuildError,
    CatalogContract,
    EnvironmentFieldDeclaration,
)
from core.catalog.model import FrozenCatalog
from core.execution.environment import (
    EnvironmentConfigurationError,
    admit_environment_configuration,
)


def _catalog() -> FrozenCatalog:
    return FrozenCatalog(
        port_types=(),
        contracts=(
            CatalogContract(
                contract_kind="binding",
                contract_id="test.binding",
                contract_version="1.0.0",
                descriptor={"contract_kind": "binding"},
                environment_fields=(
                    EnvironmentFieldDeclaration("device", "json_value"),
                    EnvironmentFieldDeclaration(
                        "provider_root",
                        "filesystem_path",
                    ),
                    EnvironmentFieldDeclaration(
                        "credential_handle",
                        "credential_handle",
                        required=False,
                    ),
                ),
            ),
        ),
    )


def test_environment_configuration_is_admitted_once_per_exact_binding() -> None:
    root = Path("provider")
    configuration = admit_environment_configuration(
        _catalog(),
        {
            ("test.binding", "1.0.0"): {
                "values": {
                    "device": {"kind": "cpu", "indices": [0]},
                    "provider_root": root,
                    "credential_handle": "credential:test",
                }
            }
        },
    )

    environment = configuration.for_binding("test.binding", "1.0.0")
    assert environment["device"] == {"kind": "cpu", "indices": (0,)}
    assert environment["provider_root"] == root
    assert environment["credential_handle"] == "credential:test"
    assert not configuration.for_binding("other.binding", "1.0.0")


def test_environment_configuration_normalizes_string_filesystem_paths() -> None:
    configuration = admit_environment_configuration(
        _catalog(),
        {
            ("test.binding", "1.0.0"): {
                "values": {
                    "device": "cpu",
                    "provider_root": "provider",
                }
            }
        },
    )

    environment = configuration.for_binding("test.binding", "1.0.0")
    assert environment["provider_root"] == Path("provider")
    assert isinstance(environment["provider_root"], Path)


@pytest.mark.parametrize(
    "values, message",
    (
        (
            {"device": "cpu", "provider_client": object()},
            "undeclared fields",
        ),
        ({"device": "cpu"}, "omits required fields"),
        (
            {"device": object(), "provider_root": Path("provider")},
            "canonical I-JSON",
        ),
    ),
)
def test_environment_configuration_rejects_values_outside_the_declaration(
    values: dict[str, object],
    message: str,
) -> None:
    with pytest.raises(EnvironmentConfigurationError, match=message):
        admit_environment_configuration(
            _catalog(),
            {("test.binding", "1.0.0"): {"values": values}},
        )


@pytest.mark.parametrize("name", ("provider_client", "client_factory"))
def test_environment_declaration_rejects_caller_owned_provider_objects(
    name: str,
) -> None:
    with pytest.raises(CatalogBuildError, match="caller-owned objects"):
        EnvironmentFieldDeclaration(name, "json_value")
