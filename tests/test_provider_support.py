"""Shared Provider support owns only checkout and credential-file hygiene."""

from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import subprocess

import pytest

from core.provider_support import (
    ProviderInstallationUnavailable,
    read_private_credential_file,
    validate_installed_provider_checkout,
    validate_provider_checkout,
)


def test_private_credential_is_read_without_exposing_its_value(
    tmp_path,
) -> None:
    token_path = tmp_path / "biohub-token"
    token_path.write_text("secret-token\n")
    token_path.chmod(0o600)

    assert read_private_credential_file(token_path.resolve()) == "secret-token"


def test_private_credential_read_rejects_public_permissions(tmp_path) -> None:
    token_path = tmp_path / "biohub-token"
    token_path.write_text("secret-token\n")
    token_path.chmod(0o644)

    try:
        read_private_credential_file(token_path.resolve())
    except PermissionError as error:
        assert str(error) == "credential file is not private"
    else:
        raise AssertionError("public credential permissions were admitted")
    finally:
        os.chmod(token_path, 0o600)


def test_private_credential_read_does_not_follow_symlinks(tmp_path) -> None:
    token_path = tmp_path / "biohub-token"
    token_path.write_text("secret-token\n")
    token_path.chmod(0o600)
    link_path = tmp_path / "biohub-token-link"
    link_path.symlink_to(token_path)

    with pytest.raises(FileNotFoundError, match="unavailable"):
        read_private_credential_file(link_path)


def test_private_credential_read_requires_an_absolute_path() -> None:
    with pytest.raises(FileNotFoundError, match="absolute"):
        read_private_credential_file("relative-token")


@pytest.mark.parametrize("payload", (b"", b"x" * (16 * 1024 + 1)))
def test_private_credential_read_rejects_invalid_sizes(
    tmp_path,
    payload: bytes,
) -> None:
    token_path = tmp_path / "biohub-token"
    token_path.write_bytes(payload)
    token_path.chmod(0o600)

    with pytest.raises(PermissionError, match="private"):
        read_private_credential_file(token_path)


def test_private_credential_read_rejects_hardlinks(tmp_path) -> None:
    token_path = tmp_path / "biohub-token"
    token_path.write_text("secret-token\n")
    token_path.chmod(0o600)
    os.link(token_path, tmp_path / "second-link")

    with pytest.raises(PermissionError, match="private"):
        read_private_credential_file(token_path)


def test_private_credential_read_rejects_fifo_without_blocking(tmp_path) -> None:
    fifo_path = tmp_path / "biohub-token"
    os.mkfifo(fifo_path, mode=0o600)

    with pytest.raises(PermissionError, match="private"):
        read_private_credential_file(fifo_path)


def test_private_credential_read_rejects_metadata_change_during_read(
    monkeypatch,
    tmp_path,
) -> None:
    import core.provider_support as support

    token_path = tmp_path / "biohub-token"
    token_path.write_text("secret-token\n")
    token_path.chmod(0o600)
    original_read = support.os.read

    def read_and_change_metadata(descriptor: int, size: int) -> bytes:
        payload = original_read(descriptor, size)
        os.utime(token_path, ns=(1, 1))
        return payload

    monkeypatch.setattr(support.os, "read", read_and_change_metadata)

    with pytest.raises(PermissionError, match="private"):
        read_private_credential_file(token_path)


class _Distribution:
    def __init__(
        self,
        direct_url: dict[str, object] | None,
        package_root: Path,
    ) -> None:
        self._direct_url = direct_url
        self._package_root = package_root

    def read_text(self, name: str) -> str | None:
        assert name == "direct_url.json"
        return None if self._direct_url is None else json.dumps(self._direct_url)

    def locate_file(self, name: str) -> Path:
        assert name == "provider_package"
        return self._package_root


def test_installed_checkout_admits_exact_pep610_revision(
    monkeypatch,
    tmp_path,
) -> None:
    package_root = tmp_path / "provider_package"
    package_root.mkdir()
    revision = "a" * 40
    distribution = _Distribution(
        {
            "vcs_info": {
                "vcs": "git",
                "commit_id": revision,
                "requested_revision": revision,
            }
        },
        package_root,
    )
    monkeypatch.setattr(
        "core.provider_support.importlib.metadata.distribution",
        lambda _name: distribution,
    )

    assert validate_installed_provider_checkout(
        "provider_package",
        revision,
    ) == package_root.resolve()


def test_installed_checkout_rejects_revision_drift(
    monkeypatch,
    tmp_path,
) -> None:
    package_root = tmp_path / "provider_package"
    package_root.mkdir()
    distribution = _Distribution(
        {
            "vcs_info": {
                "vcs": "git",
                "commit_id": "a" * 40,
                "requested_revision": "a" * 40,
            }
        },
        package_root,
    )
    monkeypatch.setattr(
        "core.provider_support.importlib.metadata.distribution",
        lambda _name: distribution,
    )

    with pytest.raises(
        ProviderInstallationUnavailable,
        match="locked revision",
    ):
        validate_installed_provider_checkout(
            "provider_package",
            "b" * 40,
        )


