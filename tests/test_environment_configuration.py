from pathlib import Path
from types import SimpleNamespace
from datetime import datetime, timezone

import pytest

from core.catalog.declarations import (
    EnvironmentFieldDeclaration,
)
from core.catalog.model import CatalogContract, FrozenCatalog
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
                descriptor={"contract_kind": "binding"},
                dependencies=(),
                definition=SimpleNamespace(
                    environment_fields=(
                        EnvironmentFieldDeclaration(
                            "provider_root",
                            "filesystem_path",
                        ),
                        EnvironmentFieldDeclaration(
                            "credential_handle",
                            "credential_handle",
                            required=False,
                        ),
                    )
                ),
            ),
        ),
        availability=(),
        availability_observed_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )


def test_environment_configuration_is_admitted_once_per_binding() -> None:
    root = Path("provider")
    configuration = admit_environment_configuration(
        _catalog(),
        {
            "test.binding": {
                "provider_root": root,
                "credential_handle": "credential:test",
            }
        },
    )

    environment = configuration.for_binding("test.binding")
    assert environment["provider_root"] == root
    assert environment["credential_handle"] == "credential:test"
    assert not configuration.for_binding("other.binding")


def test_environment_configuration_normalizes_string_filesystem_paths() -> None:
    configuration = admit_environment_configuration(
        _catalog(),
        {
            "test.binding": {"provider_root": "provider"}
        },
    )

    environment = configuration.for_binding("test.binding")
    assert environment["provider_root"] == Path("provider")
    assert isinstance(environment["provider_root"], Path)


@pytest.mark.parametrize(
    "values, message",
    (
        (
            {"provider_root": Path("provider"), "provider_client": object()},
            "undeclared fields",
        ),
        ({}, "omits required fields"),
    ),
)
def test_environment_configuration_rejects_values_outside_the_declaration(
    values: dict[str, object],
    message: str,
) -> None:
    with pytest.raises(EnvironmentConfigurationError, match=message):
        admit_environment_configuration(
            _catalog(),
            {"test.binding": values},
        )
