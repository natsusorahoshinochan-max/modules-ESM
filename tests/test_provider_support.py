"""Shared Provider support owns credential-file hygiene."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from core.provider_support import (
    read_private_credential_file,
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


def test_provider_support_excludes_package_specific_adapter_injection() -> None:
    support_source = Path(
        __import__("core.provider_support", fromlist=["__file__"]).__file__
    ).read_text()

    assert "provider_client" not in support_source
    assert "client_factory" not in support_source
    assert "Adapter" not in support_source