@pytest.mark.parametrize(
    "direct_url",
    (
        None,
        {"archive_info": {}},
        {
            "vcs_info": {
                "vcs": "hg",
                "commit_id": "a" * 40,
                "requested_revision": "a" * 40,
            }
        },
        {
            "vcs_info": {
                "vcs": "git",
                "commit_id": "a" * 40,
                "requested_revision": "main",
            }
        },
    ),
)
def test_installed_checkout_rejects_non_exact_provenance(
    monkeypatch,
    tmp_path,
    direct_url: dict[str, object] | None,
) -> None:
    package_root = tmp_path / "provider_package"
    package_root.mkdir()
    distribution = _Distribution(direct_url, package_root)
    monkeypatch.setattr(
        "core.provider_support.importlib.metadata.distribution",
        lambda _name: distribution,
    )

    with pytest.raises(ProviderInstallationUnavailable):
        validate_installed_provider_checkout("provider_package", "a" * 40)


def _editable_distribution(
    tmp_path: Path,
    *,
    src_layout: bool = True,
) -> tuple[_Distribution, Path, str]:
    checkout = tmp_path / "provider-checkout"
    package_root = checkout / ("src" if src_layout else "") / "provider_package"
    package_root.mkdir(parents=True)
    (package_root / "__init__.py").write_text("\n")
    subprocess.run(["git", "init", "-q"], cwd=checkout, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.invalid"],
        cwd=checkout,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Provider Test"],
        cwd=checkout,
        check=True,
    )
    subprocess.run(["git", "add", "."], cwd=checkout, check=True)
    subprocess.run(
        ["git", "commit", "-q", "-m", "provider fixture"],
        cwd=checkout,
        check=True,
    )
    revision = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=checkout,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    return (
        _Distribution(
            {
                "url": checkout.as_uri(),
                "dir_info": {"editable": True},
            },
            package_root,
        ),
        checkout,
        revision,
    )


def test_editable_checkout_admits_exact_head(monkeypatch, tmp_path) -> None:
    distribution, checkout, revision = _editable_distribution(tmp_path)
    monkeypatch.setattr(
        "core.provider_support.importlib.metadata.distribution",
        lambda _name: distribution,
    )

    assert validate_installed_provider_checkout(
        "provider_package",
        revision,
    ) == checkout.resolve()


def test_editable_checkout_rejects_head_drift(monkeypatch, tmp_path) -> None:
    distribution, _, _ = _editable_distribution(tmp_path)
    monkeypatch.setattr(
        "core.provider_support.importlib.metadata.distribution",
        lambda _name: distribution,
    )

    with pytest.raises(
        ProviderInstallationUnavailable,
        match="locked revision",
    ):
        validate_installed_provider_checkout(
            "provider_package",
            "b" * 40,
        )


def test_editable_checkout_admits_root_package_layout(monkeypatch, tmp_path) -> None:
    distribution, checkout, revision = _editable_distribution(
        tmp_path,
        src_layout=False,
    )
    monkeypatch.setattr(
        "core.provider_support.importlib.metadata.distribution",
        lambda _name: distribution,
    )

    assert validate_installed_provider_checkout(
        "provider_package",
        revision,
    ) == checkout.resolve()


def _git_checkout(tmp_path: Path) -> tuple[Path, str]:
    checkout = tmp_path / "provider-checkout"
    checkout.mkdir()
    (checkout / "provider.py").write_text("VALUE = 1\n")
    subprocess.run(["git", "init", "-q"], cwd=checkout, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.invalid"],
        cwd=checkout,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Provider Test"],
        cwd=checkout,
        check=True,
    )
    subprocess.run(["git", "add", "."], cwd=checkout, check=True)
    subprocess.run(
        ["git", "commit", "-q", "-m", "provider fixture"],
        cwd=checkout,
        check=True,
    )
    revision = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=checkout,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    return checkout, revision


def test_configured_checkout_admits_exact_root_and_head(tmp_path) -> None:
    checkout, revision = _git_checkout(tmp_path)

    assert validate_provider_checkout(checkout, revision) == checkout.resolve()


def test_configured_checkout_rejects_nested_root(tmp_path) -> None:
    checkout, revision = _git_checkout(tmp_path)
    nested = checkout / "nested"
    nested.mkdir()

    with pytest.raises(ProviderInstallationUnavailable, match="checkout root"):
        validate_provider_checkout(nested, revision)


def test_configured_checkout_rejects_head_drift(tmp_path) -> None:
    checkout, _ = _git_checkout(tmp_path)

    with pytest.raises(ProviderInstallationUnavailable, match="locked revision"):
        validate_provider_checkout(checkout, "b" * 40)


def test_provider_support_is_the_only_cross_extension_support_owner() -> None:
    assert importlib.util.find_spec("modules.provider_contract") is None
    support_source = Path(
        __import__("core.provider_support", fromlist=["__file__"]).__file__
    ).read_text()

    assert "provider_client" not in support_source
    assert "client_factory" not in support_source
    assert "Adapter" not in support_source
